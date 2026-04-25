"""API-Tennis WebSocket worker.

Connects to wss://wss.api-tennis.com/live with ?APIkey=... query auth.
Server pushes JSON-list messages of match-state items; no subscribe
protocol. Each item gets parsed and its event_key becomes the state
dict key.

Ported from latency-validation (code/capture/api_tennis_ws.py). Differences:
  - Writes into in-memory `state.matches` instead of JSONL to disk
  - No cross_feed routing (Phase 1A doesn't need Polymarket joins yet)
  - Field extraction is defensive — first real run will reveal the
    exact schema of unfamiliar fields, log warnings on first miss only

Connection model:
  - Single WebSocket. URL carries ?APIkey=...&timezone=UTC
  - No subscribe message. Server pushes whatever the account sees.
  - Messages: JSON list of dicts. ~24 fields per item, ~0.18 msg/s
    overall, ~1 update per match per minute.
  - Reconnect on transport errors with exponential backoff.

For demo-mode (no API key set), seeds state.matches with the v11 mockup
matches so the dashboard renders something visible. Demo mode is
explicitly opt-in via DEMO_MODE=1 env var. With API key set and
DEMO_MODE unset, the worker connects for real.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # older websockets layouts
    try:
        from websockets.client import connect as ws_connect  # type: ignore[no-redef]
    except ImportError:
        import websockets
        ws_connect = websockets.connect  # type: ignore[assignment]

from . import state
from .state import Match, Player, SetScore

log = logging.getLogger("api_tennis_worker")

# --- Config --------------------------------------------------------------

API_TENNIS_KEY: str = os.environ.get("API_TENNIS_KEY", "")
API_TENNIS_WS_BASE: str = os.environ.get(
    "API_TENNIS_WS_BASE", "wss://wss.api-tennis.com/live"
)
API_TENNIS_TIMEZONE: str = os.environ.get("API_TENNIS_TIMEZONE", "UTC")
DEMO_MODE: bool = os.environ.get("DEMO_MODE") == "1"

WS_RECONNECT_INITIAL_SECONDS: float = 1.0
WS_RECONNECT_MAX_SECONDS: float = 60.0
WS_RECONNECT_FACTOR: float = 2.0

# Statuses considered "live" for our purposes. Mirrors latency-validation
# guidance: do not trust event_live ("1" string even after match ends);
# trust event_status.
_FINISHED_STATUSES = {"Finished", "Retired", "Cancelled", "Walkover"}

# Track which schema fields we've already warned about, so logs don't
# explode on every message when a field is consistently missing.
_warned_missing: set[str] = set()

# One-shot raw-item logger. The first dict that reaches _apply_item gets
# logged in full at INFO level, so the operator has at least one
# guaranteed full-schema sample in Render logs without hunting through
# warning lines. Subsequent items are not logged.
_raw_sample_logged: bool = False


# --- Demo seeding --------------------------------------------------------

def _seed_demo_state() -> None:
    """Populate state.matches with the v11 mockup matches. Used only when
    DEMO_MODE=1 and an API key is not present."""
    demo = [
        Match(
            event_key="demo-1",
            tour="ATP", venue="Munich", round="R16",
            status="live", set_label="2nd set",
            p1=Player(name="Camilo Ugo Carabelli", country_iso3="ARG"),
            p2=Player(name="Flavio Cobolli", country_iso3="ITA"),
            p1_sets=[SetScore(games=7, tiebreak=9), SetScore(games=1)],
            p2_sets=[SetScore(games=6, tiebreak=7), SetScore(games=4)],
            p1_game="30", p2_game="40", server=2,
            p1_price_cents=31, p2_price_cents=70,
        ),
        Match(
            event_key="demo-2",
            tour="ATP", venue="Madrid", round="R32",
            status="live", set_label="2nd set",
            p1=Player(name="Learner Tien", country_iso3="USA"),
            p2=Player(name="Adolfo Vallejo", country_iso3="PAR"),
            p1_sets=[SetScore(games=4), SetScore(games=2)],
            p2_sets=[SetScore(games=6), SetScore(games=1)],
            p1_game="40", p2_game="40", server=1,
            p1_price_cents=24, p2_price_cents=77,
        ),
        Match(
            event_key="demo-3",
            tour="WTA", venue="Madrid", round="R32",
            status="live", set_label="2nd set",
            p1=Player(name="Hailey Baptiste", country_iso3="USA"),
            p2=Player(name="Jasmine Paolini", country_iso3="ITA"),
            p1_sets=[SetScore(games=7), SetScore(games=1)],
            p2_sets=[SetScore(games=5), SetScore(games=1)],
            p1_game="15", p2_game="40", server=2,
            p1_price_cents=66, p2_price_cents=35,
        ),
        Match(
            event_key="demo-4",
            tour="Ch.", venue="Rome", round="QF",
            status="live", set_label="2nd set",
            p1=Player(name="Andrea Guerrieri", country_iso3="ITA"),
            p2=Player(name="Filip Jianu", country_iso3="ROU"),
            p1_sets=[SetScore(games=6), SetScore(games=3)],
            p2_sets=[SetScore(games=6), SetScore(games=2)],
            p1_game="15", p2_game="0", server=1,
            p1_price_cents=94, p2_price_cents=6,
        ),
        Match(
            event_key="demo-5",
            tour="ATP", venue="Madrid", round="R16",
            status="upcoming",
            start_time="2026-04-25T16:45:00Z",
            p1=Player(name="Carlos Alcaraz", country_iso3="ESP"),
            p2=Player(name="Sebastian Korda", country_iso3="USA"),
            p1_price_cents=72, p2_price_cents=28,
        ),
    ]
    for m in demo:
        state.matches[m.event_key] = m


# --- Field extraction (defensive) ----------------------------------------

def _warn_once(field: str, item_keys: list[str]) -> None:
    if field in _warned_missing:
        return
    _warned_missing.add(field)
    log.warning(
        "API-Tennis schema: field %r not found on incoming item; "
        "available keys=%s. Update extractor if needed.",
        field, sorted(item_keys),
    )


def _str_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _int_or_none(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _classify_tour(item: dict) -> str:
    """Map API-Tennis event_type/tournament_name into ATP/WTA/Ch.

    Probe 1 found event_type_key 265=Atp Singles, 266=Wta Singles,
    281=Challenger Men Singles, 272=Challenger Women Singles. The
    item likely also has an event_type_type or similar string field;
    fall back to tournament_name keywords if the type field is absent.
    """
    type_key = _int_or_none(item.get("event_type_key"))
    if type_key in (265,):
        return "ATP"
    if type_key in (266,):
        return "WTA"
    if type_key in (281, 272):
        return "Ch."

    type_str = (_str_or_none(item.get("event_type_type")) or "").lower()
    if "challenger" in type_str:
        return "Ch."
    if "wta" in type_str or "women" in type_str:
        return "WTA"
    if "atp" in type_str or "men" in type_str:
        return "ATP"

    tn = (_str_or_none(item.get("tournament_name")) or "").lower()
    if "challenger" in tn:
        return "Ch."

    # Default — surface in the row as something rather than blank
    return "ATP"


def _venue_from_tournament(item: dict) -> str:
    """tournament_name in probe data is bare city names like "Madrid".
    Fall back to "Tour" if missing."""
    return _str_or_none(item.get("tournament_name")) or "Tour"


def _round_label(item: dict) -> str:
    """Round label. Real field name is unknown until first run; try a
    few common candidates and fall back to empty string."""
    for key in ("tournament_round", "event_round", "round"):
        v = _str_or_none(item.get(key))
        if v:
            return v
    if "tournament_round" not in item and "event_round" not in item and "round" not in item:
        _warn_once("round", list(item.keys()))
    return ""


def _player(item: dict, side: int) -> Player:
    """Build a Player. Names are 'M. Surname' format on API-Tennis;
    we render them as-is.

    Country code field name is `event_first_player_country_key` /
    `event_second_player_country_key` per Design Notes §6. The value
    may be ISO 3166-1 alpha-2 ('AR') or alpha-3 ('ARG') depending on
    the source — we pass it through as-is and let the frontend's flag
    lookup handle normalization. Empty/None becomes None.
    """
    name_field = "event_first_player" if side == 1 else "event_second_player"
    country_field = (
        f"event_{'first' if side == 1 else 'second'}_player_country_key"
    )
    name = _str_or_none(item.get(name_field)) or ""
    country = _str_or_none(item.get(country_field))
    if country:
        country = country.upper()
    return Player(name=name, country_iso3=country)


def _parse_set_scores(item: dict) -> tuple[list[SetScore], list[SetScore]]:
    """Extract per-set games and tiebreaks.

    Two empirical sources observed in the latency-validation corpus:
      1. `event_final_result` is a string with full set tally, format
         appears to be "6-4, 3-2" (per normalize.py docstring); used by
         analysis layer's ap_score field.
      2. `scores` may also exist as a list of {score_first, score_second}
         dicts — common API-Tennis convention but not confirmed in the
         latency-validation archive.

    Try the string parse first; fall back to the list parse; warn-once
    on miss of both. Tiebreak scores aren't in the string format, so
    we capture them only when the list-form is present.
    """
    p1_sets: list[SetScore] = []
    p2_sets: list[SetScore] = []

    # Source 1: event_final_result string, format "6-4, 3-2".
    final_result = _str_or_none(item.get("event_final_result"))
    if final_result:
        for piece in final_result.split(","):
            piece = piece.strip()
            if not piece or "-" not in piece:
                continue
            try:
                left, right = piece.split("-", 1)
                f = int(left.strip())
                s = int(right.strip())
                p1_sets.append(SetScore(games=f))
                p2_sets.append(SetScore(games=s))
            except (ValueError, AttributeError):
                continue
        if p1_sets:
            return p1_sets, p2_sets

    # Source 2: scores list of dicts.
    scores = item.get("scores")
    if isinstance(scores, list):
        for s in scores:
            if not isinstance(s, dict):
                continue
            f = _int_or_none(s.get("score_first"))
            sec = _int_or_none(s.get("score_second"))
            if f is None or sec is None:
                continue
            tb_f = _int_or_none(s.get("score_first_tb"))
            tb_s = _int_or_none(s.get("score_second_tb"))
            p1_sets.append(SetScore(games=f, tiebreak=tb_f))
            p2_sets.append(SetScore(games=sec, tiebreak=tb_s))
        return p1_sets, p2_sets

    # Neither source present — warn once.
    if "event_final_result" not in item and "scores" not in item:
        _warn_once("event_final_result|scores", list(item.keys()))
    return p1_sets, p2_sets


def _parse_current_game(item: dict) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """Extract current game point score (0/15/30/40/AD) and current server.

    Empirical from latency-validation normalize.py:
      - event_game_result: string like "30 - 40" (NOT a dict)
      - event_serve: string "First Player" / "Second Player" / None

    Defensive fallbacks retained for the rare case the schema diverges.
    """
    p1_game: Optional[str] = None
    p2_game: Optional[str] = None
    server: Optional[int] = None

    # Game points: empirical string format "p1 - p2"
    game_result = _str_or_none(item.get("event_game_result"))
    if game_result and "-" in game_result:
        try:
            left, right = game_result.split("-", 1)
            p1_game = left.strip() or None
            p2_game = right.strip() or None
        except ValueError:
            pass

    # Defensive fallback: dict-shaped variants from other API-Tennis tiers.
    if p1_game is None and p2_game is None:
        for key in ("event_game_result", "current_game"):
            v = item.get(key)
            if isinstance(v, dict):
                p1_game = _str_or_none(v.get("first")) or _str_or_none(v.get("score_first"))
                p2_game = _str_or_none(v.get("second")) or _str_or_none(v.get("score_second"))
                if p1_game or p2_game:
                    break

    # Server: empirical "First Player" / "Second Player" string.
    serve = _str_or_none(item.get("event_serve"))
    if serve == "First Player":
        server = 1
    elif serve == "Second Player":
        server = 2
    else:
        # Defensive fallback for int-coded variants.
        for key in ("event_server", "first_to_serve", "current_server"):
            v = item.get(key)
            s = _int_or_none(v)
            if s in (1, 2):
                server = s
                break

    return p1_game, p2_game, server


def _set_label(item: dict, p1_sets: list[SetScore], p2_sets: list[SetScore]) -> Optional[str]:
    """Human label like '2nd set'. Inferred from the count of sets seen,
    not from a dedicated field — keeps us robust to schema variants."""
    n = max(len(p1_sets), len(p2_sets))
    if n == 0:
        return None
    return {1: "1st set", 2: "2nd set", 3: "3rd set", 4: "4th set", 5: "5th set"}.get(n, f"set {n}")


def _classify_status(item: dict) -> str:
    """live | upcoming | finished. Use event_status authoritatively.

    Empirical values observed in latency-validation:
      - "Set 1", "Set 2", ... → live (in-progress sets)
      - "Finished", "Retired", "Cancelled", "Walkover" → finished

    Pre-match status values are not in the latency-validation corpus
    because that worker filtered them at the discovery layer. Anything
    not matching either known pattern gets warn-once'd and treated as
    upcoming — first real run reveals what API-Tennis actually sends.

    Empty event_status → upcoming (best guess for not-yet-started).
    """
    status = _str_or_none(item.get("event_status")) or ""
    if not status:
        return "upcoming"
    if status in _FINISHED_STATUSES:
        return "finished"
    if status.startswith("Set "):
        return "live"
    # Unknown non-empty status. Warn once with the value so we know what
    # to add to the classifier next session.
    _warn_once(f"event_status:{status}", list(item.keys()))
    return "upcoming"


def _start_time(item: dict) -> Optional[str]:
    """ISO start time for upcoming matches. Combine event_date +
    event_time if present."""
    d = _str_or_none(item.get("event_date"))
    t = _str_or_none(item.get("event_time"))
    if d and t:
        return f"{d}T{t}:00Z"
    return None


# --- Main parse ----------------------------------------------------------

def _apply_item(item: dict[str, Any]) -> None:
    """Translate one API-Tennis match-state dict into a Match in
    state.matches. Match key is the API-Tennis event_key."""
    global _raw_sample_logged
    if not _raw_sample_logged:
        _raw_sample_logged = True
        log.info("API-Tennis raw item sample (one-shot): %s", json.dumps(item, default=str))

    event_key = _int_or_none(item.get("event_key"))
    if event_key is None:
        # Without an event_key we can't address the match. Skip with a
        # warn-once; this should never happen on real data.
        _warn_once("event_key", list(item.keys()))
        return

    p1_sets, p2_sets = _parse_set_scores(item)
    p1_game, p2_game, server = _parse_current_game(item)
    status = _classify_status(item)

    if status == "finished":
        # Drop finished matches from the dashboard. If they reappear
        # on a future message, they get re-added; but generally they
        # stop being pushed.
        state.matches.pop(str(event_key), None)
        return

    m = Match(
        event_key=str(event_key),
        tour=_classify_tour(item),
        venue=_venue_from_tournament(item),
        round=_round_label(item),
        status=status,
        set_label=_set_label(item, p1_sets, p2_sets) if status == "live" else None,
        start_time=_start_time(item) if status == "upcoming" else None,
        p1=_player(item, 1),
        p2=_player(item, 2),
        p1_sets=p1_sets,
        p2_sets=p2_sets,
        p1_game=p1_game,
        p2_game=p2_game,
        server=server,
    )
    state.matches[str(event_key)] = m


def _handle_message(raw: str | bytes) -> None:
    """Parse one WS frame and apply each contained item to state.matches.

    The frame-arrival timestamp is recorded for the api_tennis source
    before any parsing, so even malformed frames count as "the
    connection is alive" — that's the semantic the liveness counter
    measures, per Design Notes §8.
    """
    state.source_timestamps["api_tennis"] = int(time.time() * 1000)

    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            log.warning("API-Tennis WS: non-UTF8 frame, skipping")
            return

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("API-Tennis WS: non-JSON frame (%s), skipping", exc)
        return

    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict) and "event_key" in parsed:
        items = [parsed]
    elif isinstance(parsed, dict):
        log.warning("API-Tennis WS: dict without event_key (keys=%s), skipping",
                    sorted(parsed.keys())[:10])
        return
    else:
        log.warning("API-Tennis WS: unexpected payload type %s, skipping",
                    type(parsed).__name__)
        return

    for item in items:
        if isinstance(item, dict):
            try:
                _apply_item(item)
            except Exception:
                log.exception("API-Tennis WS: failed to apply item, skipping")


# --- Worker entry point --------------------------------------------------

async def _run_once() -> None:
    """Single connect-receive cycle. Returns on connection close."""
    url = (
        f"{API_TENNIS_WS_BASE}"
        f"?APIkey={API_TENNIS_KEY}"
        f"&timezone={API_TENNIS_TIMEZONE}"
    )
    log.info("api_tennis_worker: opening WS")
    async with ws_connect(url, open_timeout=10, ping_interval=20) as ws:
        log.info("api_tennis_worker: connected, streaming events")
        async for raw in ws:
            _handle_message(raw)
    log.info("api_tennis_worker: WS closed by server, will reconnect")


async def run() -> None:
    """Supervisor loop. Reconnects with exponential backoff on transport
    errors. Returns only on CancelledError."""
    if DEMO_MODE:
        _seed_demo_state()
        log.info("api_tennis_worker: DEMO_MODE=1, seeded %d demo matches", len(state.matches))
        # Simulate frame-arrival cadence so the liveness counter cycles
        # realistically (otherwise it sits at "—" forever in demo). Probe 2
        # measured ~0.18 msg/s overall on real API-Tennis; 5s between bumps
        # is a reasonable mid-range simulation.
        while True:
            state.source_timestamps["api_tennis"] = int(time.time() * 1000)
            await asyncio.sleep(5)

    if not API_TENNIS_KEY:
        log.error(
            "api_tennis_worker: API_TENNIS_KEY not set and DEMO_MODE not set; "
            "worker idle. Set one of them."
        )
        await asyncio.Future()  # idle forever

    backoff = WS_RECONNECT_INITIAL_SECONDS
    while True:
        try:
            await _run_once()
            # Clean close from the server. Reset backoff but still wait
            # the initial interval before reconnecting — prevents tight
            # loops if the server is in a state where it accepts then
            # immediately closes connections.
            backoff = WS_RECONNECT_INITIAL_SECONDS
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            log.info("api_tennis_worker: cancelled, exiting")
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "api_tennis_worker: WS error (%s), reconnecting in %.1fs",
                exc, backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * WS_RECONNECT_FACTOR, WS_RECONNECT_MAX_SECONDS)
