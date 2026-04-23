"""API-Tennis WebSocket worker.

Connects to wss://wss.api-tennis.com/live, receives list-shaped messages
containing match state updates (game scores, point-by-point, set/match
status), and routes each item to the Polymarket-owned match_id via
cross_feed overrides. Routing failures land in api_tennis/_unresolved/.

Session 3.1 worker. Raw preservation per plan §5.2 — every item of every
message is archived with arrived_at_ms, no dedup. Phase 7 analysis
decides dedup semantics against real data.

Connection model:
  - Single WebSocket to wss.api-tennis.com/live with ?APIkey=... query
    auth. No handshake beyond the URL. No subscribe/unsubscribe protocol
    — the server pushes whatever the account has access to.
  - Messages arrive as JSON lists. Each list item is a match-state
    snapshot (all 24 fields per probe 2).
  - No separate message types. No heartbeat frames. Reconnection on
    transport errors, same exponential backoff as Polymarket.

Message handling:
  arrived_at_ms is captured at message receipt (one timestamp per
  message; all items in that message share it). The worker then
  iterates list items, resolves each to a match_id, and appends one
  JSONL record per item.

  Record shape:
    {
      "arrived_at_ms": <int>,
      "source": "api_tennis",
      "match_id": <str>,
      "match_id_resolved": <bool>,
      "event_key": <int>,
      "raw": <full item dict from the API-Tennis payload>
    }

  This mirrors the Polymarket record shape for cross-source consistency
  at Phase 7 analysis time.

Routing model:
  cross_feed.load_overrides() is called on each (re)connect, same pattern
  as the Polymarket resolver. Operator edits cross_feed_overrides.yaml
  mid-match and the next reconnect picks up the new entries. Unresolved
  events continue arriving in _unresolved until curated.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # older websockets library layouts
    try:
        from websockets.client import connect as ws_connect  # type: ignore[no-redef]
    except ImportError:
        import websockets
        ws_connect = websockets.connect  # type: ignore[assignment]

from . import archive
from . import cross_feed
from .config import (
    API_TENNIS_KEY,
    API_TENNIS_TIMEZONE,
    API_TENNIS_WS_BASE,
    WS_RECONNECT_FACTOR,
    WS_RECONNECT_INITIAL_SECONDS,
    WS_RECONNECT_MAX_SECONDS,
)


log = logging.getLogger("capture.api_tennis_ws")


class ApiTennisWorker:
    """Single-connection API-Tennis WS worker with reconnect + routing."""

    def __init__(self) -> None:
        self._overrides: dict[int, str] = {}
        self._backoff: float = WS_RECONNECT_INITIAL_SECONDS

    async def run_forever(self) -> None:
        """Supervisor entry point. Loops over connect-receive cycles with
        exponential backoff on transport failures. Returns only on
        CancelledError (graceful shutdown)."""
        if not API_TENNIS_KEY:
            log.error(
                "API_TENNIS_KEY not set in environment; worker cannot "
                "connect. Staying idle. Set the env var and restart."
            )
            # Idle-wait forever rather than crash-loop — operator will fix
            # config and redeploy. No data-integrity risk from being idle.
            await asyncio.Future()  # never resolves
            return

        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                log.info("API-Tennis worker cancelled; exiting.")
                raise
            except Exception as exc:  # noqa: BLE001 — reconnect on any transport error
                log.warning(
                    "API-Tennis WS error: %s. Reconnecting in %.1fs…",
                    exc,
                    self._backoff,
                )
                await asyncio.sleep(self._backoff)
                self._backoff = min(
                    self._backoff * WS_RECONNECT_FACTOR,
                    WS_RECONNECT_MAX_SECONDS,
                )

    async def _run_once(self) -> None:
        """Single connect-receive cycle. Returns on connection close."""
        # Re-read overrides on each connect cycle — operator may have
        # added entries while we were running.
        self._overrides = cross_feed.load_overrides()

        url = (
            f"{API_TENNIS_WS_BASE}"
            f"?APIkey={API_TENNIS_KEY}"
            f"&timezone={API_TENNIS_TIMEZONE}"
        )

        log.info(
            "Opening API-Tennis WS (%d override(s) loaded).",
            len(self._overrides),
        )

        async with ws_connect(url, open_timeout=10, ping_interval=20) as ws:
            # Reset backoff on successful connect.
            self._backoff = WS_RECONNECT_INITIAL_SECONDS
            log.info("API-Tennis WS connected. Streaming events.")

            async for raw in ws:
                arrived_ms = archive.arrived_at_ms()
                self._handle_message(raw, arrived_ms)

        log.info("API-Tennis WS closed by server; will reconnect.")

    def _handle_message(self, raw: str | bytes, arrived_ms: int) -> None:
        """Parse one WS frame and archive each contained match-state item.

        Empirically (probe 2) every message is a JSON list of match-state
        dicts, 1-10 items per message. We defensively handle other shapes
        rather than crash — the worker must survive schema surprises.
        """
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                log.warning("API-Tennis WS: non-UTF8 frame, skipping.")
                return

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("API-Tennis WS: non-JSON frame (%s), skipping.", exc)
            return

        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            # Shape defensively: if it's a single-item dict with event_key,
            # treat as list-of-one; else log and skip.
            if "event_key" in parsed:
                log.warning(
                    "API-Tennis WS: single-dict message (expected list); "
                    "treating as list-of-one."
                )
                items = [parsed]
            else:
                log.warning(
                    "API-Tennis WS: dict without event_key (keys=%s); "
                    "skipping.",
                    sorted(parsed.keys())[:10],
                )
                return
        else:
            log.warning(
                "API-Tennis WS: unexpected payload type %s; skipping.",
                type(parsed).__name__,
            )
            return

        date_str = archive.utc_date_str()

        for item in items:
            if not isinstance(item, dict):
                log.warning(
                    "API-Tennis WS: non-dict list item (type=%s); skipping.",
                    type(item).__name__,
                )
                continue
            self._archive_item(item, arrived_ms, date_str)

    def _archive_item(
        self,
        item: dict[str, Any],
        arrived_ms: int,
        date_str: str,
    ) -> None:
        """Route one match-state item to the appropriate archive path."""
        event_key = item.get("event_key")
        # API-Tennis uses int event_keys in practice; be defensive about
        # string variants.
        if isinstance(event_key, str):
            try:
                event_key = int(event_key)
            except ValueError:
                event_key = None

        match_id = None
        if isinstance(event_key, int):
            match_id = cross_feed.match_id_for_event_key(
                event_key, self._overrides
            )

        record = {
            "arrived_at_ms": arrived_ms,
            "source": "api_tennis",
            "match_id": match_id if match_id else "_unresolved",
            "match_id_resolved": match_id is not None,
            "event_key": event_key,
            "raw": item,
        }

        if match_id:
            path = archive.api_tennis_path(match_id, date_str)
        else:
            path = archive.api_tennis_path("_unresolved", date_str)
        archive.append_jsonl(path, record)
