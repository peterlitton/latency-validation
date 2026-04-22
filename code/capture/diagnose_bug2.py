"""Bug #2 diagnostic — slug-routing stability.

Session 2.1 symptom (verbatim from log):

    "8 matches subscribed on Sports WS; 7 of 8 had exactly 1 event routed
    to their match directory, with subsequent events going to _unresolved/
    despite the slug being correctly extracted from the payload. Abidjan
    (the one heavily-trading match) routed all 10 events correctly."

This script analyzes the overnight archive to surface the empirical shape
of the failure. It does NOT test any hypothesis from session 2.1; it maps
the evidence fresh so the next commit can target the real cause.

Archive layout assumed:

    {archive_root}/matches/{match_id}/meta.json           (metadata + slug list)
    {archive_root}/polymarket_sports/{match_id}/events-*.jsonl  (routed events)
    {archive_root}/polymarket_sports/_unresolved/events-*.jsonl (orphan events)

What it reports, per-match:

  1. Event counts: how many events landed in match's dir in polymarket_sports/
     vs in _unresolved/ but bearing a slug this match claims.
  2. Timestamps: arrival time of the first routed event vs the first
     unresolved event for the same slug.
  3. Slug consistency: is the slug on the first match_dir event exactly
     the same string as the slug on its subsequent _unresolved events?

What it reports, globally:

  4. Orphan slugs: slugs that appear in _unresolved but correspond to
     no known match_id in any meta.json.
  5. Cross-slug contamination: cases where a single match's dir got an
     event whose slug belongs to a different match.

Usage:
    python -m code.capture.diagnose_bug2 --archive-root /data/archive

Output is plain text to stdout. Paste back to Claude for analysis.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

log = logging.getLogger("diagnose_bug2")


def find_all_match_dirs(sports_root: Path) -> list[Path]:
    """Return every per-match directory under polymarket_sports/, excluding
    _unresolved itself. Works whether match_ids have the old _unknown-date
    suffix or the new _YYYY-MM-DD one."""
    if not sports_root.exists():
        return []
    results = []
    for p in sorted(sports_root.iterdir()):
        if not p.is_dir():
            continue
        if p.name == "_unresolved":
            continue
        results.append(p)
    return results


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file; return list of parsed dicts. Skip bad lines."""
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning("  [%s:%d] bad JSON, skipping: %s", path.name, i, e)
    return out


def collect_match_events(match_dir: Path) -> list[dict]:
    """Read all events-*.jsonl in a match dir, flattened."""
    all_events = []
    for jsonl in sorted(match_dir.glob("events-*.jsonl")):
        all_events.extend(read_jsonl(jsonl))
    return all_events


def collect_unresolved_events(sports_root: Path) -> list[dict]:
    """Read everything under _unresolved/. Structure mirrors per-match dirs."""
    unresolved_dir = sports_root / "_unresolved"
    if not unresolved_dir.exists():
        return []
    all_events = []
    for jsonl in sorted(unresolved_dir.glob("events-*.jsonl")):
        all_events.extend(read_jsonl(jsonl))
    return all_events


def read_meta(match_dir: Path) -> dict | None:
    meta_path = match_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def summarize_event(ev: dict) -> tuple[str | None, str | None, str | None]:
    """Pull (arrived_at_ms, slug, event_name) from a captured JSONL record,
    handling both our wrapper and raw fallbacks."""
    ts = ev.get("arrived_at_ms")
    slug = ev.get("slug")
    name = ev.get("event_name")
    return ts, slug, name


