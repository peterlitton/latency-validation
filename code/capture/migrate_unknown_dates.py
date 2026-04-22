"""One-shot migration: rename `*_unknown-date` match directories.

Context
-------
Session 2.1 shipped with a bug in resolver._extract_event_date (originally
inline in resolve_polymarket_event): the canonical match_id was built by
reading `event.get("eventDate")`, but Gamma doesn't populate that field.
The field we want is `startDate`. Every match discovered in session 2.1
landed with an `_unknown-date` suffix in its canonical match_id, and the
corresponding directories on disk carry that suffix too.

The code fix (resolver.py / discovery.py) lands first and prevents new
matches from being created with `_unknown-date`. This script then repairs
the existing ones.

What it does
------------
For every directory whose name ends in `_unknown-date` anywhere under
`--archive-root`:
  1. Read its meta.json.
  2. Compute the correct event_date from meta.json's `start_date_iso`
     (already written by discovery.py on every poll, so it's present and
     correct even on the broken match_ids).
  3. Build the corrected match_id by replacing the `_unknown-date` suffix.
  4. Rename the directory and rewrite meta.json's `match_id` and
     `event_date` fields to match.

Idempotency
-----------
Safe to re-run. If the target directory already exists (partial prior run),
the script logs and skips. If `start_date_iso` is missing, empty, or not a
parseable YYYY-MM-DD prefix, the script logs and skips — it never guesses.

Usage
-----
Dry run (prints plan, touches nothing):
    python -m code.capture.migrate_unknown_dates --archive-root /data/archive --dry-run

Apply:
    python -m code.capture.migrate_unknown_dates --archive-root /data/archive

The archive root is required (no default) because running this against
the wrong directory would be destructive.

Out of scope
------------
This script does NOT touch events in `_unresolved/` — those are bug #2's
territory and gated on understanding that root cause separately.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("migrate_unknown_dates")

UNKNOWN_DATE_SUFFIX = "_unknown-date"


def find_unknown_date_dirs(root: Path) -> list[Path]:
    """Walk the archive root, return every directory ending in the suffix."""
    if not root.exists():
        log.error("Archive root does not exist: %s", root)
        return []
    results: list[Path] = []
    for p in root.rglob("*"):
        if p.is_dir() and p.name.endswith(UNKNOWN_DATE_SUFFIX):
            results.append(p)
    return sorted(results)


def parse_event_date(start_date_iso: str) -> str | None:
    """Return YYYY-MM-DD slice if start_date_iso looks valid, else None.

    Validates that the first 10 characters match the YYYY-MM-DD shape
    (`NNNN-NN-NN`) rather than trusting the slice blindly.
    """
    if not isinstance(start_date_iso, str) or len(start_date_iso) < 10:
        return None
    candidate = start_date_iso[:10]
    # Minimal YYYY-MM-DD shape check without pulling in a datetime parser.
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
    """Replace the trailing `_unknown-date` with `_{new_date}`."""
    if not old_match_id.endswith(UNKNOWN_DATE_SUFFIX):
        raise ValueError(
            f"match_id does not end in {UNKNOWN_DATE_SUFFIX!r}: {old_match_id!r}"
        )
    prefix = old_match_id[: -len(UNKNOWN_DATE_SUFFIX)]
    return f"{prefix}_{new_date}"


def migrate_one(dir_path: Path, dry_run: bool) -> str:
    """Migrate a single `_unknown-date` directory.

    Returns a status token for reporting: one of
      "renamed", "skipped_no_meta", "skipped_bad_meta", "skipped_no_date",
      "skipped_target_exists", "skipped_already_correct".
    """
    meta_path = dir_path / "meta.json"
    if not meta_path.exists():
        log.warning("  [skip] no meta.json in %s", dir_path)
        return "skipped_no_meta"

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("  [skip] meta.json not parseable in %s: %s", dir_path, exc)
        return "skipped_bad_meta"

    start_date_iso = meta.get("start_date_iso") or ""
    new_date = parse_event_date(start_date_iso)
    if new_date is None:
        log.warning(
            "  [skip] start_date_iso missing/invalid in %s (value=%r)",
            dir_path,
            start_date_iso,
        )
        return "skipped_no_date"

    old_match_id = dir_path.name
    try:
        new_match_id = rebuild_match_id(old_match_id, new_date)
    except ValueError:
        # Guard against walk-tree surprises — we filter by suffix already,
        # but belt-and-braces.
        log.error("  [skip] unexpected match_id shape: %r", old_match_id)
        return "skipped_bad_meta"

    target = dir_path.with_name(new_match_id)
    if target == dir_path:
        # Shouldn't happen given the suffix filter, but handle cleanly.
        return "skipped_already_correct"

    if target.exists():
        log.warning(
            "  [skip] target already exists: %s (prior partial migration?)",
            target,
        )
        return "skipped_target_exists"

    log.info("  %s", old_match_id)
    log.info("    -> %s", new_match_id)

    if dry_run:
        return "renamed"  # counted as would-rename in dry-run tally

    # Apply: rename dir first, then rewrite meta.json in the new location.
    # Order matters: if the rename succeeds and the meta write fails, a
    # re-run will still find the new dir with the stale match_id inside
    # and correct it (re-run reads new dir's meta and notices match_id
    # still has _unknown-date — but wait, on the second run the dir no
    # longer ends in _unknown-date, so find_unknown_date_dirs won't pick
    # it up). We therefore write meta.json first, then rename — reversing
    # that order. If the rename fails after meta is written, next run
    # will still find the old-named dir (ends in _unknown-date) and
    # reprocess from scratch.
    meta["match_id"] = new_match_id
    meta["event_date"] = new_date
    # Append a migration provenance note. Small, optional.
    migrations = meta.get("migrations") or []
    migrations.append(
        {
            "kind": "unknown_date_rename",
            "from_match_id": old_match_id,
            "to_match_id": new_match_id,
            "source_field": "start_date_iso",
        }
    )
    meta["migrations"] = migrations

    meta_path.write_text(
        json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8"
    )
    dir_path.rename(target)
    return "renamed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rename _unknown-date match directories using start_date_iso from meta.json.",
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
    log.info("Archive root: %s", root)
    log.info("Mode: %s", "DRY RUN" if args.dry_run else "APPLY")

    dirs = find_unknown_date_dirs(root)
    log.info("Found %d candidate directories ending in %r",
             len(dirs), UNKNOWN_DATE_SUFFIX)

    if not dirs:
        log.info("Nothing to do.")
        return 0

    counters: dict[str, int] = {}
    for d in dirs:
        status = migrate_one(d, dry_run=args.dry_run)
        counters[status] = counters.get(status, 0) + 1

    log.info("-- Summary --")
    for status, count in sorted(counters.items()):
        log.info("  %s: %d", status, count)

    if args.dry_run:
        log.info("Dry run complete. Re-run without --dry-run to apply.")
    else:
        log.info("Migration complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
