"""Phase 4 reconciliation checks against the unified event stream.

Each function takes a UnifiedEvent list and returns a structured result
for reporting. Functions are pure — no printing, no disk writes. The
phase_4_calibration entrypoint calls them and formats output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

from .normalize import (
    SOURCE_API_TENNIS,
    SOURCE_PM_MARKET_DATA,
    SOURCE_PM_TRADE,
    UnifiedEvent,
)


# ---------------------------------------------------------------------
# Time spans per source
# ---------------------------------------------------------------------


@dataclass
class SourceSpan:
    source: str
    count: int
    first_ms: int | None
    last_ms: int | None

    @property
    def span_minutes(self) -> float:
        if self.first_ms is None or self.last_ms is None:
            return 0.0
        return (self.last_ms - self.first_ms) / 1000.0 / 60.0


def compute_source_spans(events: list[UnifiedEvent]) -> list[SourceSpan]:
    """Per-source count + first/last arrived_at_ms."""
    sources = [SOURCE_API_TENNIS, SOURCE_PM_MARKET_DATA, SOURCE_PM_TRADE]
    out: list[SourceSpan] = []
    for src in sources:
        src_events = [e for e in events if e.source == src]
        if not src_events:
            out.append(SourceSpan(source=src, count=0, first_ms=None, last_ms=None))
            continue
        first = src_events[0].arrived_at_ms
        last = src_events[-1].arrived_at_ms
        # events are pre-sorted by arrived_at_ms at stream build time,
        # so per-source first/last is first/last of filtered slice.
        out.append(
            SourceSpan(
                source=src,
                count=len(src_events),
                first_ms=first,
                last_ms=last,
            )
        )
    return out


def compute_overlap_window(
    spans: list[SourceSpan],
) -> tuple[int | None, int | None, float]:
    """Intersection of time spans across all non-empty sources.

    Returns (overlap_start_ms, overlap_end_ms, overlap_minutes). If any
    source has zero records, returns (None, None, 0.0).
    """
    non_empty = [s for s in spans if s.count > 0 and s.first_ms is not None]
    if len(non_empty) < 2:
        return None, None, 0.0
    start = max(s.first_ms for s in non_empty)
    end = min(s.last_ms for s in non_empty)
    if end < start:
        return start, end, 0.0
    return start, end, (end - start) / 1000.0 / 60.0


# ---------------------------------------------------------------------
# Silent-drop check
# ---------------------------------------------------------------------


@dataclass
class GapFinding:
    source: str
    gap_ms: int
    at_ms: int  # arrived_at_ms of the record AFTER the gap
    median_gap_ms: float
    ratio_to_median: float


def find_large_gaps(
    events: list[UnifiedEvent],
    source: str,
    ratio_threshold: float = 10.0,
) -> tuple[list[GapFinding], float]:
    """Find inter-arrival gaps > ratio_threshold × median gap for a source.

    Returns (findings, median_gap_ms). A finding doesn't prove a silent
    drop — it just flags a cadence anomaly for operator review. Normal
    quiet periods (market sparse between games) will produce large gaps
    too. Phase 4 AC is "manual verification," not automatic pass/fail.
    """
    src_events = [e for e in events if e.source == source]
    if len(src_events) < 3:
        return [], 0.0

    gaps = [
        src_events[i].arrived_at_ms - src_events[i - 1].arrived_at_ms
        for i in range(1, len(src_events))
    ]
    med = median(gaps)
    if med <= 0:
        # Degenerate: many records at same ms, can't usefully compute ratio.
        return [], float(med)

    threshold_ms = ratio_threshold * med
    findings: list[GapFinding] = []
    for i, gap in enumerate(gaps, start=1):
        if gap > threshold_ms:
            findings.append(
                GapFinding(
                    source=source,
                    gap_ms=gap,
                    at_ms=src_events[i].arrived_at_ms,
                    median_gap_ms=float(med),
                    ratio_to_median=gap / med,
                )
            )
    return findings, float(med)


# ---------------------------------------------------------------------
# Game-boundary reconciliation (API-Tennis → Polymarket)
# ---------------------------------------------------------------------


@dataclass
class BoundaryMatch:
    """One API-Tennis status transition with nearest Polymarket response."""

    transition: str  # e.g. "Set 1 -> Set 2", "Set 2 -> Finished"
    ap_at_ms: int
    pm_response_at_ms: int | None  # first market_data within window, or None
    pm_delta_ms: int | None  # pm_response - ap, signed
    pm_px_at_response: float | None  # pm_last_trade_px at response
    pm_px_before: float | None  # pm_last_trade_px just before ap transition
    within_window: bool


def find_status_transitions(
    events: list[UnifiedEvent],
) -> list[tuple[int, str, str]]:
    """Detect API-Tennis event_status changes over time.

    Returns list of (arrived_at_ms, prev_status, new_status). First
    observed status is also emitted with prev_status="" to mark the
    capture-start state. Status transitions are the game boundaries
    we reconcile against Polymarket price action.
    """
    out: list[tuple[int, str, str]] = []
    last_status: str | None = None
    for e in events:
        if e.source != SOURCE_API_TENNIS:
            continue
        status = e.ap_event_status or ""
        if status != last_status:
            out.append((e.arrived_at_ms, last_status or "", status))
            last_status = status
    return out


def reconcile_boundaries(
    events: list[UnifiedEvent],
    window_ms: int = 30_000,
) -> list[BoundaryMatch]:
    """Match each API-Tennis status transition to nearest Polymarket
    market_data within +/- window_ms.

    Why market_data and not trade: market_data fires on every book
    update, much denser signal. Phase 7 decides whether Q3 uses
    quote-based or trade-based reaction times; Phase 4 calibration
    just shows the alignment works.
    """
    transitions = find_status_transitions(events)
    pm_md = [e for e in events if e.source == SOURCE_PM_MARKET_DATA]

    out: list[BoundaryMatch] = []
    for ap_ms, prev, new in transitions:
        label = f"{prev or '(start)'} -> {new}"
        # Price state before transition: last market_data strictly before ap_ms
        before = [e for e in pm_md if e.arrived_at_ms < ap_ms]
        pm_px_before = (
            before[-1].pm_last_trade_px if before else None
        )
        # First market_data at or after transition, within window
        after = [
            e
            for e in pm_md
            if ap_ms <= e.arrived_at_ms <= ap_ms + window_ms
        ]
        if after:
            first_after = after[0]
            out.append(
                BoundaryMatch(
                    transition=label,
                    ap_at_ms=ap_ms,
                    pm_response_at_ms=first_after.arrived_at_ms,
                    pm_delta_ms=first_after.arrived_at_ms - ap_ms,
                    pm_px_at_response=first_after.pm_last_trade_px,
                    pm_px_before=pm_px_before,
                    within_window=True,
                )
            )
        else:
            # No Polymarket activity within +window. Still record the
            # transition for visibility — quiet periods happen.
            out.append(
                BoundaryMatch(
                    transition=label,
                    ap_at_ms=ap_ms,
                    pm_response_at_ms=None,
                    pm_delta_ms=None,
                    pm_px_at_response=None,
                    pm_px_before=pm_px_before,
                    within_window=False,
                )
            )
    return out


# ---------------------------------------------------------------------
# Match identity resolution check
# ---------------------------------------------------------------------


@dataclass
class IdentityCheck:
    expected_match_id: str
    mismatches: list[tuple[str, str]] = field(default_factory=list)
    # (source, observed_match_id) tuples for any records not matching

    @property
    def passed(self) -> bool:
        return not self.mismatches


def verify_match_identity(
    events: list[UnifiedEvent],
    expected_match_id: str,
) -> IdentityCheck:
    """Confirm every unified event carries the expected match_id.

    API-Tennis records recovered from _unresolved will have
    match_id='_unresolved' — those are expected and NOT counted as
    mismatches here (the whole point of recovery is that we assert
    their identity via event_key join, not via match_id field).
    Mismatches here would mean a record routed to the wrong match dir,
    which would be a real bug.
    """
    ck = IdentityCheck(expected_match_id=expected_match_id)
    for e in events:
        mid = e.match_id
        if mid == expected_match_id:
            continue
        if mid == "_unresolved" and e.source == SOURCE_API_TENNIS:
            # Allowed — recovered via event_key, not match_id.
            continue
        ck.mismatches.append((e.source, mid))
    return ck
