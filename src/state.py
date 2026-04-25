"""In-memory match state.

Single dict keyed by API-Tennis event_key. Worker writes, endpoints read.
No locking yet — single asyncio loop, single writer. Revisit if that changes.

Also tracks last-event-arrived timestamps per upstream source. These are
process-level values (one per source), not per-match. The frontend uses
them to render the liveness counters in the header. Per Design Notes §8,
the counter resets on any message arrival from that source — not just
messages with score changes — so the counter measures connection health,
not match activity.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Player:
    name: str
    country_iso3: Optional[str] = None  # for flag rendering; None until resolved


@dataclass
class SetScore:
    games: int                          # 0-7 (or higher in deciding sets without tiebreak)
    tiebreak: Optional[int] = None      # tiebreak point count if this set went to tiebreak


@dataclass
class Match:
    event_key: str
    tour: str                           # "ATP" | "WTA" | "Ch."
    venue: str                          # tournament city, e.g. "Madrid"
    round: str                          # e.g. "R32", "QF"
    status: str                         # "live" | "upcoming" | "finished"
    set_label: Optional[str] = None     # e.g. "2nd set"; None for non-live
    start_time: Optional[str] = None    # ISO string for upcoming matches

    p1: Player = field(default_factory=lambda: Player(name=""))
    p2: Player = field(default_factory=lambda: Player(name=""))

    p1_sets: list[SetScore] = field(default_factory=list)
    p2_sets: list[SetScore] = field(default_factory=list)

    p1_game: Optional[str] = None       # "0" | "15" | "30" | "40" | "AD"
    p2_game: Optional[str] = None

    server: Optional[int] = None        # 1 or 2; None until first serve

    # Phase 1C — populated by Polymarket worker
    p1_price_cents: Optional[int] = None
    p2_price_cents: Optional[int] = None


# Global match state. Worker mutates; endpoints read.
matches: dict[str, Match] = {}

# Last-event-arrived timestamps (epoch ms) per upstream source.
# None means "no event has arrived from that source yet this process."
# api_tennis: updated on every WS frame received from API-Tennis,
#   regardless of whether the frame contains data for any match we
#   care about. Heartbeat-style activity counts.
# polymarket: Phase 1C onward. Stays None until then.
source_timestamps: dict[str, Optional[int]] = {
    "api_tennis": None,
    "polymarket": None,
}


def snapshot() -> dict:
    """Return the current state for the dashboard.

    Shape:
        {
          "matches": [<match dict>, ...],   # live first, then upcoming
          "source_timestamps": {            # epoch ms or null per source
            "api_tennis": <int|null>,
            "polymarket": <int|null>,
          },
        }
    """
    live = [m for m in matches.values() if m.status == "live"]
    upcoming = sorted(
        [m for m in matches.values() if m.status == "upcoming"],
        key=lambda m: m.start_time or "",
    )
    return {
        "matches": [asdict(m) for m in (*live, *upcoming)],
        "source_timestamps": dict(source_timestamps),
    }
