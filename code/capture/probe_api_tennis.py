"""Probe 2: API-Tennis WebSocket shape classifier.

Runs a 60-second capture against wss://wss.api-tennis.com/live and
classifies message shapes, counts events, and samples the first 20
raw payloads to /tmp/api_tennis_ws_capture.jsonl for post-hoc review.

Not part of the capture pipeline; one-off empirical schema probe for
session 3.1. Run via:

    python -m code.capture.probe_api_tennis

Writes summary to stdout and raw samples to /tmp/api_tennis_ws_capture.jsonl.
Does NOT touch /data/archive.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import Counter

try:
    from websockets.asyncio.client import connect
except ImportError:
    try:
        from websockets.client import connect  # type: ignore[no-redef]
    except ImportError:
        import websockets
        connect = websockets.connect  # type: ignore[assignment]


DURATION_SECONDS = 60
OUT_PATH = "/tmp/api_tennis_ws_capture.jsonl"
RAW_SAMPLE_LIMIT = 20


async def main() -> None:
    key = os.environ.get("API_TENNIS_KEY", "")
    if not key:
        print("ERROR: API_TENNIS_KEY not set in environment")
        return

    url = f"wss://wss.api-tennis.com/live?APIkey={key}&timezone=UTC"

    msg_count = 0
    shape_types: Counter = Counter()
    event_keys_seen: set = set()
    tournaments: Counter = Counter()
    first_msg = None
    raw_samples_written = 0

    print(f"Connecting to wss.api-tennis.com...")
    async with connect(url, open_timeout=10, ping_interval=20) as ws:
        print(f"Connected. Capturing for {DURATION_SECONDS}s...")
        start = time.time()
        deadline = start + DURATION_SECONDS

        with open(OUT_PATH, "w") as fh:
            while time.time() < deadline:
                remaining = deadline - time.time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break

                recv_ms = int(time.time() * 1000)
                msg_count += 1

                if raw_samples_written < RAW_SAMPLE_LIMIT:
                    fh.write(
                        json.dumps({"arrived_at_ms": recv_ms, "raw_text": raw})
                        + "\n"
                    )
                    fh.flush()
                    raw_samples_written += 1

                try:
                    parsed = json.loads(raw)
                except Exception:
                    shape_types["non-json"] += 1
                    continue

                if first_msg is None:
                    first_msg = parsed

                if isinstance(parsed, list):
                    shape_types["list"] += 1
                    for item in parsed:
                        if isinstance(item, dict):
                            ek = item.get("event_key")
                            if ek is not None:
                                event_keys_seen.add(ek)
                            tn = item.get("tournament_name")
                            if tn:
                                tournaments[tn] += 1
                elif isinstance(parsed, dict):
                    shape_types["dict"] += 1
                    if "event_key" in parsed:
                        shape_types["dict-single-event"] += 1
                        event_keys_seen.add(parsed.get("event_key"))
                        tn = parsed.get("tournament_name")
                        if tn:
                            tournaments[tn] += 1
                    else:
                        for k, v in parsed.items():
                            if isinstance(v, dict) and "event_key" in v:
                                shape_types["dict-keyed-by-event-key"] += 1
                                event_keys_seen.add(v.get("event_key"))
                                tn = v.get("tournament_name")
                                if tn:
                                    tournaments[tn] += 1
                                break

    elapsed = time.time() - start
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Duration: {elapsed:.1f}s")
    print(f"Messages received: {msg_count}")
    if elapsed > 0:
        print(f"Rate: {msg_count/elapsed:.2f} msg/s")
    print()
    print("Shape types:")
    for s, c in shape_types.most_common():
        print(f"  {s}: {c}")
    print()
    print(f"Unique event_keys seen: {len(event_keys_seen)}")
    print()
    print("Tournaments seen (message counts):")
    for t, c in tournaments.most_common(10):
        print(f"  {c:5d}  {t}")
    print()
    print(f"Raw samples ({raw_samples_written}) written to {OUT_PATH}")
    if first_msg is not None:
        print()
        print("FIRST MESSAGE SHAPE:")
        if isinstance(first_msg, list):
            print(f"  list with {len(first_msg)} items")
            if first_msg and isinstance(first_msg[0], dict):
                print(f"  first item keys: {sorted(first_msg[0].keys())}")
        elif isinstance(first_msg, dict):
            print(f"  dict with {len(first_msg)} keys")
            keys = sorted(first_msg.keys())[:20]
            print(f"  keys: {keys}")


if __name__ == "__main__":
    asyncio.run(main())
