# PM-Tennis v4 Awareness — Findings from Latency & Validation Study

**Source:** Latency & Validation Study v1, sessions 2.x – 4.x (April 22-24, 2026)
**Audience:** PM-Tennis next session Claude, and operator
**Purpose:** Surface findings from the sibling latency study that may affect PM-Tennis v4 capture-layer correctness or §4.x signal-model assumptions
**Status:** Informational — operator decides whether/when to action

---

## Why this document exists

The Latency & Validation Study built capture infrastructure against the same Polymarket US Markets WebSocket and the same API-Tennis WebSocket that PM-Tennis interacts with (or will interact with). In doing so, the latency study made empirical observations about the actual API surface that diverge from documented or assumed shapes. Several of these observations are directly relevant to PM-Tennis v4's capture and signal-qualification layers.

This document covers six findings, two of which are potentially load-bearing for PM-Tennis v4 §4.x correctness. The other four are awareness items.

The latency study has now delivered:
- Phase 3 (three-source capture) — closed
- Phase 4 (calibration on completed match) — closed
- Phase 5 v1 (per-match Plotly dashboard) — closed

The findings below have all been validated against real captured archive data, not just documentation review.

---

## Finding 1 — Polymarket Markets WebSocket emits only two event types

**Severity: HIGH for PM-Tennis v4 §4.2 signal model**

PM-Tennis v4 §4.2 describes a game-level signal model anchored on game-boundary state transitions, with the state tuple `(sets_won_a, sets_won_b, games_won_a, games_won_b, server)`. The plan states the signal model operates on "Sports WebSocket emits game-boundary transitions only," referencing the H-005 finding.

**Empirical reality:** The Polymarket US `MarketsWebSocket` (the only Polymarket WebSocket exposed by the `polymarket-us` SDK as of v0.1.2) emits exactly two event types:

- `market_data` — order book deltas (best bid, best ask, depth)
- `trade` — executed trades

Across more than 25,000 captured events on more than 30 distinct matches over multiple hours of capture, no other event types were observed. No `heartbeat`, no game-state events, no session-lifecycle events, no set/game/match transition signals.

**The plan's "Sports WS" doesn't exist as a separate endpoint.** What session 2.2 called "Sports WS" is the same `MarketsWebSocket` Polymarket exposes. The SDK has three subscription methods (`subscribe_market_data`, `subscribe_market_data_lite`, `subscribe_trades`), all of which feed into the same WebSocket connection. Game-state events are not among the available subscriptions.

**Implication for PM-Tennis v4:**

The signal model in §4.2 cannot derive its game-boundary state tuple from Polymarket alone. Game state must come from a separate source — the natural candidate is API-Tennis (which the latency study integrates and which does emit game-boundary events).

If PM-Tennis v4's plan currently assumes Polymarket emits game-state events, that assumption is wrong. Two paths forward:

1. **Add API-Tennis as PM-Tennis's game-state source.** Subscribe to API-Tennis WebSocket for game/set/match transitions. Use Polymarket only for order book and trade execution data. Latency study can share its API-Tennis worker code (`code/capture/api_tennis_ws.py`).
2. **Infer game state from market activity.** Watch market_data for price movements characteristic of game boundaries (e.g., resolution price approaching 0 or 1, market closing). Less reliable, more inference, but no second data source dependency.

Path 1 is cleaner and directly serves the signal model as designed. Path 2 introduces inference noise into a signal that's supposed to be empirical.

**Recommended action for PM-Tennis next session:**

Surface this to operator before resuming Phase 3 (or wherever PM-Tennis is in its build). Don't proceed on the assumption that Polymarket emits game state. Verify the actual data source for PM-Tennis's signal model.

---

## Finding 2 — Polymarket trade payload field paths

**Severity: HIGH for PM-Tennis v4 §4.4 signal qualification**

PM-Tennis v4 §4.4 specifies that signal qualification requires recent `last_trade_price` activity from the trades stream:

> A `last_trade_price` event must be present in the CLOB stream within 30 seconds preceding the signal, indicating aggressive flow is present rather than pure maker repositioning.

This filter is described as essential for distinguishing real mispricings from market-maker repositioning artifacts of the Maker Rebates Program.

**Empirical reality from latency study session 4.2 (commit 15):**

