"""One-shot migration: rename `*_unknown-date` match directories (v2).

Context
-------
Session 2.1's resolver wrote `_unknown-date` as the date suffix on every
match_id because `event.get("eventDate")` returns empty on the Polymarket
US gateway. Directories on disk carry that suffix. Commit 1 (session 2.2)
fixed the resolver to read `startDate`. This script repairs the already-
written directories.

v2 rewrite: v1 assumed meta.json sat alongside events. The actual archive
layout has two parallel trees:

    /data/archive/matches/{match_id}/meta.json                (metadata)
    /data/archive/polymarket_sports/{match_id}/events-*.jsonl (WS events)
    /data/archive/polymarket_sports/_unresolved/...           (bug #2 orphans)

Both trees hold match_id-named directories and both were polluted by the
session 2.1 bug. v2 migrates both, using `matches/{name}/meta.json` as the
single source of truth for the correct date. The companion
`polymarket_sports/{name}/` dir (which has no meta.json of its own) is
renamed by reference to its sibling in `matches/`.

What it does
------------
Phase 1 — matches/ tree:
  For every `matches/*_unknown-date/` with a readable meta.json and a
  parseable `start_date_iso`, build the corrected match_id and rename the
  directory. Rewrite meta.json's `match_id` and `event_date` fields and
  append a migration provenance entry.

Phase 2 — polymarket_sports/ tree:
  For every `polymarket_sports/*_unknown-date/`, look up the correct name
  either in this run's phase-1 rename map, or by scanning matches/ for a
  sibling whose prefix matches and whose suffix is a valid date (supports
  re-runs where phase 1 already renamed in a prior invocation). Rename the
  events directory to match. No metadata to rewrite.

Idempotency
-----------
Safe to re-run. Skips (cleanly, no errors):
  - Target dir already exists (e.g., commit 2 wrote a fresh correctly-named
    dir after a match went live; or prior run already renamed).
  - Phase 1: source has no meta.json, or start_date_iso missing/invalid.
  - Phase 2: no renamed sibling in matches/, or multiple ambiguous siblings.

Out of scope
------------
Does not touch `polymarket_sports/_unresolved/` — bug #2 territory.
Does not touch `gamma/` snapshots — those are per-date, not per-match.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("migrate_unknown_dates")

UNKNOWN_DATE_SUFFIX = "_unknown-date"
MATCHES_SUBDIR = "matches"
SPORTS_SUBDIR = "polymarket_sports"


def find_unknown_date_dirs(root: Path) -> list[Path]:
    """Shallow scan: direct children of `root` ending in the suffix."""
    if not root.exists():
        return []
    results: list[Path] = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and p.name.endswith(UNKNOWN_DATE_SUFFIX):
            results.append(p)
    return results


def parse_event_date(start_date_iso: str) -> str | None:
    """Return YYYY-MM-DD slice if start_date_iso looks valid, else None."""
    if not isinstance(start_date_iso, str) or len(start_date_iso) < 10:
        return None
    candidate = start_date_iso[:10]
    if (
        len(candidate) == 10
        and candidate[4] == "-"
        and candidate[7] == "-"
        and candidate[0:4].isdigit()
        and candidate[5:7].isdigit()
        and candidate[8:10].isdigit()
    ):
        return candidate
    return None


def rebuild_match_id(old_match_id: str, new_date: str) -> str:
    if not old_match_id.endswith(UNKNOWN_DATE_SUFFIX):
        raise ValueError(
            f"match_id does not end in {UNKNOWN_DATE_SUFFIX!r}: {old_match_id!r}"
        )
    prefix = old_match_id[: -len(UNKNOWN_DATE_SUFFIX)]
    return f"{prefix}_{new_date}"


# --- Phase 1: matches/ tree -------------------------------------------------


def migrate_matches_dir(dir_path: Path, dry_run: bool) -> tuple[str, str | None]:
    """Migrate one matches/*_unknown-date/ dir.

    Returns (status_token, new_name_or_None).
    """
    meta_path = dir_path / "meta.json"
    if not meta_path.exists():
        log.warning("  [skip] no meta.json in %s", dir_path)
        return "skipped_no_meta", None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("  [skip] meta.json not parseable in %s: %s", dir_path, exc)
        return "skipped_bad_meta", None

    start_date_iso = meta.get("start_date_iso") or ""
    new_date = parse_event_date(start_date_iso)
    if new_date is None:
        log.warning(
            "  [skip] start_date_iso missing/invalid in %s (value=%r)",
            dir_path,
            start_date_iso,
        )
        return "skipped_no_date", None

    old_name = dir_path.name
    try:
        new_name = rebuild_match_id(old_name, new_date)
    except ValueError:
        log.error("  [skip] unexpected match_id shape: %r", old_name)
        return "skipped_bad_meta", None

    target = dir_path.with_name(new_name)
    if target.exists():
        log.info("  [skip] target exists: %s", target)
        return "skipped_target_exists", None

    log.info("  %s", old_name)
    log.info("    -> %s", new_name)

    if dry_run:
        return "renamed", new_name

    meta["match_id"] = new_name
    meta["event_date"] = new_date
    migrations = meta.get("migrations") or []
    migrations.append(
        {
            "kind": "unknown_date_rename",
            "phase": "matches",
            "from_match_id": old_name,
            "to_match_id": new_name,
            "source_field": "start_date_iso",
        }
    )
    meta["migrations"] = migrations
    meta_path.write_text(
        json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8"
    )
    dir_path.rename(target)
    return "renamed", new_name


# --- Phase 2: polymarket_sports/ tree ---------------------------------------


def _date_suffix_is_valid(name: str, prefix: str) -> bool:
    """True if name == prefix + "_" + YYYY-MM-DD."""
    expected_prefix = f"{prefix}_"
    if not name.startswith(expected_prefix):
        return False
    if name.endswith(UNKNOWN_DATE_SUFFIX):
        return False
    suffix = name[len(expected_prefix):]
    return parse_event_date(suffix) is not None


def migrate_sports_dir(
    dir_path: Path,
    matches_root: Path,
    rename_map: dict[str, str],
    dry_run: bool,
) -> str:
    """Migrate one polymarket_sports/*_unknown-date/ dir."""
    old_name = dir_path.name

    # Source of truth 1: phase 1 renamed the sibling in this run.
    new_name = rename_map.get(old_name)

    # Source of truth 2: phase 1 in a prior run already renamed the
    # matches/ sibling; find it by prefix scan.
    if new_name is None and matches_root.exists():
        prefix = old_name[: -len(UNKNOWN_DATE_SUFFIX)]
        candidates = [
            p for p in matches_root.iterdir()
            if p.is_dir() and _date_suffix_is_valid(p.name, prefix)
        ]
        if len(candidates) == 1:
            new_name = candidates[0].name
            log.info(
                "  [phase2] resolved %s via existing sibling %s",
                old_name,
                candidates[0].name,
            )
        elif len(candidates) > 1:
            log.warning(
                "  [skip] %s has multiple matches/ siblings: %s — "
                "can't disambiguate",
                old_name,
                sorted(c.name for c in candidates),
            )
            return "skipped_ambiguous"

    if new_name is None:
        log.warning(
            "  [skip] %s has no meta.json sibling in matches/ — "
            "cannot determine date",
            dir_path,
        )
        return "skipped_no_sibling"

    target = dir_path.with_name(new_name)
    if target.exists():
        log.info("  [skip] target exists: %s", target)
        return "skipped_target_exists"

    log.info("  %s", old_name)
    log.info("    -> %s", new_name)

    if dry_run:
        return "renamed"

    dir_path.rename(target)
    return "renamed"


# --- Entry point ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rename _unknown-date directories in the two-tree archive layout "
            "(matches/ for metadata, polymarket_sports/ for events)."
        ),
    )
    parser.add_argument(
        "--archive-root",
        required=True,
        type=Path,
        help="Root of the archive (e.g., /data/archive).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying anything.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    root: Path = args.archive_root.resolve()
    matches_root = root / MATCHES_SUBDIR
    sports_root = root / SPORTS_SUBDIR

    log.info("Archive root:       %s", root)
    log.info("matches/ subdir:    %s", matches_root)
    log.info("polymarket_sports/: %s", sports_root)
    log.info("Mode: %s", "DRY RUN" if args.dry_run else "APPLY")

    # --- Phase 1: matches/ ---
    log.info("")
    log.info("=== Phase 1: matches/ (metadata tree, authoritative for dates) ===")
    matches_candidates = find_unknown_date_dirs(matches_root)
    log.info("Phase 1 candidates: %d", len(matches_candidates))

    matches_counters: dict[str, int] = {}
    rename_map: dict[str, str] = {}
    for d in matches_candidates:
        status, new_name = migrate_matches_dir(d, dry_run=args.dry_run)
        matches_counters[status] = matches_counters.get(status, 0) + 1
        if status == "renamed" and new_name:
            rename_map[d.name] = new_name

    # --- Phase 2: polymarket_sports/ ---
    log.info("")
    log.info("=== Phase 2: polymarket_sports/ (events tree) ===")
    sports_candidates = find_unknown_date_dirs(sports_root)
    log.info("Phase 2 candidates: %d", len(sports_candidates))

    sports_counters: dict[str, int] = {}
    for d in sports_candidates:
        status = migrate_sports_dir(
            d, matches_root, rename_map, dry_run=args.dry_run
        )
        sports_counters[status] = sports_counters.get(status, 0) + 1

    # --- Summary ---
    log.info("")
    log.info("=== Summary ===")
    log.info("Phase 1 (matches/):")
    for status, count in sorted(matches_counters.items()):
        log.info("  %s: %d", status, count)
    log.info("Phase 2 (polymarket_sports/):")
    for status, count in sorted(sports_counters.items()):
        log.info("  %s: %d", status, count)

    if args.dry_run:
        log.info("")
        log.info("Dry run complete. Re-run without --dry-run to apply.")
    else:
        log.info("Migration complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