def format_ts(ms: Any) -> str:
    """Format arrived_at_ms as human-readable UTC, or 'n/a'."""
    if not isinstance(ms, (int, float)):
        return "n/a"
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(ms / 1000.0, tz=_dt.timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return f"ms={ms}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bug #2 slug-routing diagnostic.")
    parser.add_argument(
        "--archive-root",
        required=True,
        type=Path,
        help="Archive root (e.g. /data/archive).",
    )
    parser.add_argument(
        "--matches-subdir",
        default="matches",
        help="Subdirectory holding per-match meta.json (default: matches).",
    )
    parser.add_argument(
        "--sports-subdir",
        default="polymarket_sports",
        help="Subdirectory for Sports WS event archive (default: polymarket_sports).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    archive_root = args.archive_root.resolve()
    matches_root = (archive_root / args.matches_subdir).resolve()
    sports_root = (archive_root / args.sports_subdir).resolve()
    print(f"Archive root:        {archive_root}")
    print(f"matches/ subdir:     {matches_root}")
    print(f"polymarket_sports/:  {sports_root}")
    print()

    if not sports_root.exists():
        print(f"ERROR: {sports_root} does not exist.")
        return 1
    if not matches_root.exists():
        print(f"WARNING: {matches_root} does not exist — slug ownership will be empty.")

    # Per-match event dirs live in polymarket_sports/.
    match_event_dirs = find_all_match_dirs(sports_root)
    print(f"Match event dirs (polymarket_sports/): {len(match_event_dirs)}")
    unresolved_events = collect_unresolved_events(sports_root)
    print(f"_unresolved events:                    {len(unresolved_events)}")
    print()

    # Collect routed events keyed by dir name.
    per_match_events: dict[str, list[dict]] = {}
    for md in match_event_dirs:
        per_match_events[md.name] = collect_match_events(md)

    # Collect slug ownership from matches/{*}/meta.json. Key by match_id
    # (which equals the directory name in matches/). Skip _unknown-date dirs:
    # post-migration they are superseded provenance-only, and including them
    # confuses ownership attribution for slugs that were re-registered under
    # the correctly-named sibling.
    per_match_slugs: dict[str, set[str]] = {}
    all_known_match_ids: set[str] = set()
    if matches_root.exists():
        for md in sorted(matches_root.iterdir()):
            if not md.is_dir():
                continue
            if md.name.endswith("_unknown-date"):
                # Superseded or awaiting migration; skip for ownership.
                continue
            all_known_match_ids.add(md.name)
            meta = read_meta(md)
            known_slugs: set[str] = set()
            if meta:
                for s in meta.get("moneyline_market_slugs") or []:
                    if isinstance(s, str):
                        known_slugs.add(s)
            per_match_slugs[md.name] = known_slugs

    # --- Per-match event breakdown ---
    print("=" * 80)
    print("ROUTED EVENTS PER polymarket_sports/ DIR")
    print("=" * 80)
    print(f"{'dir name':<60} {'routed':>8} {'meta?':>6}")
    print("-" * 80)
    for md in match_event_dirs:
        events = per_match_events[md.name]
        has_meta = "yes" if md.name in per_match_slugs else "NO"
        print(f"{md.name[:60]:<60} {len(events):>8} {has_meta:>6}")

    print()
    print("=" * 80)
    print("UNRESOLVED EVENTS BY SLUG")
    print("=" * 80)

    # Tally unresolved events by slug.
    unresolved_by_slug: dict[str | None, list[dict]] = defaultdict(list)
    for ev in unresolved_events:
        _ts, slug, _name = summarize_event(ev)
        unresolved_by_slug[slug].append(ev)

    # Build reverse map: slug -> match_id.
    slug_to_match: dict[str, str] = {}
    for mid, slugs in per_match_slugs.items():
        for s in slugs:
            if s in slug_to_match:
                print(f"  ! slug {s!r} claimed by both {slug_to_match[s]} and {mid}")
            slug_to_match[s] = mid

    print(f"{'slug':<56} {'count':>6} {'owner match_id':<56}")
    print("-" * 80)

    orphan_slugs: list[str] = []
    for slug, evs in sorted(
        unresolved_by_slug.items(),
        key=lambda kv: -len(kv[1]),
    ):
        slug_repr = str(slug) if slug is not None else "<None>"
        owner = slug_to_match.get(slug or "", "— not in any meta.json")
        if owner == "— not in any meta.json" and slug:
            orphan_slugs.append(slug)
        print(f"{slug_repr[:56]:<56} {len(evs):>6} {owner[:56]:<56}")

    print()
    print(f"Orphan slugs (in _unresolved, no matching meta.json): {len(orphan_slugs)}")
    for s in orphan_slugs[:20]:
        print(f"  {s}")
    if len(orphan_slugs) > 20:
        print(f"  ... and {len(orphan_slugs) - 20} more")

    # --- First-event timing ---
    print()
    print("=" * 80)
    print("TIMING: FIRST ROUTED vs FIRST UNRESOLVED (BY OWNER MATCH)")
    print("=" * 80)
    print(f"{'match_id':<42} {'first routed':<28} {'first unresolved':<28}")
    print("-" * 80)

    for mid in sorted(per_match_slugs.keys()):
        # Routed events for this match are in polymarket_sports/{mid}/.
        routed = per_match_events.get(mid, [])
        # Unresolved events owned by this match's slugs.
        match_slugs = per_match_slugs[mid]
        mid_unresolved = [
            ev for ev in unresolved_events
            if (summarize_event(ev)[1] in match_slugs)
        ]
        first_routed_ms = min(
            (summarize_event(ev)[0] for ev in routed
             if isinstance(summarize_event(ev)[0], (int, float))),
            default=None,
        )
        first_unres_ms = min(
            (summarize_event(ev)[0] for ev in mid_unresolved
             if isinstance(summarize_event(ev)[0], (int, float))),
            default=None,
        )
        print(
            f"{mid[:42]:<42} "
            f"{format_ts(first_routed_ms)[:28]:<28} "
            f"{format_ts(first_unres_ms)[:28]:<28} "
            f"(routed={len(routed)}, unresolved={len(mid_unresolved)})"
        )

    # --- Dirname mismatch check ---
    # polymarket_sports/ has a dir but matches/ doesn't know this match_id,
    # or vice versa. Symptom of bug #1's _unknown-date vs clean-date divergence.
    print()
    print("=" * 80)
    print("TREE CONSISTENCY CHECK")
    print("=" * 80)
    sports_names = {md.name for md in match_event_dirs}
    missing_in_matches = sorted(sports_names - all_known_match_ids)
    missing_in_sports = sorted(all_known_match_ids - sports_names)
    print(f"In polymarket_sports/ but NOT in matches/:  {len(missing_in_matches)}")
    for n in missing_in_matches[:20]:
        print(f"  {n}")
    if len(missing_in_matches) > 20:
        print(f"  ... and {len(missing_in_matches) - 20} more")
    print(f"In matches/ but NOT in polymarket_sports/:  {len(missing_in_sports)}")
    for n in missing_in_sports[:20]:
        print(f"  {n}")
    if len(missing_in_sports) > 20:
        print(f"  ... and {len(missing_in_sports) - 20} more")

    # --- Cross-match contamination ---
    print()
    print("=" * 80)
    print("CROSS-MATCH CONTAMINATION CHECK")
    print("=" * 80)
    print("(events in dir X whose slug belongs to a different match's meta.json)")
    print()
    contamination_found = False
    for mid, events in per_match_events.items():
        own_slugs = per_match_slugs.get(mid, set())
        for ev in events:
            _ts, slug, _name = summarize_event(ev)
            if slug and slug not in own_slugs and slug in slug_to_match:
                contamination_found = True
                owner = slug_to_match[slug]
                print(f"  in-dir={mid}  slug={slug}  true-owner={owner}")
    if not contamination_found:
        print("  None found.")

    # --- Summary ---
    print()
    print("=" * 80)
    print("SUMMARY FOR OPERATOR")
    print("=" * 80)
    print(f"  polymarket_sports/ match dirs:    {len(match_event_dirs)}")
    print(f"  matches/ meta.json files:         {len(per_match_slugs)}")
    print(f"  Total routed events:              "
          f"{sum(len(v) for v in per_match_events.values())}")
    print(f"  Total unresolved events:          {len(unresolved_events)}")
    print(f"  Unique slugs in _unresolved:      {len(unresolved_by_slug)}")
    print(f"  Orphan slugs (unknown owner):     {len(orphan_slugs)}")
    print(f"  Dirname mismatch (sports only):   {len(missing_in_matches)}")
    print(f"  Dirname mismatch (matches only):  {len(missing_in_sports)}")
    print()
    print("Paste this output back to Claude for analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