The actual Polymarket `trade` event payload structure is:

```json
{
  "trade": {
    "marketSlug": "...",
    "price": {"value": "0.330", "currency": "USD"},
    "quantity": {"value": "44.000", "currency": "USD"},
    "tradeTime": "2026-04-23T18:45:05.068622283Z",
    "maker": {
      "side": "ORDER_SIDE_BUY",
      "intent": "...",
      "outcomeSide": "...",
      "action": "..."
    },
    "taker": {
      "username": "...",
      "side": "ORDER_SIDE_SELL",
      "intent": "ORDER_INTENT_SELL_LONG",
      "outcomeSide": "OUTCOME_SIDE_YES",
      "action": "ORDER_ACTION_SELL"
    }
  }
}
```

Three things to note:

1. **Field names are `price`, `quantity`, `tradeTime`** — not `px`, `qty`, `transactTime` or `time` as the latency study's initial extractor assumed (and as which may be in PM-Tennis docs/comments if any exist).
2. **Price and quantity are nested objects** with `{value, currency}` shape — not flat strings or numbers. Extracting requires `trade.price.value` not just `trade.price`.
3. **Timestamp field is `tradeTime`** — ISO-8601 with nanosecond precision and UTC `Z` suffix.

**The latency study's commit 15 fixed exactly this bug** in its `normalize_polymarket_trade` extractor. The bug had shipped in commit 11 of session 4.1 and was undetected because Phase 4 calibration only counted records by source — never probed trade price values. Phase 5 dashboard surfaced it: `trade markers: 0` despite 178 trade records in the archive.

**Implication for PM-Tennis v4:**

If PM-Tennis v4's `last_trade_price` filter is implemented or planned against the assumed-but-wrong field shape, every signal qualification check will fail silently — the filter will see zero recent trades and either reject all signals or pass all signals depending on the default behavior. Either way, the filter would not function as designed.

**Recommended action for PM-Tennis next session:**

1. Verify PM-Tennis's trade-stream extractor against this known-correct shape before any signal-qualification testing.
2. Probe a real captured Polymarket trade payload before writing the extractor — never trust documented field names.
3. Use `trade.price.value` and `trade.quantity.value` (parse to float) and `trade.tradeTime` for the timestamp.

The latency study's `code/analysis/normalize.py` `normalize_polymarket_trade` function is a reference implementation.

**Bonus opportunity:**

The `maker`/`taker` blocks in the payload contain side and intent information that's potentially valuable for PM-Tennis's signal model. Specifically, `taker.side` (`ORDER_SIDE_BUY` vs `ORDER_SIDE_SELL`) tells you whether the trade was buyer-aggressive or seller-aggressive — directly relevant to the §4.4 "aggressive flow" filter. The latency study currently captures this in `raw` but does not surface it in the `UnifiedEvent` schema; v2 work.

---

## Finding 3 — Empirical-probe-first discipline for new extractors

**Severity: MEDIUM (process recommendation)**

Across the latency study sessions, the same pattern appeared at least four times: extractor or filter written against an assumed payload shape, bug undetected until something downstream actually used the extracted values, fix required only after diagnostic probing of the real payload.

The pattern:
- Session 2.2: three Polymarket schema-assumption bugs (event_name set, event_live string semantics, market_data shape)
- Session 2.2: participant-shape bug (TEAM-typed dispatch latent until WTA matches surfaced)
- Session 4.2: trade extractor field paths (Finding 2 above)

**Recommended discipline (now standing rule in the latency study):**

Before writing any new extractor or filter against a Polymarket or API-Tennis payload field:

1. Capture or pull at least one real payload sample from the archive
2. Print or log the actual field structure
3. Write the extractor against that empirical sample, not against documentation or convention
4. Test the extractor by running it against archive data and verifying non-null outputs

This applies to PM-Tennis as it does to the latency study. Documentation alone is insufficient; documented field names have been wrong in every case the latency study has checked.

---

## Finding 4 — Render disk and capture costs

**Severity: LOW (operational awareness)**

The latency study found that capture-layer disk usage scales meaningfully:

- API-Tennis: ~480 MB/day under typical Madrid match density (5-8 concurrent matches with multi-message-per-tick payloads)
- Polymarket market_data + trade: ~60 MB/day
- Combined: ~150-300 MB/day across three sources, observed at ~480 MB/day under heavier load

