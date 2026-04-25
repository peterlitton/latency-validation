# Session 4.2 Handoff — Latency & Validation Study

**Date closed:** 2026-04-24
**Operator:** Peter Litton
**Repo:** https://github.com/peterlitton/latency-validation
**Render service:** srv-d7kekf77f7vs738r4igg (Standard tier, 50 GB disk)
**Mac dev env:** ~/latency-validation/ with venv, JupyterLab, local_archive

---

## 1. Background

### Project
14-day observation-only measurement study comparing API-Tennis WebSocket vs Polymarket Sports/Markets WebSocket feeds for live tennis. Three data sources captured continuously to per-match archives:

1. **API-Tennis WS** — game state (point/game/set/match transitions)
2. **Polymarket Markets WS `subscribe_market_data`** — CLOB order book deltas
3. **Polymarket Markets WS `subscribe_trades`** — trade executions

All routing into canonical `match_id` directories: `{tournament-slug}_{player-a-slug}_{player-b-slug}_{YYYY-MM-DD}`.

### Phase status at session 4.2 close
- **Phase 1-4:** complete
- **Phase 5 v1:** complete (this session)
- **Phase 6:** running autonomously (14-day measurement window through ~May 7)
- **Phase 7:** scheduled post-trial

### Architecture rules (operational)
- **Render container:** capture-only. NO analysis workloads. Established commit 14.
- **Mac:** all Phase 4-7 analysis. `~/latency-validation/local_archive/` synced via `refresh-archive` alias.
- **GitHub:** source of truth. Mac is a working copy. Operator ships via drag-drop on GitHub web UI, not `git push`.

### Key data quirks to remember
- API-Tennis player names are initials-dot-surname (`M. Trungelliti`); Polymarket has full names. Cross-feed match identity uses manual `event_key → match_id` overrides in `cross_feed_overrides.yaml`.
- API-Tennis `event_live="1"` does NOT mean live — must check `event_status not in {"Finished", "Retired", "Cancelled"}`.
- Polymarket emits no game-state events. Only `market_data` and `trade`.
- `_unresolved/` events are recoverable at Phase 7 via event_key join; not lost.
- Mid-match override addition loses prior history. Operator owns timely curation.

---

## 2. Work completed this session (4.2)

Two commits: 14 (incident root-cause) and 15 (session close).

### Commit 14 — OOM incident closure (log-only)
- Diagnosed 6 instance failures 13:49–13:57 UTC 2026-04-24 (read-only Render dashboard, no Shell)
- Root cause: in-container Phase 4 calibration on Ostapenko/Waltert (~23.5k records) competing with capture service for 2 GB budget. Two memory spikes to ~50/55%, self-resolved 14:00 UTC
- **Operational rule established:** no analysis on Render. Mac-only.
- Standing risk "Render service memory / crash loop" CLOSED
- Capture continued through incident with ~1-2 min gaps per restart cycle (degraded, not lost — flagged for Phase 7)

### Commit 15 — Session 4.2 close
Four threads:

**Thread A: 8 new overrides — ABANDONED.** Edits to `pair_overrides_batch2.py` never reached GitHub before matches finished. `_unresolved/` join at Phase 7 will recover the data via event_key.

**Thread B: Loaders streaming rewrite — SKIPPED.** Investigation showed `normalize.build_unified_stream` materializes a sorted list (the actual memory ceiling), so streaming loaders alone solves nothing. Full streaming would require external sort. Mac has plenty of RAM. Decision: don't rewrite. Revisit only if Phase 7 hits a ceiling.

**Thread C: Phase 5 v1 dashboard — DELIVERED.** New `notebooks/phase_5_dashboard.ipynb`. Plotly per-match timeline with bid/ask step lines, trade markers, AP status transitions on a single time axis. Validated against Bittoun-Kouzmine vs Chazal (Challenger Abidjan 2026-04-23): 4858 bid points, 4894 ask points, 178 trade markers, 2 status transitions. Chart renders sensibly. Phase 5 v1 AC: met.

