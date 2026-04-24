"""Unified common-schema representation across all three sources.

Phase 4 AC deliverable: `normalization into common-schema view across
the three sources`. This module defines `UnifiedEvent` and the three
per-source extractors that produce it.

Design notes:

- Timestamp: `arrived_at_ms` is capture-host wall-clock at message
  receipt. We trust this as the common time axis for Phase 4
  reconciliation. NTP verification (session 4.1) confirmed clock is
  within ±10 ms of reference.

- Source-specific fields use prefixes:
    `ap_*` for API-Tennis
    `pm_*` for Polymarket (whether market_data or trade)
  Fields are None when not applicable to the record's source. This
  keeps the schema flat and analyzable without variant types while
  still being typed.

- `raw` preserves the full original payload for Phase 7 access. The
  extracted fields are for convenience, not truth — anything the
  extractors don't capture is still available via `raw`.

- Bids/offers from Polymarket market_data are arrays of price levels.
  Best bid = first bid by convention; best ask = first offer. Both can
  be empty on thin markets (we've seen offers=[] on heavily-bid books).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SOURCE_API_TENNIS = "api_tennis"
SOURCE_PM_MARKET_DATA = "polymarket_market_data"
SOURCE_PM_TRADE = "polymarket_trade"


@dataclass
class UnifiedEvent:
    """One row in the cross-source unified event stream."""

    arrived_at_ms: int
    source: str
    match_id: str
    event_type: str  # source-native type, kept verbatim

    # API-Tennis fields
    ap_event_status: str | None = None
    ap_score: str | None = None  # set-level, e.g. "1 - 2"
    ap_game_result: str | None = None  # current game, e.g. "30 - 40"
    ap_server: str | None = None  # "First Player" / "Second Player" / None
    ap_winner: str | None = None  # set when match ends
    ap_final_result: str | None = None  # full set tally

    # Polymarket fields (market_data and trade both use pm_ prefix)
    pm_best_bid_px: float | None = None
    pm_best_ask_px: float | None = None
    pm_last_trade_px: float | None = None
    pm_market_state: str | None = None  # MARKET_STATE_OPEN, etc.
    pm_notional_traded: float | None = None
    pm_trade_qty: float | None = None  # trade events only
    pm_trade_px: float | None = None  # trade events only
    pm_transact_time: str | None = None  # Polymarket-side timestamp, ISO

    # Original payload for Phase 7 access
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def arrived_at_iso(self) -> str:
        """Convenience ISO representation of arrived_at_ms."""
        from datetime import UTC, datetime
        return datetime.fromtimestamp(
            self.arrived_at_ms / 1000.0, tz=UTC
        ).isoformat(timespec="milliseconds")


def _coerce_price(v: Any) -> float | None:
    """Parse Polymarket price strings like '0.990' into floats.

    Polymarket stringifies numerics in the API. Tolerates None and
    already-numeric input.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _extract_px(px_obj: Any) -> float | None:
    """Pull the numeric price out of a `{"value": "0.990", "currency": "USD"}`
    nested dict. Returns None if shape is off."""
    if not isinstance(px_obj, dict):
        return None
    return _coerce_price(px_obj.get("value"))


def normalize_api_tennis(record: dict[str, Any]) -> UnifiedEvent:
    """Build UnifiedEvent from one api_tennis archive record."""
    raw = record.get("raw") or {}
    return UnifiedEvent(
        arrived_at_ms=int(record["arrived_at_ms"]),
        source=SOURCE_API_TENNIS,
        match_id=record.get("match_id", "_unresolved"),
        event_type=raw.get("event_status") or "api_tennis_update",
        ap_event_status=raw.get("event_status"),
        ap_score=raw.get("event_final_result"),
        ap_game_result=raw.get("event_game_result"),
        ap_server=raw.get("event_serve"),
        ap_winner=raw.get("event_winner"),
        ap_final_result=raw.get("event_final_result"),
        raw=raw,
    )


def normalize_polymarket_market_data(
    record: dict[str, Any],
) -> UnifiedEvent:
    """Build UnifiedEvent from one polymarket market_data record."""
    raw = record.get("raw") or {}
    market_data = raw.get("marketData") or {}
    bids = market_data.get("bids") or []
    offers = market_data.get("offers") or []
    stats = market_data.get("stats") or {}

    best_bid = _extract_px(bids[0].get("px")) if bids else None
    best_ask = _extract_px(offers[0].get("px")) if offers else None

    return UnifiedEvent(
        arrived_at_ms=int(record["arrived_at_ms"]),
        source=SOURCE_PM_MARKET_DATA,
        match_id=record.get("match_id", "_unresolved"),
        event_type="market_data",
        pm_best_bid_px=best_bid,
        pm_best_ask_px=best_ask,
        pm_last_trade_px=_extract_px(stats.get("lastTradePx")),
        pm_market_state=market_data.get("state"),
        pm_notional_traded=_extract_px(stats.get("notionalTraded")),
        pm_transact_time=market_data.get("transactTime"),
        raw=raw,
    )


def normalize_polymarket_trade(record: dict[str, Any]) -> UnifiedEvent:
    """Build UnifiedEvent from one polymarket trade record.

    Polymarket trade payload shape varies slightly from market_data. The
    `trade` object has direct price/qty fields rather than an order-book
    array. Extractor pulls those plus any market-state context if
    present in the payload envelope.
    """
    raw = record.get("raw") or {}
    trade = raw.get("trade") or {}

    return UnifiedEvent(
        arrived_at_ms=int(record["arrived_at_ms"]),
        source=SOURCE_PM_TRADE,
        match_id=record.get("match_id", "_unresolved"),
        event_type="trade",
        pm_trade_px=_extract_px(trade.get("px")),
        pm_trade_qty=_coerce_price(trade.get("qty")),
        pm_transact_time=trade.get("transactTime") or trade.get("time"),
        raw=raw,
    )


def normalize_polymarket_record(
    record: dict[str, Any],
) -> UnifiedEvent | None:
    """Dispatch polymarket record by event_name. Returns None on unknown."""
    event_name = record.get("event_name")
    if event_name == "market_data":
        return normalize_polymarket_market_data(record)
    if event_name == "trade":
        return normalize_polymarket_trade(record)
    return None


def build_unified_stream(
    api_tennis_records: list[dict[str, Any]],
    polymarket_records: list[dict[str, Any]],
) -> list[UnifiedEvent]:
    """Normalize all records from both feeds and return a single
    arrived_at_ms-sorted stream.

    api_tennis_records can come from either the routed match directory
    or from _unresolved (joined by event_key upstream in loaders).
    polymarket_records come from polymarket_sports/{match_id}/.
    """
    events: list[UnifiedEvent] = []
    for r in api_tennis_records:
        events.append(normalize_api_tennis(r))
    for r in polymarket_records:
        ue = normalize_polymarket_record(r)
        if ue is not None:
            events.append(ue)
    events.sort(key=lambda e: e.arrived_at_ms)
    return events
