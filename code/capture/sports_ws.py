"""Polymarket Sports (Markets) WebSocket worker.

Subscribes to moneyline `market_slug` values supplied by the discovery loop
and appends raw payloads to per-match JSONL archives.

Subscription model:
  - Documented cap: 100 slugs per subscription.
  - We batch the active slug set into sub-100 groups and send multiple
    subscribe messages over the same connection.
  - When discovery's active set changes, we reconcile by closing the
    connection and reconnecting; the reconnect loop picks up the new set.
    This is simpler than diffing subscriptions mid-stream and correct because
    meta.json is already written for every known match — no event is lost.

Reconnect model:
  - On any disconnect or exception, sleep with exponential backoff (capped).
  - On successful connect, backoff resets.
  - Disconnect-window data loss is accepted if the WS doesn't support replay;
    the Phase 2 working log documents whichever behavior we observe.

Subscription message shape is based on Polymarket US documentation
(docs.polymarket.us). The actual protocol is verified empirically during
session 2.1 — if this message format doesn't work, we tune the SUBSCRIBE_
constants and note the correction in the working log.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from . import archive
from .config import (
    MARKETS_WS_SLUG_CAP,
    MARKETS_WS_URL,
    USER_AGENT,
    WS_RECONNECT_FACTOR,
    WS_RECONNECT_INITIAL_SECONDS,
    WS_RECONNECT_MAX_SECONDS,
)
from .discovery import DiscoveryLoop

log = logging.getLogger("capture.sports_ws")


# Subscription payload shape. Polymarket US WebSocket protocol documents
# market_slug as the subscription unit. If the real protocol disagrees, fix
# these two constants and the build_subscribe_message function.
SUBSCRIBE_TYPE = "subscribe"
SUBSCRIBE_CHANNEL = "markets"


def build_subscribe_message(slugs: list[str]) -> str:
    """Build a subscribe frame for up to MARKETS_WS_SLUG_CAP slugs."""
    payload = {
        "type": SUBSCRIBE_TYPE,
        "channel": SUBSCRIBE_CHANNEL,
        "markets": slugs,
    }
    return json.dumps(payload)


def batch_slugs(slugs: list[str], cap: int) -> list[list[str]]:
    """Partition slugs into sub-cap chunks."""
    return [slugs[i : i + cap] for i in range(0, len(slugs), cap)]


def extract_slug_from_event(payload: dict[str, Any]) -> str | None:
    """Pull the market_slug out of an incoming event.

    Tries a few plausible field names because we haven't pinned the exact
    payload shape yet. Session 2.1 live-run narrows this down and we
    simplify afterwards.
    """
    for field in ("market_slug", "marketSlug", "slug"):
        val = payload.get(field)
        if isinstance(val, str) and val:
            return val
    # Some WS protocols nest the identity.
    for container in ("market", "data", "event"):
        nested = payload.get(container)
        if isinstance(nested, dict):
            found = extract_slug_from_event(nested)
            if found:
                return found
    return None


class SportsWorker:
    """Long-running Sports WS capture worker.

    Reads current slugs from the DiscoveryLoop on each (re)connect, opens
    the WS, fans out subscribe messages, and appends every inbound payload
    to the match's JSONL file.
    """

    def __init__(self, discovery: DiscoveryLoop) -> None:
        self._discovery = discovery
        self._backoff = WS_RECONNECT_INITIAL_SECONDS

    async def run_forever(self) -> None:
        log.info("Sports WS worker starting; url=%s", MARKETS_WS_URL)
        while True:
            await self._run_once()
            # Sleep before retry; backoff grows on repeat failures.
            log.info("Reconnecting in %.1fs…", self._backoff)
            await asyncio.sleep(self._backoff)
            self._backoff = min(
                self._backoff * WS_RECONNECT_FACTOR,
                WS_RECONNECT_MAX_SECONDS,
            )

    async def _run_once(self) -> None:
        """One connect-subscribe-consume lifecycle. Returns when the
        connection closes or errors."""
        slugs = self._discovery.current_slugs()
        if not slugs:
            # No active matches; wait and try again. Don't escalate backoff.
            log.info("No active slugs to subscribe to; idle for 30s.")
            self._backoff = WS_RECONNECT_INITIAL_SECONDS
            await asyncio.sleep(30)
            return

        batches = batch_slugs(slugs, MARKETS_WS_SLUG_CAP)
        log.info(
            "Connecting to Markets WS with %d slugs across %d batch(es).",
            len(slugs),
            len(batches),
        )

        try:
            async with websockets.connect(
                MARKETS_WS_URL,
                user_agent_header=USER_AGENT,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as ws:
                # Reset backoff on successful connect.
                self._backoff = WS_RECONNECT_INITIAL_SECONDS

                # Fan out subscribe frames.
                for batch in batches:
                    await ws.send(build_subscribe_message(batch))

                log.info("Subscribed; entering receive loop.")
                async for raw_msg in ws:
                    self._handle_message(raw_msg)

        except (ConnectionClosed, WebSocketException) as exc:
            log.warning("Markets WS connection ended: %s", exc)
        except Exception as exc:  # noqa: BLE001 — loop must survive
            log.exception("Markets WS unexpected error: %s", exc)

    def _handle_message(self, raw_msg: str | bytes) -> None:
        """Route one incoming payload to the right match's JSONL file.

        Raw preservation rule: store the payload as-received under `raw`,
        plus minimal routing fields and arrived_at_ms.
        """
        recv_ms = archive.arrived_at_ms()

        # Decode once; store the parsed dict under `raw` so analysis
        # doesn't need to re-parse. If it's not JSON, store the string.
        payload: Any
        if isinstance(raw_msg, bytes):
            try:
                raw_msg = raw_msg.decode("utf-8")
            except UnicodeDecodeError:
                log.warning("Non-UTF-8 Markets WS frame; skipping.")
                return
        try:
            payload = json.loads(raw_msg)
        except json.JSONDecodeError:
            log.warning("Non-JSON Markets WS frame; storing as string.")
            payload = raw_msg

        # Resolve to a match_id via the slug reverse lookup.
        slug = None
        if isinstance(payload, dict):
            slug = extract_slug_from_event(payload)

        match_id = self._discovery.match_id_for_slug(slug) if slug else None

        record = {
            "arrived_at_ms": recv_ms,
            "source": "polymarket_sports",
            "match_id": match_id,
            "match_id_resolved": bool(match_id),
            "slug": slug,
            "raw": payload,
        }

        # Route: resolved events go to their match's file;
        # unresolved events go to an _unresolved bucket for operator review.
        date_str = archive.utc_date_str()
        if match_id:
            path = archive.polymarket_sports_path(match_id, date_str)
        else:
            path = archive.polymarket_sports_path("_unresolved", date_str)
        archive.append_jsonl(path, record)
