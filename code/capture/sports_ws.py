"""Polymarket US Sports/Markets WebSocket worker.

Uses the official `polymarket-us` SDK (pinned to 0.1.2 in pyproject.toml
to match PM-Tennis's validation). The SDK handles Ed25519 handshake auth,
heartbeat/pong, and event parsing. We register event handlers and append
raw payloads to per-match JSONL archives.

Path-A rationale (per plan §5.4 revision):
  Independence between this study and PM-Tennis is at the data and analysis
  layers, not the transport layer. Using the same SDK as PM-Tennis (which
  empirically validated it through H-023 live sweeps) is lower-risk than
  hand-rolling the Ed25519 handshake and would not have produced meaningful
  independence anyway — both clients receive the same payloads from the
  same server.

Subscription model:
  - One MarketsWebSocket per sub-100 batch of slugs. SDK's `client.ws.markets()`
    is a factory — each call returns a fresh connection-capable instance.
    We open N of these (N = ceil(slugs / 100)).
  - For each connection we call both `subscribe_market_data` (full order
    book state, feeds Q3 reaction-time analysis) and `subscribe_trades`
    (execution events, feeds Q3/Q4 with trade-level signal). The SDK
    collapses what plan §4 calls "Sports WS" and "CLOB WS" into one
    MarketsWebSocket with parallel subscription types; session 2.2
    honors the plan's two-worker commitment by subscribing to both
    streams on the same connection.
  - PM-Tennis's stress-test uses the generic subscribe() with
    SUBSCRIPTION_TYPE_MARKET_DATA; we use the convenience method (identical
    wire behavior).
  - We register handlers for all six events the SDK emits on markets:
    market_data, market_data_lite, trade, heartbeat, error, close. Our
    subscriptions produce market_data + trade + heartbeat/error/close;
    extra handlers cost nothing and guard against SDK default changes.

Raw preservation (plan §5.2):
  The SDK parses JSON and dispatches by event name. We persist the parsed
  payload (not the wire bytes) — the SDK's parse is trivial and deterministic,
  so payload == json.loads(wire). Recording it post-parse is functionally
  equivalent to raw preservation. The arrived_at_ms timestamp is captured at
  handler entry, which is the closest point to wire-arrival we can get from
  inside the SDK.

Reconnect model:
  - SDK raises WebSocketError / APIConnectionError on connection loss. We
    catch, log, back off, and reconnect with exponential backoff capped at
    WS_RECONNECT_MAX_SECONDS.
  - On successful connect, backoff resets.
  - Discovery's active slug set is re-read on each (re)connect; if matches
    have been added/removed since last connect, the new set is picked up.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from polymarket_us import (
    APIConnectionError,
    APITimeoutError,
    AsyncPolymarketUS,
    AuthenticationError,
    PolymarketUSError,
    WebSocketError,
)

from . import archive
from .config import (
    MARKETS_WS_SLUG_CAP,
    POLYMARKET_US_API_KEY_ID,
    POLYMARKET_US_API_SECRET_KEY,
    WS_RECONNECT_FACTOR,
    WS_RECONNECT_INITIAL_SECONDS,
    WS_RECONNECT_MAX_SECONDS,
)
from .discovery import DiscoveryLoop

log = logging.getLogger("capture.sports_ws")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def batch_slugs(slugs: list[str], cap: int) -> list[list[str]]:
    """Partition slugs into sub-cap chunks (documented 100-slug limit)."""
    return [slugs[i : i + cap] for i in range(0, len(slugs), cap)]


def extract_slug_from_event(payload: dict[str, Any]) -> str | None:
    """Pull the market_slug out of an inbound payload.

    SDK event shapes (from polymarket_us/websocket/markets.py _handle_message):
      - market_data         → {"marketData": {...}}
      - market_data_lite    → {"marketDataLite": {...}}
      - trade               → {"trade": {...}}
    The `marketSlug` field is inside the inner object. PM-Tennis §14.3
    confirmed at n=1 that market_data payloads carry `marketSlug`.
    """
    for container in ("marketData", "marketDataLite", "trade"):
        inner = payload.get(container)
        if isinstance(inner, dict):
            slug = inner.get("marketSlug") or inner.get("market_slug")
            if isinstance(slug, str) and slug:
                return slug
    # Fallback: top-level
    for field in ("marketSlug", "market_slug", "slug"):
        val = payload.get(field)
        if isinstance(val, str) and val:
            return val
    return None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class SportsWorker:
    """Long-running Markets WS capture worker (SDK-backed).

    On each (re)connect:
      1. Read current slugs from DiscoveryLoop.
      2. Batch into sub-100 groups.
      3. For each batch, spawn one MarketsWebSocket, register handlers,
         connect, subscribe to market_data AND trades.
      4. Await until any connection fails; all connections are torn down
         together; outer loop reconnects after backoff.
    """

    def __init__(self, discovery: DiscoveryLoop) -> None:
        self._discovery = discovery
        self._backoff = WS_RECONNECT_INITIAL_SECONDS
        self._client: AsyncPolymarketUS | None = None

    async def run_forever(self) -> None:
        log.info("Sports WS worker starting (polymarket-us SDK mode)")
        if not POLYMARKET_US_API_KEY_ID or not POLYMARKET_US_API_SECRET_KEY:
            log.error(
                "POLYMARKET_US_API_KEY_ID and/or POLYMARKET_US_API_SECRET_KEY "
                "not set. Worker will idle until keys are provided; discovery "
                "continues unaffected."
            )

        # Lazy client construction — avoid instantiating without creds.
        while True:
            await self._run_once()
            log.info("Reconnecting in %.1fs…", self._backoff)
            await asyncio.sleep(self._backoff)
            self._backoff = min(
                self._backoff * WS_RECONNECT_FACTOR,
                WS_RECONNECT_MAX_SECONDS,
            )

    async def _run_once(self) -> None:
        """One connect-subscribe-consume lifecycle across N batch connections."""
        if not POLYMARKET_US_API_KEY_ID or not POLYMARKET_US_API_SECRET_KEY:
            self._backoff = WS_RECONNECT_INITIAL_SECONDS
            await asyncio.sleep(60)
            return

        slugs = self._discovery.current_slugs()
        if not slugs:
            log.info("No active slugs to subscribe to; idle for 30s.")
            self._backoff = WS_RECONNECT_INITIAL_SECONDS
            await asyncio.sleep(30)
            return

        # Build client once per _run_once cycle; close at teardown. This keeps
        # a stale key_id from haunting reconnects if the operator rotated it.
        self._client = AsyncPolymarketUS(
            key_id=POLYMARKET_US_API_KEY_ID,
            secret_key=POLYMARKET_US_API_SECRET_KEY,
        )

        batches = batch_slugs(slugs, MARKETS_WS_SLUG_CAP)
        log.info(
            "Opening %d Markets WS connection(s) for %d slug(s).",
            len(batches),
            len(slugs),
        )

        # Open all WS connections and subscribe each.
        markets_ws_list: list[Any] = []
        closed_event = asyncio.Event()

        try:
            for batch_idx, batch in enumerate(batches):
                ws = self._client.ws.markets()
                self._register_handlers(ws, closed_event, batch_idx)
                await ws.connect()
                # Reset backoff the moment the first connection succeeds.
                self._backoff = WS_RECONNECT_INITIAL_SECONDS

                # Subscribe to full order book data (feeds Q3 reaction-time
                # analysis: quote-level signal for the CLOB).
                md_request_id = f"md-{uuid.uuid4().hex[:12]}"
                await ws.subscribe_market_data(md_request_id, batch)

                # Subscribe to trade notifications (feeds Q3/Q4: execution-level
                # signal distinguishes real market-moving events from noise
                # requotes, and trade-stream completeness is an independent
                # reliability channel). Session 2.2 addition honoring plan §4's
                # two-surface commitment; the SDK exposes both under one
                # MarketsWebSocket.
                tr_request_id = f"tr-{uuid.uuid4().hex[:12]}"
                await ws.subscribe_trades(tr_request_id, batch)

                log.info(
                    "Subscribed batch %d/%d with %d slugs "
                    "(market_data=%s, trades=%s).",
                    batch_idx + 1,
                    len(batches),
                    len(batch),
                    md_request_id,
                    tr_request_id,
                )
                markets_ws_list.append(ws)

            log.info("All batches subscribed; entering idle wait.")
            # Wait until any connection signals close. The SDK dispatches to
            # the `close` handler which sets closed_event.
            await closed_event.wait()
            log.info("Close signal received; tearing down connections.")

        except AuthenticationError as exc:
            log.error(
                "Markets WS authentication failed — check key_id/secret_key: %s",
                exc,
            )
            # Don't hammer the auth endpoint; longer sleep before retry.
            self._backoff = max(self._backoff, 30.0)
        except (
            APIConnectionError,
            APITimeoutError,
            WebSocketError,
            PolymarketUSError,
        ) as exc:
            log.warning("Markets WS connection issue: %s", exc)
        except Exception as exc:  # noqa: BLE001 — loop must survive
            log.exception("Markets WS unexpected error: %s", exc)
        finally:
            # Best-effort close of every connection we opened.
            for ws in markets_ws_list:
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001 — teardown is best-effort
                    pass
            if self._client is not None:
                try:
                    await self._client.close()
                except Exception:  # noqa: BLE001
                    pass
                self._client = None

    def _register_handlers(
        self,
        ws: Any,
        closed_event: asyncio.Event,
        batch_idx: int,
    ) -> None:
        """Wire all six SDK events to our handlers."""

        def _on_market_data(msg: dict[str, Any]) -> None:
            self._handle_payload("market_data", msg)

        def _on_market_data_lite(msg: dict[str, Any]) -> None:
            self._handle_payload("market_data_lite", msg)

        def _on_trade(msg: dict[str, Any]) -> None:
            self._handle_payload("trade", msg)

        def _on_heartbeat(*args: Any, **kwargs: Any) -> None:
            # Heartbeats are frequent; keep log volume down (debug only).
            log.debug("Markets WS heartbeat (batch %d)", batch_idx)

        def _on_error(err: Any) -> None:
            log.warning("Markets WS error event (batch %d): %s", batch_idx, err)
            self._handle_payload("error", {"error_repr": repr(err)})

        def _on_close(*args: Any, **kwargs: Any) -> None:
            log.info("Markets WS close event (batch %d)", batch_idx)
            closed_event.set()

        ws.on("market_data", _on_market_data)
        ws.on("market_data_lite", _on_market_data_lite)
        ws.on("trade", _on_trade)
        ws.on("heartbeat", _on_heartbeat)
        ws.on("error", _on_error)
        ws.on("close", _on_close)

    def _handle_payload(self, event_name: str, payload: dict[str, Any]) -> None:
        """Route one inbound SDK-parsed payload to the right match's JSONL.

        arrived_at_ms is captured at handler entry — as close to SDK-dispatch
        as we can get. This is what Q2 (lag) comparisons will use against
        API-Tennis's timestamps.
        """
        recv_ms = archive.arrived_at_ms()

        slug = extract_slug_from_event(payload) if isinstance(payload, dict) else None
        match_id = self._discovery.match_id_for_slug(slug) if slug else None

        record = {
            "arrived_at_ms": recv_ms,
            "source": "polymarket_sports",
            "event_name": event_name,
            "match_id": match_id,
            "match_id_resolved": bool(match_id),
            "slug": slug,
            "raw": payload,
        }

        date_str = archive.utc_date_str()
        if match_id:
            path = archive.polymarket_sports_path(match_id, date_str)
        else:
            path = archive.polymarket_sports_path("_unresolved", date_str)
        archive.append_jsonl(path, record)