**Thread D: Polymarket trade extractor bug — FIXED.** Bug shipped in commit 11 (session 4.1), surfaced by Phase 5 dashboard showing `trade markers: 0` despite 178 trade records in archive. Schema mismatch:
- Old: `trade.px`, `trade.qty`, `trade.transactTime || trade.time` — none exist
- New: `trade.price`, `trade.quantity` (both nested `{value, currency}`, handled by `_extract_px`), `trade.tradeTime`
- Edit applied via terminal heredoc to `code/analysis/normalize.py`. After kernel restart, trade count went 0 → 178.

### Files modified this session (Mac-local)
1. `code/analysis/normalize.py` — `normalize_polymarket_trade` extractor fixed
2. `notebooks/phase_5_dashboard.ipynb` — NEW file (~6.6 KB, 7 cells)
3. `log/working_log.md` — commits 14 + 15 appended (full file rendered as `working_log.md` in this session's outputs, 909 lines, ready to drag-drop replace on GitHub)

### Notebook preamble fix worth remembering
Cell 1 originally used `sys.path.insert(0, '')` which didn't reliably shadow Python's stdlib `code` module (interactive interpreter helpers). Fixed to absolute path:
```python
import sys
sys.path.insert(0, '/Users/PeterLitton/latency-validation')
for mod_name in list(sys.modules.keys()):
    if mod_name == 'code' or mod_name.startswith('code.'):
        del sys.modules[mod_name]
```
Same workaround pattern as session 4.1's smoke-test cell, but the absolute path is more reliable than empty-string. Long-term cleanup deferred (rename `code/` directory or add `pyproject.toml`).

---

## 3. Outstanding — drag-drop queue for next session

Three Mac-local files not yet on GitHub. Drag-drop on GitHub web UI:

1. **`code/analysis/normalize.py`** — trade extractor fix (Mac path: `~/latency-validation/code/analysis/normalize.py`)
2. **`notebooks/phase_5_dashboard.ipynb`** — new file (Mac path: `~/latency-validation/notebooks/phase_5_dashboard.ipynb`)
3. **`log/working_log.md`** — full replace with the 909-line version rendered this session

Operator preferred to wait until next session for the drag-drop. No urgency since Mac and Render are independent and the capture service doesn't read these files.

---

## 4. Considered next steps (session 5.x)

Listed roughly in suggested order. Operator picks priorities at session open.

### Immediate operational
- **Drag-drop the three queued files to GitHub.** Clean baseline before any new work.
- **Sync Mac to GitHub.** `cd ~/latency-validation && git pull` to make sure Mac matches whatever's on GitHub before editing further. (Note: if Mac has uncommitted edits — which it does, the normalize.py fix — pull may complain. Either commit/stash first or do the drag-drop first so GitHub matches Mac.)

### Phase 5 v2 polish (UI-driven)
Operator described v1 UI as "not great" but functional. Possible improvements:
- **Legend behavior with empty traces.** Plotly hides traces with zero data points by default. The trade-bug diagnosis was harder because of this. Force legend visibility for all four traces even when empty.
- **Axis gridlines.** Currently dense; consider hourly major + 10-min minor for typical match length.
- **Transition labels readable.** y=1.08 triangles work but the hover-only label is awkward. Consider always-visible labels or a separate annotation row.
- **Scoreboard overlay.** Show current score + server based on `ap_event_status` / pointbypoint at any point on the timeline.
- **Multi-match selector.** Currently MATCH_ID is a hardcoded constant in cell 4. Replace with a dropdown reading match list from `local_archive/matches/`.
- **Latency annotations.** Per AP transition, annotate the time-to-first-PM-response (overlaps with `phase_4_calibration.reconcile_boundaries` logic — could pull and reuse).

### Phase 7 prep
- **Maker/taker UnifiedEvent fields.** Trade payload includes maker/taker blocks (side, intent, outcome, action, taker username). Add fields to `UnifiedEvent` dataclass for Phase 7 directional analysis. Schema decision: nest under `pm_trade_maker_*`/`pm_trade_taker_*` prefixes following existing convention.
- **Empirical-probe-first checklist for new extractors.** This session's trade extractor bug was the fourth Polymarket schema-assumption bug. Codify the rule: any new extractor field is probed against ≥1 real payload from archive before committing.

### Other Phase 5 ideas (operator decision)
- **Re-run Phase 4 calibration on a fuller-overlap match** (any of the six early-pairings from commit 13). Abidjan smoke-test only had 7.28 min overlap. Better data point for Q2/Q3 jitter expectations. Not blocking — Phase 4 AC already closed.
- **Headless notebook execution via `jupyter nbconvert --execute`** for batch-rendering the dashboard across all completed matches. Useful for Phase 7 review.

### Standing items unchanged
- Plan §4 / §6 language revision queued (low urgency, cosmetic — describes "Sports WS / CLOB WS" as separate endpoints when SDK reality is one MarketsWebSocket with three subscription types).
- Bug #4 (reconnect-when-empty) parked. Cosmetic.
- `code/` package shadow workaround in notebooks. Workaround improved this session (absolute path); structural fix (rename directory or pyproject.toml) still deferred.
- Diagnostic streaming rewrite (capture-layer, OLD) deferred post-Phase-7.

---

## 5. Standing risks status

| Risk | Status |
|---|---|
| Render service memory / crash loop | CLOSED (commit 14) |
| Render tier / disk | closed (Standard, 50 GB) |
| Archive pruning | closed |
| Diagnostic streaming rewrite (capture-layer) | deferred post-Phase-7 |
| Loaders streaming rewrite (analysis-layer) | deliberately skipped commit 15 |
| Bug #4 (reconnect-when-empty) | cosmetic, parked |
| Plan §4 / §6 language revision | queued, low urgency |
| `code` package import hack in notebooks | workaround improved; cleanup pending |

---

## 6. Operator preferences to carry forward

Surfaced or reinforced this session:

1. **UTC throughout** in working log and analysis output
2. **Drag-drop to GitHub web UI**, not `git push`. GitHub is source of truth.
3. **Skip work that doesn't serve research questions.** Default to simplest option.
4. **Read modules before drafting code.** Empirical-probe-first.
5. **Imperative, terse instructions.** Don't push back unless actually blocked. ("Apply fix, restart, ship if X.")
6. **Will paste assistant command blocks verbatim** — avoid inline shell comments that could be parsed as args. Prefer Python heredoc over sed for file edits (fewer escaping pitfalls).
7. **Editor preference:** TextEdit unfamiliar/risky (smart quotes break .py). Terminal heredoc is path of least resistance.
8. **JupyterLab vocabulary needed coaching** this session — terms like "cell" and the run workflow (Shift+Enter, Run All Cells) were initially unfamiliar. Explain UI mechanics step-by-step when needed.
9. **Ship-fast over deep-investigation** when output looks reasonable.
10. **Prose questions in chat, not interactive widgets.**

---

## 7. Reference paths

```
~/latency-validation/                   # Mac dev root
├── code/
│   ├── analysis/
│   │   ├── loaders.py                  # 130 lines, list-based, NOT streaming
│   │   ├── normalize.py                # 206 lines, MODIFIED this session
│   │   ├── reconcile.py                # 275 lines, untouched
│   │   └── phase_4_calibration.py     # 281 lines, untouched
│   └── capture/                        # capture workers
├── notebooks/
│   └── phase_5_dashboard.ipynb         # NEW this session
├── log/
│   └── working_log.md                  # 909 lines after this session's update
├── local_archive/                      # rsync of /data/archive on Render
│   ├── matches/                        # per-match meta.json + discovery_delta
│   ├── api_tennis/                     # API-Tennis WS events per match
│   ├── polymarket_sports/              # Polymarket events per match
│   └── cross_feed_overrides.yaml       # 9 entries currently active
└── .venv/                              # Python 3.12 venv

/data/archive/                          # Render persistent disk (capture-only)
```

Daily Mac workflow:
```bash
cd ~/latency-validation
source .venv/bin/activate
refresh-archive                         # rsync from Render
jupyter lab notebooks/phase_5_dashboard.ipynb
```

---

## 8. Cross-session context

- **9 active overrides** in cross_feed_overrides.yaml on Render
- **Latest GitHub commits:** 68e6d73 (session 4.1 carry-overs) + commit 14 (log-only OOM closure)
- **API-Tennis trial expires** ~May 7 → triggers Phase 7
- **Memory baseline** post-commit-14: 5-10% of 2 GB on Render (healthy)

End of handoff.
