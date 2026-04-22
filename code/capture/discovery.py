"""Gamma discovery loop.

Polls the Polymarket US public gateway at a fixed interval, extracts tennis
events, and maintains a discovery state machine:

  - Each poll produces a raw JSONL snapshot for archival.
  - Newly-seen events get a meta.json written (immutable once written).
  - Added/removed event IDs become a delta record.
  - The active set is exposed via `current_slugs()` and `current_match_ids()`
    so the Sports WS worker knows what to subscribe to.

Design notes:
  - Doubles/mixed events are filtered out at the resolver layer (see
    resolver.py). They still appear in the raw Gamma snapshot but don't
    produce meta.json files or enter the active set.
  - Gateway is unauthenticated. If it starts requiring auth we'll see 401s.
  - Pagination stops when a page returns fewer events than the page limit.
  - Poll failures are logged, not raised — the loop continues to the next
    tick so a transient gateway outage doesn't kill the worker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from . import archive
from .config import (
    GAMMA_BASE,
    GAMMA_PAGE_LIMIT,
    GAMMA_POLL_INTERVAL_SECONDS,
    TENNIS_SPORT_SLUG,
    USER_AGENT,
)
from .resolver import ResolvedIdentity, load_overrides, resolve_polymarket_event

log = logging.getLogger("capture.discovery")


class GammaClient:
    """Thin async wrapper around the Polymarket US public gateway."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=GAMMA_BASE,
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_all_sports(self) -> list[dict[str, Any]]:
        """GET /v2/sports — all sports for slug verification."""
        resp = await self._client.get("/v2/sports")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("sports", "data", "results", "items"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        log.warning("Unexpected /v2/sports response shape: %s", type(data))
        return []

    async def get_events_page(
        self, slug: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """One page of /v2/sports/{slug}/events."""
        resp = await self._client.get(
            f"/v2/sports/{slug}/events",
            params={"limit": limit, "offset": offset},
        )
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events") if isinstance(data, dict) else None
        return events or []

    async def get_all_events(self, slug: str) -> list[dict[str, Any]]:
        """Paginate until an empty-or-short page."""
        all_events: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.get_events_page(slug, GAMMA_PAGE_LIMIT, offset)
            all_events.extend(page)
            if len(page) < GAMMA_PAGE_LIMIT:
                break
            offset += GAMMA_PAGE_LIMIT
        return all_events


async def verify_sport_slug(client: GammaClient, slug: str) -> bool:
    """Log every sport the gateway knows; return True if our slug is there.

    Non-fatal if the slug isn't found — polls will return empty, which is
    visible in logs, rather than crashing the service.
    """
    log.info("Verifying sport slug %r against gateway /v2/sports…", slug)
    try:
        sports = await client.get_all_sports()
    except Exception as exc:  # network, JSON, anything
        log.critical("Could not reach gateway /v2/sports: %s", exc)
        return False

    available = []
    matched = False
    for sport in sports:
        s = sport.get("slug") or ""
        n = sport.get("name") or ""
        available.append(s)
        if s == slug:
            matched = True
            log.info("  ✓ match — slug=%r name=%r", s, n)
        else:
            log.info("    slug=%r name=%r", s, n)

    if not matched:
        log.error(
            "Sport slug %r NOT found. Available: %s. "
            "Set TENNIS_SPORT_SLUG env var to override.",
            slug,
            available,
        )
    return matched


# --- Moneyline market extraction --------------------------------------------

# The constant Polymarket uses to tag moneyline markets in the v2 gateway.
# From PM-Tennis discovery.py's field documentation.
MONEYLINE_MARKET_TYPE = "SPORTS_MARKET_TYPE_MONEYLINE"


def extract_moneyline_slugs(event: dict[str, Any]) -> list[str]:
    """Pull market_slug values from an event's moneyline markets.

    Sports WS subscribes by market_slug (documented 100-slug cap per
    subscription). Returns the slugs for only the moneyline markets on
    this event — not all markets (e.g., set-score markets are separate).
    """
    markets = event.get("markets") or []
    slugs: list[str] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        if m.get("sportsMarketTypeV2") != MONEYLINE_MARKET_TYPE:
            continue
        if not m.get("active") or m.get("closed"):
            continue
        slug = m.get("slug")
        if isinstance(slug, str) and slug:
            slugs.append(slug)
    return slugs


def extract_asset_identifiers(event: dict[str, Any]) -> list[str]:
    """Pull marketSides[].identifier from moneyline markets.

    These are the asset/token IDs that CLOB-side capture will reference
    in session 2.2. Stored in meta.json for later use.
    """
    ids: list[str] = []
    for m in event.get("markets") or []:
        if not isinstance(m, dict):
            continue
        if m.get("sportsMarketTypeV2") != MONEYLINE_MARKET_TYPE:
            continue
        for side in m.get("marketSides") or []:
            if isinstance(side, dict):
                ident = side.get("identifier")
                if isinstance(ident, str) and ident:
                    ids.append(ident)
    return ids


# --- Discovery loop ---------------------------------------------------------


class DiscoveryLoop:
    """Maintains the active set of tennis events and emits persistence."""

    def __init__(self, client: GammaClient) -> None:
        self._client = client
        # match_id -> meta dict. Authoritative live state.
        self._active: dict[str, dict[str, Any]] = {}
        # match_id -> list of Sports WS slugs for that match.
        self._match_slugs: dict[str, list[str]] = {}
        # Cached overrides; reloaded each poll (cheap, file is small).
        self._overrides: dict[str, Any] = {}

    def current_slugs(self) -> list[str]:
        """All Sports WS slugs across all active matches.

        Returned as a flat list; the Sports WS worker is responsible for
        batching into <=100-slug subscriptions per config.
        """
        all_slugs: list[str] = []
        for slugs in self._match_slugs.values():
            all_slugs.extend(slugs)
        return all_slugs

    def current_match_ids(self) -> list[str]:
        return list(self._active.keys())

    def match_id_for_slug(self, slug: str) -> str | None:
        """Reverse lookup: Sports WS payload will arrive keyed by slug, so
        the worker needs to map back to our canonical match_id."""
        for mid, slugs in self._match_slugs.items():
            if slug in slugs:
                return mid
        return None

    async def run_once(self) -> None:
        """Execute one poll cycle. Never raises; errors go to the log."""
        poll_ts = archive.utc_iso_now()
        date_str = archive.utc_date_str()

        # Pick up any newly-added overrides without restarting.
        self._overrides = load_overrides()

        try:
            raw_events = await self._client.get_all_events(TENNIS_SPORT_SLUG)
        except httpx.HTTPStatusError as exc:
            log.error("Gateway HTTP error during poll: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001 — loop must survive
            log.error("Gateway unreachable during poll: %s", exc)
            return

        # Archive the raw response before anything else can fail.
        snap_path = archive.gamma_snapshot_path(date_str)
        for ev in raw_events:
            archive.append_jsonl(
                snap_path, {"poll_ts": poll_ts, "event": ev}
            )

        # Build the new active set.
        new_active: dict[str, dict[str, Any]] = {}
        new_match_slugs: dict[str, list[str]] = {}

        for ev in raw_events:
            identity: ResolvedIdentity = resolve_polymarket_event(
                ev, self._overrides
            )
            if identity.status == "rejected":
                continue

            match_id = identity.match_id
            if not match_id:
                continue

            # Build the meta record. Written only on first sighting.
            meta = _build_meta(ev, match_id, identity, poll_ts)

            # Write meta.json (immutable; skipped on repeat polls).
            was_new = archive.write_meta(match_id, meta)
            if was_new:
                log.info(
                    "Discovered match %s (status=%s) — tournament=%r "
                    "players=%r+%r",
                    match_id,
                    identity.status,
                    meta.get("tournament_name"),
                    meta.get("player_a_name"),
                    meta.get("player_b_name"),
                )

            new_active[match_id] = meta
            new_match_slugs[match_id] = extract_moneyline_slugs(ev)

        # Compute and emit delta.
        prev_ids = set(self._active.keys())
        curr_ids = set(new_active.keys())
        added = sorted(curr_ids - prev_ids)
        removed = sorted(prev_ids - curr_ids)

        if added or removed:
            # One delta record per affected match, so each match's
            # discovery_delta.jsonl is self-contained.
            for mid in added:
                archive.append_jsonl(
                    archive.discovery_delta_path(mid),
                    {"poll_ts": poll_ts, "change": "added"},
                )
            for mid in removed:
                archive.append_jsonl(
                    archive.discovery_delta_path(mid),
                    {"poll_ts": poll_ts, "change": "removed"},
                )

        self._active = new_active
        self._match_slugs = new_match_slugs

        log.info(
            "Poll complete: active=%d added=%d removed=%d raw=%d slugs=%d",
            len(self._active),
            len(added),
            len(removed),
            len(raw_events),
            len(self.current_slugs()),
        )

    async def run_forever(self) -> None:
        log.info(
            "Discovery loop starting: slug=%r interval=%ds",
            TENNIS_SPORT_SLUG,
            GAMMA_POLL_INTERVAL_SECONDS,
        )
        while True:
            await self.run_once()
            await asyncio.sleep(GAMMA_POLL_INTERVAL_SECONDS)


def _build_meta(
    event: dict[str, Any],
    match_id: str,
    identity: ResolvedIdentity,
    poll_ts: str,
) -> dict[str, Any]:
    """Flatten a raw Gamma event into the per-match meta record."""
    event_state = event.get("eventState") or {}
    tennis_state = event_state.get("tennisState") or {}
    participants = event.get("participants") or []
    names = [
        (p.get("name") or "").strip()
        for p in participants
        if isinstance(p, dict)
    ]
    names = [n for n in names if n]

    return {
        "match_id": match_id,
        "resolution_status": identity.status,
        "resolution_reason": identity.reason,
        # Identity fields.
        "polymarket_event_id": str(event.get("id") or ""),
        "polymarket_event_slug": event.get("slug") or "",
        "sportradar_game_id": event.get("sportradarGameId") or "",
        # Match context.
        "title": event.get("title") or "",
        "tournament_name": tennis_state.get("tournamentName") or "",
        "round": tennis_state.get("round") or "",
        "event_date": (event.get("eventDate") or "")[:10],
        "start_date_iso": event.get("startDate") or "",
        "end_date_iso": event.get("endDate") or "",
        # Players.
        "player_a_name": names[0] if len(names) >= 1 else "",
        "player_b_name": names[1] if len(names) >= 2 else "",
        "participants_raw": participants,
        # Subscription identifiers for WS workers.
        "moneyline_market_slugs": extract_moneyline_slugs(event),
        "asset_identifiers": extract_asset_identifiers(event),
        # Status at discovery.
        "live_at_discovery": bool(event.get("live")),
        "active_at_discovery": bool(event.get("active")),
        # Provenance.
        "discovered_at": poll_ts,
    }
