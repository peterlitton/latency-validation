"""Phase 4 Calibration — main entrypoint.

Runs all AC checks for one match and prints a plain-text report.
Designed to be run from Render Shell:

    python -m code.analysis.phase_4_calibration \\
        --match-id challenger-abidjan_constantin-bittoun-kouzmine_maxime-chazal_2026-04-23

Optional flags:
    --date 2026-04-23           (defaults to today UTC)
    --archive-root /data/archive (defaults to production path)
    --no-recover-unresolved     (skip the event_key recovery from _unresolved)
    --gap-ratio 10              (threshold for silent-drop flagging)
    --window-sec 30             (search window for game-boundary reconciliation)

Output is intentionally verbose and self-contained — the full run can
be pasted back into the working log as Phase 4 evidence.

Phase 4 AC coverage in this script:
- Normalization into common-schema view: build_unified_stream()
- Silent-drop check: find_large_gaps() per source
- Manual reconciliation of game boundaries: reconcile_boundaries()
- Match identity resolution held: verify_match_identity()
- NTP clock verification: NOT in this script — runs separately on
  Render Shell; output recorded in working log.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from . import loaders
from .normalize import (
    SOURCE_API_TENNIS,
    SOURCE_PM_MARKET_DATA,
    SOURCE_PM_TRADE,
    build_unified_stream,
)
from .reconcile import (
    compute_overlap_window,
    compute_source_spans,
    find_large_gaps,
    reconcile_boundaries,
    verify_match_identity,
)


def _ms_to_iso(ms: int | None) -> str:
    if ms is None:
        return "(none)"
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat(
        timespec="milliseconds"
    )


def _fmt_px(v: float | None) -> str:
    return "-" if v is None else f"{v:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 4 calibration report for one match."
    )
    parser.add_argument("--match-id", required=True)
    parser.add_argument(
        "--date",
        default=datetime.now(UTC).strftime("%Y-%m-%d"),
        help="YYYY-MM-DD, defaults to today UTC",
    )
    parser.add_argument(
        "--archive-root", default=str(loaders.DEFAULT_ARCHIVE_ROOT)
    )
    parser.add_argument(
        "--no-recover-unresolved",
        action="store_true",
        help="Skip pulling api_tennis records from _unresolved/",
    )
    parser.add_argument("--gap-ratio", type=float, default=10.0)
    parser.add_argument("--window-sec", type=int, default=30)
    args = parser.parse_args()

    archive = Path(args.archive_root)
    match_id = args.match_id
    date_str = args.date

    print("=" * 72)
    print(f"Phase 4 Calibration Report")
    print("=" * 72)
    print(f"match_id:     {match_id}")
    print(f"date:         {date_str}")
    print(f"archive_root: {archive}")
    print()

    # ---------------------------------------------------------------
    # 1. Meta + discovery-delta
    # ---------------------------------------------------------------
    print("-" * 72)
    print("1. MATCH METADATA")
    print("-" * 72)
    meta = loaders.load_meta(match_id, archive_root=archive)
    if not meta:
        print(f"  FAIL: no meta.json found for match_id={match_id}")
        return
    print(f"  tournament_name:  {meta.get('tournament_name')}")
    print(f"  round:            {meta.get('round')}")
    print(f"  event_date:       {meta.get('event_date')}")
    print(f"  start_date_iso:   {meta.get('start_date_iso')}")
    print(f"  player_a:         {meta.get('player_a_name')}")
    print(f"  player_b:         {meta.get('player_b_name')}")
    print(f"  resolution:       {meta.get('resolution_status')}")
    print(f"  moneyline_slugs:  {meta.get('moneyline_market_slugs')}")

    dd = loaders.load_discovery_delta(match_id, archive_root=archive)
    print(f"  discovery_delta records: {len(dd)}")
    print()

    # ---------------------------------------------------------------
    # 2. Load raw records from all sources
    # ---------------------------------------------------------------
    print("-" * 72)
    print("2. RAW RECORDS LOADED")
    print("-" * 72)
    pm_records = loaders.load_polymarket_sports(
        match_id, date_str, archive_root=archive
    )
    ap_routed = loaders.load_api_tennis_routed(
        match_id, date_str, archive_root=archive
    )
    print(f"  polymarket_sports (market_data + trade): {len(pm_records)}")
    print(f"  api_tennis routed:                       {len(ap_routed)}")

    # Gather event_keys seen in routed records so we know what to
    # recover from _unresolved.
    routed_event_keys = set()
    for r in ap_routed:
        ek = r.get("event_key") or (r.get("raw") or {}).get("event_key")
        if isinstance(ek, int):
            routed_event_keys.add(ek)
    # Fallback: if routed is empty, try to learn event_keys from the
    # matches/ meta.json — not currently stored there for API-Tennis,
    # so in practice --no-recover-unresolved is needed when routed=0
    # AND operator hasn't provided event_key hints. Common path: at
    # least one routed record exists, giving us the event_key.

    ap_recovered: list = []
    if not args.no_recover_unresolved and routed_event_keys:
        ap_recovered = loaders.recover_api_tennis_unresolved(
            routed_event_keys, date_str, archive_root=archive
        )
        print(
            f"  api_tennis recovered from _unresolved "
            f"(event_keys={sorted(routed_event_keys)}): {len(ap_recovered)}"
        )
    elif args.no_recover_unresolved:
        print("  api_tennis recovered from _unresolved: SKIPPED (--no-recover-unresolved)")
    else:
        print(
            "  api_tennis recovered from _unresolved: SKIPPED (no event_keys from routed)"
        )

    all_api_tennis = ap_routed + ap_recovered
    print()

    # ---------------------------------------------------------------
    # 3. Build unified stream
    # ---------------------------------------------------------------
    print("-" * 72)
    print("3. UNIFIED STREAM")
    print("-" * 72)
    unified = build_unified_stream(all_api_tennis, pm_records)
    print(f"  total unified events: {len(unified)}")
    spans = compute_source_spans(unified)
    print()
    print(f"  {'source':<30} {'count':>8} {'first (UTC)':<30} {'last (UTC)':<30} {'span (min)':>10}")
    for s in spans:
        print(
            f"  {s.source:<30} {s.count:>8} "
            f"{_ms_to_iso(s.first_ms):<30} "
            f"{_ms_to_iso(s.last_ms):<30} "
            f"{s.span_minutes:>10.2f}"
        )

    overlap_start, overlap_end, overlap_min = compute_overlap_window(spans)
    print()
    print(f"  cross-source overlap window:")
    print(f"    start: {_ms_to_iso(overlap_start)}")
    print(f"    end:   {_ms_to_iso(overlap_end)}")
    print(f"    duration: {overlap_min:.2f} min")
    print()

    # ---------------------------------------------------------------
    # 4. Silent-drop check (gap analysis)
    # ---------------------------------------------------------------
    print("-" * 72)
    print("4. SILENT-DROP CHECK (inter-arrival gaps)")
    print("-" * 72)
    print(f"  threshold: gap > {args.gap_ratio}x per-source median")
    print()
    for src in [SOURCE_API_TENNIS, SOURCE_PM_MARKET_DATA, SOURCE_PM_TRADE]:
        findings, med = find_large_gaps(unified, src, args.gap_ratio)
        print(f"  {src}: median gap = {med:.0f} ms, large gaps = {len(findings)}")
        for f in findings[:10]:
            print(
                f"    at {_ms_to_iso(f.at_ms)}: "
                f"gap={f.gap_ms} ms ({f.ratio_to_median:.1f}x median)"
            )
        if len(findings) > 10:
            print(f"    ... and {len(findings) - 10} more")
    print()

    # ---------------------------------------------------------------
    # 5. Game-boundary reconciliation
    # ---------------------------------------------------------------
    print("-" * 72)
    print("5. GAME-BOUNDARY RECONCILIATION (API-Tennis → Polymarket)")
    print("-" * 72)
    boundaries = reconcile_boundaries(
        unified, window_ms=args.window_sec * 1000
    )
    print(
        f"  status transitions: {len(boundaries)} "
        f"(search window: +{args.window_sec}s)"
    )
    print()
    header = (
        f"  {'transition':<30} {'ap at (UTC)':<30} "
        f"{'pm delta (ms)':>14} {'px before':>10} {'px at resp':>11}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for b in boundaries:
        delta_str = "(none in window)" if b.pm_delta_ms is None else f"{b.pm_delta_ms:+d}"
        print(
            f"  {b.transition:<30} {_ms_to_iso(b.ap_at_ms):<30} "
            f"{delta_str:>14} "
            f"{_fmt_px(b.pm_px_before):>10} "
            f"{_fmt_px(b.pm_px_at_response):>11}"
        )
    print()

    # ---------------------------------------------------------------
    # 6. Match identity resolution
    # ---------------------------------------------------------------
    print("-" * 72)
    print("6. MATCH IDENTITY RESOLUTION")
    print("-" * 72)
    ck = verify_match_identity(unified, match_id)
    if ck.passed:
        print(f"  PASS: all {len(unified)} unified records carry the expected")
        print(f"  match_id (or are api_tennis recovered-from-_unresolved).")
    else:
        print(f"  FAIL: {len(ck.mismatches)} records carry unexpected match_id")
        for src, mid in ck.mismatches[:10]:
            print(f"    source={src} observed_match_id={mid}")
        if len(ck.mismatches) > 10:
            print(f"    ... and {len(ck.mismatches) - 10} more")
    print()

    # ---------------------------------------------------------------
    # 7. Summary
    # ---------------------------------------------------------------
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  match_id:                  {match_id}")
    print(f"  sources with data:         {sum(1 for s in spans if s.count > 0)} / 3")
    print(f"  cross-source overlap:      {overlap_min:.2f} min")
    print(f"  boundary transitions:      {len(boundaries)}")
    print(
        f"  transitions with PM resp:  "
        f"{sum(1 for b in boundaries if b.within_window)} / {len(boundaries)}"
    )
    print(f"  identity check:            {'PASS' if ck.passed else 'FAIL'}")
    print()
    print("NTP verification runs separately — see working log for clock offset evidence.")


if __name__ == "__main__":
    main()
