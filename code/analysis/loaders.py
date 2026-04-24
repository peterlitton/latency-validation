"""Raw JSONL loaders, one per archive sub-tree.

Each loader returns a list of the decoded records. Loaders are dumb — no
filtering, no transformation, just read-and-parse. Downstream modules do
the semantic work.

Path conventions follow `code/capture/archive.py`:
- matches/{match_id}/meta.json, discovery_delta.jsonl
- polymarket_sports/{match_id}/{YYYY-MM-DD}.jsonl
- api_tennis/{match_id}/{YYYY-MM-DD}.jsonl
- api_tennis/_unresolved/{YYYY-MM-DD}.jsonl

The archive root is configurable (defaults to /data/archive, matches
production on Render) so analysis can run against a copied archive for
local development.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ARCHIVE_ROOT = Path("/data/archive")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of dicts. Returns [] if absent.

    Malformed lines are skipped with a print-to-stderr warning rather
    than crashing — if a line is corrupted mid-write, we'd rather see
    the rest of the data than nothing.
    """
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for ln, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # Don't silently eat bad lines — calibration should know.
                print(
                    f"[loaders] WARN: bad JSONL at {path}:{ln}: {exc}"
                )
    return records


def load_meta(
    match_id: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
) -> dict[str, Any]:
    """Return the match's meta.json dict, or {} if absent."""
    path = archive_root / "matches" / match_id / "meta.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_discovery_delta(
    match_id: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
) -> list[dict[str, Any]]:
    """Return discovery add/remove transitions for the match."""
    path = archive_root / "matches" / match_id / "discovery_delta.jsonl"
    return _read_jsonl(path)


def load_polymarket_sports(
    match_id: str,
    date_str: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
) -> list[dict[str, Any]]:
    """Return all Polymarket Sports WS records for match/date.

    Includes both `market_data` and `trade` event_name records — the
    capture worker writes them to the same file distinguished by
    event_name field. Downstream code partitions.
    """
    path = (
        archive_root
        / "polymarket_sports"
        / match_id
        / f"{date_str}.jsonl"
    )
    return _read_jsonl(path)


def load_api_tennis_routed(
    match_id: str,
    date_str: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
) -> list[dict[str, Any]]:
    """Return API-Tennis records routed to this match_id."""
    path = archive_root / "api_tennis" / match_id / f"{date_str}.jsonl"
    return _read_jsonl(path)


def recover_api_tennis_unresolved(
    event_keys: Iterable[int],
    date_str: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
) -> list[dict[str, Any]]:
    """Pull API-Tennis records from _unresolved/ matching any of event_keys.

    Session 3.1 curation workflow acknowledged that events arriving
    before an override is added go to _unresolved and are not
    retroactively moved. Phase 7 analysis rule: route by event_key, not
    by directory placement.

    Returns records from _unresolved/{date}.jsonl whose event_key is in
    the given set. Accepts an iterable to handle the (future) case of
    a match that might have multiple API-Tennis event_keys across days
    or restarts.
    """
    target = set(event_keys)
    if not target:
        return []
    path = archive_root / "api_tennis" / "_unresolved" / f"{date_str}.jsonl"
    out: list[dict[str, Any]] = []
    for rec in _read_jsonl(path):
        ek = rec.get("event_key")
        # event_key may be null if the raw payload lacked one entirely.
        if ek is not None and ek in target:
            out.append(rec)
    return out
