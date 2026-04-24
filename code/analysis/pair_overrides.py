"""Operator utility: pair Polymarket match_ids with API-Tennis event_keys.

Helps the operator curate cross_feed_overrides.yaml as matches appear.
Takes a list of match-label + surname-tokens tuples (edit TARGETS below
or pass via CLI), queries the API-Tennis livescore endpoint, scans the
recent archive for active Polymarket matches, and prints proposed
`event_key: match_id` pairings ready to append.

Usage:
    python -m code.analysis.pair_overrides

Edit TARGETS below for the current batch. Run, read output, append any
unambiguous pairings to /data/archive/cross_feed_overrides.yaml.

Safe to run any time — read-only against both archive and API-Tennis.
"""

from __future__ import annotations

import httpx
import os
import pathlib
import time


# Edit for the current batch. Each entry is (label, [surname_tokens],
# first_names_only_flag). first_names_only=True means disambiguation
# is expected and the script prints all plausible candidates.
TARGETS: list[tuple[str, list[str], bool]] = [
    ("Simona vs Jelena", ["Simona", "Jelena"], True),
    ("Cirstea vs Grant", ["Cirstea", "Grant"], False),
    ("Jianu vs Guerrieri", ["Jianu", "Guerrieri"], False),
    ("Bronzetti vs Kudermetova", ["Bronzetti", "Kudermetova"], False),
    ("Ruse vs Rybakina", ["Ruse", "Rybakina"], False),
    ("Shelton vs Prizmic", ["Shelton", "Prizmic"], False),
]


ARCHIVE = pathlib.Path("/data/archive")
RECENT_WINDOW_SEC = 900  # 15 min — "active now" definition


def fetch_api_tennis_live() -> list[dict]:
    """Call API-Tennis get_livescore and return the result list."""
    key = os.environ.get("API_TENNIS_KEY", "")
    if not key:
        raise RuntimeError("API_TENNIS_KEY not set in environment")
    r = httpx.get(
        "https://api.api-tennis.com/tennis/",
        params={"method": "get_livescore", "APIkey": key},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("result", []) or []


def active_polymarket_matches(today: str) -> list[str]:
    """Return match_ids with JSONL writes in the last RECENT_WINDOW_SEC."""
    cutoff = time.time() - RECENT_WINDOW_SEC
    out: list[str] = []
    pm_root = ARCHIVE / "polymarket_sports"
    if not pm_root.exists():
        return out
    for d in pm_root.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if not d.name.endswith(today):
            continue
        jsonl = d / f"{today}.jsonl"
        if jsonl.exists() and jsonl.stat().st_mtime > cutoff:
            out.append(d.name)
    return sorted(out)


def match_api_tennis(
    live_events: list[dict],
    tokens: list[str],
) -> list[dict]:
    """Find live events where both tokens appear across the two players."""
    tokens_lower = [t.lower() for t in tokens]
    matches: list[dict] = []
    for e in live_events:
        p1 = (e.get("event_first_player") or "").lower()
        p2 = (e.get("event_second_player") or "").lower()
        p1_hit = any(t in p1 for t in tokens_lower)
        p2_hit = any(t in p2 for t in tokens_lower)
        if p1_hit and p2_hit:
            matches.append(e)
    return matches


def match_polymarket(
    pm_matches: list[str],
    tokens: list[str],
    permissive: bool,
) -> list[str]:
    """Find pm match_ids whose slug contains both tokens.

    permissive=True allows 1-of-2 token hits (for first-name-only cases
    where the operator will disambiguate).
    """
    tokens_lower = [t.lower() for t in tokens]
    out: list[str] = []
    for m in pm_matches:
        mid_lower = m.lower()
        hits = sum(1 for t in tokens_lower if t in mid_lower)
        if hits >= 2:
            out.append(m)
        elif permissive and hits >= 1:
            out.append(m)
    return out


def main() -> None:
    today = time.strftime("%Y-%m-%d", time.gmtime())

    print(f"Pair-overrides run: {today}")
    print()

    try:
        live_events = fetch_api_tennis_live()
    except Exception as exc:
        print(f"ERROR fetching API-Tennis: {exc}")
        return

    print(f"API-Tennis live now: {len(live_events)} events")

    pm_matches = active_polymarket_matches(today)
    print(
        f"Polymarket active matches (written in last "
        f"{RECENT_WINDOW_SEC // 60} min): {len(pm_matches)}"
    )
    for m in pm_matches:
        print(f"  {m}")
    print()

    unambiguous: list[tuple[int, str]] = []

    for label, tokens, first_names_only in TARGETS:
        print(f"=== {label} ===")

        ap_candidates = match_api_tennis(live_events, tokens)
        if not ap_candidates:
            print(f"  API-Tennis: NO MATCH for tokens {tokens}")
        elif len(ap_candidates) == 1:
            print(f"  API-Tennis: 1 candidate")
        else:
            print(
                f"  API-Tennis: {len(ap_candidates)} candidates "
                f"{'(first-name search; expected)' if first_names_only else '(ambiguous)'}"
            )
        for e in ap_candidates:
            print(
                f"    event_key={e.get('event_key')} "
                f"tournament={e.get('tournament_name')!r} "
                f"p1={e.get('event_first_player')!r} "
                f"p2={e.get('event_second_player')!r} "
                f"status={e.get('event_status')!r}"
            )

        pm_candidates = match_polymarket(
            pm_matches, tokens, permissive=first_names_only
        )
        if not pm_candidates:
            print(f"  Polymarket: NO MATCH for tokens {tokens}")
        elif len(pm_candidates) == 1:
            print(f"  Polymarket: 1 candidate")
        else:
            print(f"  Polymarket: {len(pm_candidates)} candidates")
        for m in pm_candidates:
            print(f"    {m}")

        if len(ap_candidates) == 1 and len(pm_candidates) == 1:
            ek = ap_candidates[0].get("event_key")
            if isinstance(ek, int):
                line = f"{ek}: {pm_candidates[0]}"
                unambiguous.append((ek, pm_candidates[0]))
                print(f"  PROPOSED: {line}")
            else:
                print(f"  PROPOSED: (event_key not an int: {ek!r})")
        else:
            print(f"  PROPOSED: (needs operator disambiguation)")
        print()

    print("=" * 60)
    print("UNAMBIGUOUS PAIRINGS — APPEND BLOCK")
    print("=" * 60)
    if not unambiguous:
        print("(none — all require operator disambiguation)")
    else:
        for ek, mid in unambiguous:
            print(f"{ek}: {mid}")
    print()
    print("To apply, append block to /data/archive/cross_feed_overrides.yaml")
    print("then Restart Service on Render.")


if __name__ == "__main__":
    main()
