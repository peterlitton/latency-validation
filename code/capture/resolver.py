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

    The `eventDate` fallback is retained as defense in depth (session 2.2
    decision): once the live-only filter is in place, `startDate` should
    always be populated, but the fallback protects against malformed-response
    failure modes that silently produced `_unknown-date` suffixes in 2.1.
    """
    raw = event.get("startDate") or event.get("eventDate") or ""
    if not isinstance(raw, str):
        return ""
    return raw[:10]


# Participant-type discriminators used on the Polymarket US gateway.
# Both PLAYER and TEAM appear on tennis singles matches empirically:
# session 2.2 captured 20k+ events across PLAYER-typed matches, then
# during commit 6's live-window verification encountered 7 active TEAM-
# typed matches where Gamma uses `participant["team"]["name"]` for the
# player name. Session 2.2 scope accepts either as a "player" for
# match-id purposes; nominees remain out of scope (placeholder
# participants for unresolved draw positions, no match being played).
PARTICIPANT_TYPE_PLAYER = "PARTICIPANT_TYPE_PLAYER"
PARTICIPANT_TYPE_TEAM = "PARTICIPANT_TYPE_TEAM"


def _extract_player_names(participants: list[Any]) -> list[str]:
    """Return player names from participants, PLAYER or TEAM type.

    The US gateway uses a typed-wrapper shape for participants:
        {"type": "PARTICIPANT_TYPE_PLAYER", "player": {"name": "..."}}
        {"type": "PARTICIPANT_TYPE_TEAM",   "team":   {"name": "..."}}
        {"type": "PARTICIPANT_TYPE_NOMINEE", ...}    ← out of scope

    Empirically both PLAYER and TEAM types appear on tennis singles
    matches (why Gamma uses two types for the same conceptual entity is
    not documented; the two types have been observed within the same
    session). Both are treated as "player" for match-id construction —
    the nested `.name` field is the real player name in both cases.
    Nominees remain out of scope per session 2.2 scope decision.

    An event with zero PLAYER-or-TEAM participants will fail the
    downstream singles check and be rejected.
    """
    names: list[str] = []
    for p in participants:
        if not isinstance(p, dict):
            continue
        p_type = p.get("type")
        if p_type == PARTICIPANT_TYPE_PLAYER:
            inner = p.get("player") or {}
        elif p_type == PARTICIPANT_TYPE_TEAM:
            inner = p.get("team") or {}
        else:
            continue
        if not isinstance(inner, dict):
            continue
        name = (inner.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def resolve_polymarket_event(
    event: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> ResolvedIdentity:
    """Given a raw Gamma event object, produce a ResolvedIdentity.

    Scope (v1): live singles tennis matches only.

    Rejection order (first match wins; keeps log reasons unambiguous):
      1. Ended or closed — event is done.
      2. Not currently live — scheduled-future or pre-match; out of scope
         per session 2.2 scope decision. v1 research questions compare
         event timing during live play, so pre-match events generate no
         comparable WS traffic.
      3. Doubles/mixed — more than two PLAYER-or-TEAM-typed participants.
      4. Not a recognisable singles match — anything other than exactly
         two PLAYER-or-TEAM-typed participants (covers nominee-only
         events, malformed payloads, and solo placeholder events).
         Nominee-only events are the main expected case and are out of
         scope by session 2.2 decision.

    Live singles with two PLAYER-or-TEAM participants either resolve
    cleanly or get flagged (missing tournament name, etc.) — flagged
    events are still captured, with the flag recorded in meta.json for
    operator review.
    """
    # Extract fields defensively — the gateway response shape has enough
    # nested optionality to warrant it.
    event_state = event.get("eventState") or {}
    tennis_state = event_state.get("tennisState") or {}
    tournament = tennis_state.get("tournamentName") or ""

    participants = event.get("participants") or []
    player_names = _extract_player_names(participants)
    event_date = _extract_event_date(event)

    # --- Rejections ---

    if event.get("ended") or event.get("closed"):
        return ResolvedIdentity(
            match_id=None, status="rejected", reason="event ended or closed"
        )

    # Live-only filter (session 2.2 scope decision). `live` is a top-level
    # boolean on Gamma events; scheduled-but-not-yet-live events return
    # False here. Strict stateless filter: on transient `live=False` during
    # delays, the event drops from the active set; the next poll (60s)
    # restores it if play resumes. Option 2 (sticky set) rejected due to
    # the trapped-match failure mode if `ended` never fires cleanly.
    if not bool(event.get("live")):
        return ResolvedIdentity(
            match_id=None, status="rejected", reason="not live"
        )

    if len(player_names) > 2:
        return ResolvedIdentity(
            match_id=None,
            status="rejected",
            reason=f"doubles/mixed ({len(player_names)} player/team participants)",
        )

    if len(player_names) != 2:
        # Either zero (likely nominee-only event, out of scope) or one
        # (malformed payload). Reject rather than flag — a valid live
        # singles match must have exactly two PLAYER-or-TEAM participants.
        return ResolvedIdentity(
            match_id=None,
            status="rejected",
            reason=(
                f"not a recognisable singles match "
                f"({len(player_names)} player/team participants; "
                f"{len(participants)} total)"
            ),
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

    # Defensive tripwire: a live singles event with two player/team
    # participants but a missing tournament name is unexpected post-
    # nominee-filter. Session 2.2 hypothesis: bug #3 (unknown-tournament)
    # was caused by nominee events, and the live-only + PLAYER/TEAM-only
    # filters above should eliminate them entirely. If this WARNING
    # fires, the hypothesis was wrong and there's another shape variant
    # to investigate. Zero-cost insurance.
    if not tournament:
        log.warning(
            "Live singles event has empty tournamentName: "
            "event_id=%s title=%r — bug #3 hypothesis may be incomplete",
            event.get("id"),
            event.get("title"),
        )
        return ResolvedIdentity(
            match_id=mid,
            status="flagged",
            reason="missing tournament name on live match (unexpected)",
        )

    return ResolvedIdentity(match_id=mid, status="resolved")

