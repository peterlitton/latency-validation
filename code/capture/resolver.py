"""Match identity resolution.

Produces a study-internal canonical match_id from each source's native
identifiers, so events from API-Tennis, Polymarket Sports WS, and Polymarket
CLOB WS all land in the same archive directory for the same physical match.

Canonical format:
    {tournament_slug}_{player_a_slug}_{player_b_slug}_{event_date}

where:
- tournament_slug is the tournament name, lowercase, ASCII-only, hyphens.
- player_a_slug / player_b_slug are player names slugified and sorted
  alphabetically (so "Medvedev vs Djokovic" and "Djokovic vs Medvedev"
  produce the same ID).
- event_date is YYYY-MM-DD UTC.

Example: wimbledon_djokovic-novak_medvedev-daniil_2026-07-03

Rationale: readable in JSONL tails during Phase 4/7 analysis, source-agnostic
so v1.2+ new feeds don't need remapping, and deterministic from metadata that
every source provides in some form.

Overrides file (YAML) handles cases where fuzzy matching fails:
    - A player's name appears differently in two sources.
    - A tournament slug differs between sources.
    - Edge cases that aren't worth a regex for.

Overrides format (one entry per canonical match_id):

    matches:
      wimbledon_djokovic-novak_medvedev-daniil_2026-07-03:
        polymarket_event_id: "9579"
        api_tennis_event_key: "12345"
        notes: "API-Tennis spelled 'Novak Djokovich' — typo"
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # overrides unsupported until pyyaml is installed

from .config import OVERRIDES_PATH

log = logging.getLogger("capture.resolver")


# --- Slugification ----------------------------------------------------------


_SLUG_INVALID = re.compile(r"[^a-z0-9\-]+")


def slugify(text: str) -> str:
    """ASCII-only, lowercase, hyphenated. Deterministic.

    Strips diacritics so "Medvedev" and "Médvédev" slug identically;
    collapses whitespace and punctuation to single hyphens.
    """
    if not text:
        return ""
    # Decompose accented characters and drop combining marks.
    ascii_only = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    # Lowercase; replace anything non-alnum with hyphens; collapse repeats.
    lowered = ascii_only.lower().strip()
    with_hyphens = _SLUG_INVALID.sub("-", lowered)
    # Strip leading/trailing hyphens and collapse runs.
    collapsed = re.sub(r"-+", "-", with_hyphens).strip("-")
    return collapsed


def player_slug(name: str) -> str:
    """Slug for a player name. Preserves last-first ordering by joining
    first and last name with a hyphen after slugification."""
    return slugify(name)


# --- Canonical match_id -----------------------------------------------------


def canonical_match_id(
    tournament_name: str,
    player_a_name: str,
    player_b_name: str,
    event_date: str,
) -> str:
    """Build the study-internal canonical match_id.

    Players are slugified and sorted alphabetically so side order doesn't
    matter. event_date is expected as YYYY-MM-DD.
    """
    t_slug = slugify(tournament_name)
    a_slug = player_slug(player_a_name)
    b_slug = player_slug(player_b_name)
    p_slugs = sorted([s for s in (a_slug, b_slug) if s])
    parts = [
        t_slug or "unknown-tournament",
        *p_slugs,
        event_date or "unknown-date",
    ]
    return "_".join(parts)


# --- Resolved identity ------------------------------------------------------


@dataclass
class ResolvedIdentity:
    """Result of resolving a source-native identifier.

    status:
      "resolved"  — canonical match_id is known.
      "flagged"   — ambiguous; caller should still capture but mark for
                    manual override. match_id is a best-effort slug.
      "rejected"  — event should not be captured (e.g., doubles, ended).
    """

    match_id: str | None
    status: str
    reason: str = ""


# --- Overrides loader -------------------------------------------------------


def load_overrides(path: Path | None = None) -> dict[str, Any]:
    """Read the overrides YAML. Returns an empty dict if the file is
    missing or if pyyaml isn't installed. Logs a warning if pyyaml is
    missing so operators notice.
    """
    p = path or OVERRIDES_PATH
    if yaml is None:
        log.warning(
            "pyyaml not installed; overrides file at %s will not be read",
            p,
        )
        return {}
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        log.warning("Overrides file %s is not a mapping; ignoring", p)
        return {}
    return data


# --- Polymarket-specific resolver ------------------------------------------


def _extract_event_date(event: dict[str, Any]) -> str:
    """Pull the event date as YYYY-MM-DD from a Gamma event payload.

    Prefers `startDate` (empirically present on Gamma events, per session 2.1
    discovery; same field PM-Tennis uses at H-016). Falls back to `eventDate`
    (named in the brief but empirically absent from Gamma responses). Returns
    empty string if neither is present or usable, which produces the
    "unknown-date" canonical suffix downstream.

    The `[:10]` slice handles both ISO-8601 with time (`"2026-04-22T13:00:00Z"`)
    and plain-date (`"2026-04-22"`) inputs.
    """
    raw = event.get("startDate") or event.get("eventDate") or ""
    if not isinstance(raw, str):
        return ""
    return raw[:10]


def resolve_polymarket_event(
    event: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> ResolvedIdentity:
    """Given a raw Gamma event object, produce a ResolvedIdentity.

    Uses the event's metadata fields (tournamentName, participants, startDate).
    Doubles and already-ended events are rejected. Anything else either
    resolves cleanly or gets flagged for override.
    """
    # Extract fields defensively — the gateway response shape has enough
    # nested optionality to warrant it.
    event_state = event.get("eventState") or {}
    tennis_state = event_state.get("tennisState") or {}
    tournament = tennis_state.get("tournamentName") or ""

    participants = event.get("participants") or []
    player_names = [
        (p.get("name") or "").strip() for p in participants if isinstance(p, dict)
    ]
    player_names = [n for n in player_names if n]

    event_date = _extract_event_date(event)

    # Rejections.
    if event.get("ended") or event.get("closed"):
        return ResolvedIdentity(
            match_id=None, status="rejected", reason="event ended or closed"
        )
    if len(player_names) > 2:
        return ResolvedIdentity(
            match_id=None,
            status="rejected",
            reason=f"doubles/mixed ({len(player_names)} participants)",
        )

    if len(player_names) < 2:
        # Not enough info to build a canonical ID. Flag but don't reject —
        # metadata may fill in later.
        fallback = canonical_match_id(
            tournament,
            player_names[0] if player_names else "",
            "",
            event_date,
        )
        return ResolvedIdentity(
            match_id=fallback,
            status="flagged",
            reason=f"only {len(player_names)} participants in Gamma payload",
        )

    mid = canonical_match_id(
        tournament, player_names[0], player_names[1], event_date
    )

    # Overrides may remap a Polymarket event_id to a different canonical
    # match_id if the name spellings disagree with API-Tennis.
    if overrides:
        ev_id = str(event.get("id") or "")
        by_polymarket = overrides.get("by_polymarket_event_id") or {}
        if ev_id and ev_id in by_polymarket:
            mapped = by_polymarket[ev_id]
            if isinstance(mapped, str):
                return ResolvedIdentity(
                    match_id=mapped, status="resolved", reason="override"
                )

    if not tournament or not player_names[0] or not player_names[1]:
        return ResolvedIdentity(
            match_id=mid,
            status="flagged",
            reason="missing tournament or player name",
        )

    return ResolvedIdentity(match_id=mid, status="resolved")