The 14-day measurement window may accumulate 3-7 GB of archive data depending on tournament density. Rounded up for safety: 10 GB minimum, 50 GB for full headroom.

PM-Tennis's storage requirements may differ depending on whether it captures all sources or just Polymarket. If PM-Tennis runs on Render Standard tier (10 GB default disk), monitor disk consumption against projected window length.

**Specific incident worth knowing about (session 2.2):**

Initial Render Starter tier (512 MB RAM, 1 GB disk) was insufficient for sustained capture. The capture service hit OOM repeatedly and disk filled in days. Standard tier (2 GB RAM) plus a disk bump to 50 GB resolved both. Cost: ~$27.50/month.

---

## Finding 5 — In-container analysis OOM risk

**Severity: LOW (operational rule)**

Session 4.2 had an OOM crash-loop incident on the Render service. Root cause: Phase 4 calibration scripts run via Render Shell loaded ~24,000 records into memory in the same container as the live capture service. The combined footprint exceeded the 2 GB limit.

Diagnosed via Render Metrics memory graph: baseline flat at ~100-200 MB for 8+ hours pre-incident, two discrete spikes during incident window reaching ~1.0-1.1 GB, baseline returned post-incident.

**Operational rule added to the latency study (commit 14):**

No analysis workloads run on the Render container. All analysis work happens on a Mac (or other local) environment against a synced copy of the archive. Render container is capture-only.

**Implication for PM-Tennis:**

If PM-Tennis runs analysis or backtesting on the same container as live capture, the same OOM pattern can occur. Mitigation: separate analysis from capture by container, or move analysis to local environment.

---

## Finding 6 — Cross-feed match identity reconciliation

**Severity: LOW (workflow awareness)**

Polymarket and API-Tennis use different match identifiers and different player name conventions. Polymarket uses canonical match_ids of form `{tournament}_{player_a_slug}_{player_b_slug}_{date}`. API-Tennis uses integer `event_key` and initial-dot-surname player naming.

The latency study uses a `cross_feed_overrides.yaml` file mapping `event_key` (int) → `match_id` (str). Operator-curated as matches appear, no fuzzy matching.

PM-Tennis would face the same reconciliation problem if it uses both feeds. The latency study has a working reference implementation in `code/capture/cross_feed.py` and a documented operator workflow.

**Operational lesson from session 4.1:**

Add overrides at match discovery, not mid-match. Mid-match overrides lose all prior API-Tennis history (events arriving before override addition land in `_unresolved/` and require post-hoc recovery via event_key join).

---

## Summary table

| Finding | Severity | Category | Action |
|---|---|---|---|
| 1. Polymarket emits no game-state events | HIGH | §4.2 signal model | Verify before resuming Phase 3 |
| 2. Trade payload field paths | HIGH | §4.4 signal qualification | Verify extractor against known-correct shape |
| 3. Empirical-probe-first discipline | MEDIUM | Process | Adopt for any new extractor work |
| 4. Render disk and capture costs | LOW | Infrastructure | Awareness for tier sizing |
| 5. In-container analysis OOM | LOW | Operational | Don't run analysis in capture container |
| 6. Cross-feed match identity | LOW | Workflow | Reference latency study's cross_feed.py if dual-source |

---

## What this document does not do

- Does not prescribe specific PM-Tennis v4 plan revisions
- Does not assume PM-Tennis is at any particular phase
- Does not require any immediate operator action
- Does not modify PM-Tennis files

This is informational handoff between two parallel studies. PM-Tennis next session reads this, decides what's relevant to current PM-Tennis state, and acts accordingly.

---

## Reference paths in latency-validation repo

For PM-Tennis sessions wanting to read the latency study's reference implementations:

- `code/capture/api_tennis_ws.py` — API-Tennis WebSocket worker
- `code/capture/cross_feed.py` — Cross-feed override resolution
- `code/analysis/normalize.py` — `normalize_polymarket_trade` function (corrected extractor)
- `notebooks/phase_5_dashboard.ipynb` — Phase 5 minimal dashboard
- `log/working_log.md` — Full session history including all empirical probes and bug diagnoses

Repository public at github.com/peterlitton/latency-validation.

---

**End of findings document.**
