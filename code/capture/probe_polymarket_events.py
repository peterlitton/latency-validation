"""Probe 3: Polymarket Markets WebSocket event-type classifier.

Opens a MarketsWebSocket against a currently-live match's moneyline
slug (reads one from /data/archive/matches/*/meta.json where
live_at_discovery=True), subscribes to both market_data and trades,
and captures 60 seconds of events. Classifies every dispatched event
by event_name and dumps the first payload of each distinct type.

Used in session 3.1 to empirically answer whether the plan's "Sports
WS as a distinct game-state stream" corresponds to anything real in
this SDK, or whether game state must be inferred from market_data
deltas.

Run via:

    python -m code.capture.probe_polymarket_events

Writes to stdout only. Does NOT touch /data/archive.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import time
import uuid
from collections import Counter
from typing import Any

from polymarket_us import AsyncPolymarketUS


DURATION_SECONDS = 60
ARCHIVE_MATCHES = pathlib.Path("/data/archive/matches")


def pick_live_slug() -> tuple[str, str] | None:
    """Return (match_id, slug) for a currently-live match, or None."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    candidates: list[tuple[str, str]] = []
    for meta in ARCHIVE_MATCHES.glob(f"*_{today}/meta.json"):
        try:
            d = json.loads(meta.read_text())
        except Exception:
            continue
        if not d.get("live_at_discovery"):
            continue
        slugs = d.get("moneyline_market_slugs") or []
        for s in slugs:
            candidates.append((meta.parent.name, s))
    return candidates[0] if candidates else None


async def main() -> None:
    key_id = os.environ.get("POLYMARKET_US_API_KEY_ID", "")
    secret = os.environ.get("POLYMARKET_US_API_SECRET_KEY", "")
    if not (key_id and secret):
        print("ERROR: POLYMARKET_US_API_KEY_ID / _SECRET_KEY not set")
        return

    picked = pick_live_slug()
    if picked is None:
        print("No live-at-discovery matches found in archive for today.")
        print("Discovery may not have run yet, or no live matches right now.")
        return

    match_id, slug = picked
    print(f"Using match_id={match_id}")
    print(f"Slug:         {slug}")
    print()

    event_names: Counter = Counter()
    payload_keys: dict[str, list[str]] = {}
    first_of_each: dict[str, Any] = {}

    client = AsyncPolymarketUS(key_id=key_id, secret_key=secret)
    ws = client.ws.markets()

    def make_handler(name: str):
        def _h(msg: Any) -> None:
            event_names[name] += 1
            if name not in first_of_each:
                first_of_each[name] = msg
                if isinstance(msg, dict):
                    payload_keys[name] = sorted(msg.keys())
        return _h

    for ev in [
        "market_data",
        "market_data_lite",
        "trade",
        "heartbeat",
        "error",
        "close",
    ]:
        ws.on(ev, make_handler(ev))

    await ws.connect()
    md_id = f"md-probe-{uuid.uuid4().hex[:8]}"
    tr_id = f"tr-probe-{uuid.uuid4().hex[:8]}"
    await ws.subscribe_market_data(md_id, [slug])
    await ws.subscribe_trades(tr_id, [slug])

    print(f"Subscribed: md={md_id} tr={tr_id}")
    print(f"Capturing for {DURATION_SECONDS}s...")
    print()

    start = time.time()
    await asyncio.sleep(DURATION_SECONDS)
    elapsed = time.time() - start

    try:
        await ws.close()
    except Exception:
        pass

    print("=" * 60)
    print("EVENT-NAME CLASSIFICATION")
    print("=" * 60)
    print(f"Duration: {elapsed:.1f}s")
    for name, count in event_names.most_common():
        rate = count / elapsed if elapsed > 0 else 0.0
        print(f"  {name:22s} {count:6d}  ({rate:.2f}/s)")
    print()

    print("=" * 60)
    print("TOP-LEVEL KEYS PER EVENT TYPE")
    print("=" * 60)
    for name, keys in payload_keys.items():
        print(f"  {name}: {keys}")
    print()

    print("=" * 60)
    print("FIRST PAYLOAD OF EACH TYPE (truncated to 1500 chars)")
    print("=" * 60)
    for name, msg in first_of_each.items():
        print(f"\n-- {name} --")
        dump = json.dumps(msg, indent=2, default=str)
        print(dump[:1500])


if __name__ == "__main__":
    asyncio.run(main())
