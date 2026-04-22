"""Archive layout and JSONL writer.

All on-disk paths are computed here. Keeps worker code free of path
arithmetic and makes layout changes a single-file edit.

Archive structure:
    {ARCHIVE_ROOT}/
        gamma/
            {YYYY-MM-DD}.jsonl          — raw Gamma poll snapshots
        matches/
            {match_id}/
                meta.json                — per-match metadata (immutable)
                discovery_delta.jsonl    — added/removed event IDs per poll
        polymarket_sports/
            {match_id}/
                {YYYY-MM-DD}.jsonl       — raw Sports WS events
        polymarket_clob/
            {match_id}/
                {YYYY-MM-DD}.jsonl       — raw CLOB WS events (session 2.2)
        api_tennis/
            {match_id}/
                {YYYY-MM-DD}.jsonl       — raw API-Tennis events (Phase 3)
        overrides.yaml                   — match identity overrides
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import ARCHIVE_ROOT


# --- Path helpers -----------------------------------------------------------


def gamma_snapshot_path(date_str: str) -> Path:
    """Raw Gamma poll response archive for a given UTC date."""
    return ARCHIVE_ROOT / "gamma" / f"{date_str}.jsonl"


def match_dir(match_id: str) -> Path:
    return ARCHIVE_ROOT / "matches" / match_id


def meta_path(match_id: str) -> Path:
    return match_dir(match_id) / "meta.json"


def discovery_delta_path(match_id: str) -> Path:
    return match_dir(match_id) / "discovery_delta.jsonl"


def polymarket_sports_path(match_id: str, date_str: str) -> Path:
    return (
        ARCHIVE_ROOT
        / "polymarket_sports"
        / match_id
        / f"{date_str}.jsonl"
    )


def polymarket_clob_path(match_id: str, date_str: str) -> Path:
    return (
        ARCHIVE_ROOT
        / "polymarket_clob"
        / match_id
        / f"{date_str}.jsonl"
    )


def api_tennis_path(match_id: str, date_str: str) -> Path:
    return (
        ARCHIVE_ROOT
        / "api_tennis"
        / match_id
        / f"{date_str}.jsonl"
    )


# --- JSONL writer -----------------------------------------------------------


def utc_date_str(dt: datetime | None = None) -> str:
    """YYYY-MM-DD for the given UTC datetime (or now)."""
    dt = dt or datetime.now(UTC)
    return dt.strftime("%Y-%m-%d")


def utc_iso_now() -> str:
    return datetime.now(UTC).isoformat()


def arrived_at_ms() -> int:
    """Milliseconds since epoch, capture-host wall clock."""
    return int(datetime.now(UTC).timestamp() * 1000)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON record to path, ensuring the directory exists.

    Line-buffered: each call opens, writes one line, closes. This means
    every record is durable on disk the moment append_jsonl returns — a
    SIGTERM mid-record loses at most the current record, never corrupts
    earlier records.

    Trade-off: open/close per record is slower than keeping a file handle
    open. For our write rates (tens to low-hundreds of events per second
    across all workers) this is fine. Revisit if profiling shows it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def write_meta(match_id: str, meta: dict[str, Any]) -> bool:
    """Write meta.json for a match. Returns True if newly written, False if
    it already existed (meta.json is immutable by design)."""
    mp = meta_path(match_id)
    if mp.exists():
        return False
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True
