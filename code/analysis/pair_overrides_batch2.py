"""Ad-hoc pairing script for 4 new matches — session 4.1 continuation.

Same logic as pair_overrides.py but with the current batch hardcoded.
Safe to run any time; read-only against both archive and API-Tennis.

Usage:
    python -m code.analysis.pair_overrides_batch2
"""

from __future__ import annotations

import httpx
import os
import pathlib
import time


TARGETS: list[tuple[str, list[str]]] = [
    ("Fils vs Buse", ["Fils", "Buse"]),
    ("Noskova vs Arango", ["Noskova", "Arango"]),
    ("Putintseva vs Kostyuk", ["Putintseva", "Kostyuk"]),
    ("Yuan vs Klimovicova", ["Yuan", "Klimovicova"]),
]


ARCHIVE = pathlib.Path("/data/archive")
RECENT_WINDOW_SEC = 900


def main() -> None:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    cutoff = time.time() - RECENT_WINDOW_SEC

    key = os.environ.get("API_TENNIS_KEY", "")
    if not key:
        print("ERROR: API_TENNIS_KEY not set")
        return

    r = httpx.get(
        "https://api.api-tennis.com/tennis/",
        params={"method": "get_livescore", "APIkey": key},
        timeout=15,
    )
    r.raise_for_status()
    live = r.json().get("result", []) or []
    print(f"API-Tennis live: {len(live)} events")
    print()

    pm_matches: list[str] = []
    pm_root = ARCHIVE / "polymarket_sports"
    if pm_root.exists():
        for d in pm_root.iterdir():
            if not d.is_dir() or d.name.startswith("_"):
                continue
            if not d.name.endswith(today):
                continue
            jsonl = d / f"{today}.jsonl"
            if jsonl.exists() and jsonl.stat().st_mtime > cutoff:
                pm_matches.append(d.name)

    print(
        f"Polymarket active (written in last "
        f"{RECENT_WINDOW_SEC // 60} min): {len(pm_matches)}"
    )
    for m in sorted(pm_matches):
        print(f"  {m}")
    print()

    unambiguous: list[str] = []

    for label, tokens in TARGETS:
        print(f"=== {label} ===")
        tl = [t.lower() for t in tokens]

        ap_candidates = []
        for e in live:
            p1 = (e.get("event_first_player") or "").lower()
            p2 = (e.get("event_second_player") or "").lower()
            if any(t in p1 for t in tl) and any(t in p2 for t in tl):
                ap_candidates.append(e)

        pm_candidates = [
            m for m in pm_matches
            if sum(1 for t in tl if t in m.lower()) >= 2
        ]

        for e in ap_candidates:
            print(
                f"  AP: event_key={e.get('event_key')} "
                f"tour={e.get('tournament_name')!r} "
                f"p1={e.get('event_first_player')!r} "
                f"p2={e.get('event_second_player')!r} "
                f"status={e.get('event_status')!r}"
            )
        for m in pm_candidates:
            print(f"  PM: {m}")

        if len(ap_candidates) == 1 and len(pm_candidates) == 1:
            ek = ap_candidates[0].get("event_key")
            if isinstance(ek, int):
                line = f"{ek}: {pm_candidates[0]}"
                unambiguous.append(line)
                print(f"  PROPOSED: {line}")
        elif not ap_candidates:
            print(f"  AP: not live (or tokens don't match)")
        elif not pm_candidates:
            print(f"  PM: not in archive (match not started yet?)")
        else:
            print(f"  ambiguous — needs manual disambiguation")
        print()

    print("=" * 60)
    print("APPEND BLOCK")
    print("=" * 60)
    if not unambiguous:
        print("(none)")
    else:
        for line in unambiguous:
            print(line)


if __name__ == "__main__":
    main()
