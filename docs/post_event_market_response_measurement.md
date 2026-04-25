# Post-Event Market Response Measurement

**Status:** Working note. Identifies the measurement problem, lays out candidate definitions, and names tradeoffs. Project placement TBD.

**Author context:** Originated from spinoff-design discussion 2026-04-25. Relevant to latency study Phase 7 analysis (Q3 CLOB reaction time), to any over-vs-under-reaction analysis on captured market data, and to live-trading instrument design that needs a real-time read of where the market has settled.

---

## 1. The problem

Given an event at time `T_event` (a point boundary, game boundary, break point, set transition, etc.), the market price was at `P_pre` just before the event. After `T_event`, the price moves. Sometimes monotonically toward a new equilibrium. Often noisily — bids and asks updating independently, market makers requoting, sparse trades firing at varying prices.

We need an operational definition of "the post-event market response price" — call it `P_post` — so that statements like "the market over-reacted to this event" or "the market under-reacted" or "the CLOB took N seconds to reprice" are measurable consistently across events.

The price doesn't announce when it has finished responding. There is no moment where the order book says "settled." Any definition of `P_post` is a chosen convention, and different conventions have different tradeoffs.

The same problem appears in two distinct contexts that may want different conventions:

**Measurement context.** For analytical use (Phase 7 of the latency study, retrospective over-vs-under-reaction analysis, edge characterization) the goal is rigorous and consistent classification across hundreds or thousands of events. Excluding ambiguous events with a flag is acceptable.

**Trading context.** For live decision support (an instrument used at the moment of trade entry or exit), the goal is the best available real-time read of where the market is heading. Excluding events isn't possible — every event you trade off has to be classified somehow, even if classification is uncertain. Also, you typically can't wait the full settling time before acting.

These contexts may use the same underlying data but probably want different operational definitions.

## 2. Candidate definitions for `P_post`

Six candidates, ordered roughly from simplest to most adaptive.

### 2.1 Mid-price snapshot at fixed delay

Take the bid-ask midpoint at exactly `T_event + Δ` for some chosen `Δ`. Common choices: 5 seconds, 30 seconds, 2 minutes.

**Advantages:**
- Trivially simple to implement and explain.
- Consistent across events — the same `Δ` applies to all.
- No ambiguity about when the measurement is taken.
- Easy to compute multiple variants (5s, 30s, 2min) and compare.

**Disadvantages:**
- `Δ` is arbitrary. There is no principled basis for choosing 5s over 30s.
- The right `Δ` varies by event type. A break point may reprice within seconds; a set transition may take longer because more fair-value parameters change.
- A single snapshot is sensitive to micro-noise. The bid or ask could happen to flicker at the chosen instant, biasing the measurement.
- Does not adapt to the size of the event. Big events with substantial repricing get measured the same way as small events with marginal repricing.

### 2.2 Volume-weighted price across a window (VWAP)

Take the volume-weighted average price across `[T_event, T_event + W]` for some window `W`. Weighted by trade volume, not by quote updates.

**Advantages:**
- Less sensitive to single-tick noise than a snapshot.
- Captures where trades actually happened, which is closer to "where the market thinks fair value is" than where idle bids and asks happened to sit.
- Naturally averages over short-term oscillation within the window.

**Disadvantages:**
- Trades are sparse on tennis markets — latency study found median ~9.7 seconds between trades. A short window may contain zero or one trades, making VWAP meaningless or noisy.
- A single trade in a sleepy window dominates the VWAP entirely, defeating the noise-reduction goal.
- Ignores quote movement, which is itself information about where the market is heading.
- Window `W` is arbitrary, same as `Δ` above.
- Susceptible to a single large trade skewing the result if a market participant happens to fire at an off-equilibrium price within the window.

### 2.3 Settling-time detection via variance threshold

Define `P_post` as the bid-ask midpoint at the moment when rolling variance over a short window drops below a chosen threshold — i.e., the price has stopped moving.

**Advantages:**
- Adaptive to event size. Big events take longer to settle; small events settle quickly. The measurement waits as long as needed.
- Captures something close to the intuitive notion of "the market has finished responding."
- Doesn't require pre-specifying a `Δ` or `W`.

**Disadvantages:**
- "Variance below threshold" requires a threshold, which is itself an arbitrary tuning parameter. You'd be tuning against your own data.
- For events that never settle cleanly (volatile match phases, ongoing speculation), the detection never fires and you have no measurement.
- Computationally heavier — must track a rolling statistic and check it continuously.
- Variance over what window? Choosing the rolling-window length introduces another parameter.
- Susceptible to false-positive settling during temporary lulls in activity, before the price moves further.

### 2.4 Bid-ask spread normalization

Take `P_post` as the bid-ask midpoint at the moment the post-event spread returns to the pre-event spread (or to the typical spread for that match).

**Advantages:**
- Captures the market-maker uncertainty signal directly. Right after an event, market makers widen spreads because they don't yet know fair value. Spread compression is the market makers signaling they have figured it out.
- Adaptive to event type without explicit tuning. Bigger events generate wider initial spreads and longer compression times.
- Computationally cheaper than variance-based detection.
- Has an intuitive interpretation that lines up with what experienced traders watch.

**Disadvantages:**
- Some events don't materially widen the spread. For these, the criterion fires immediately and the measurement is essentially a snapshot at `T_event`.
- "Returns to pre-event spread" is itself ambiguous when pre-event spread was already varying. Returns to within X percent? Returns to a moving average?
- Market-maker behavior varies across matches. Spread normalization on a heavily-quoted Madrid Open match looks different from a Challenger with thin quoting.
- Doesn't directly measure where the price has gone — only that uncertainty has resolved. The price reading at the moment of normalization may itself still be moving.

### 2.5 First stable trade cluster

Wait for trades to fire post-event. When N consecutive trades cluster within a tight price band, take the median as `P_post`.

**Advantages:**
- Trade-driven rather than quote-driven. Trades represent actual market consensus more strongly than quote updates do.
- Robust to quote-side noise (algorithmic requoting, wash quoting).

**Disadvantages:**
- Trades are sparse. Median ~9.7s between trades on tennis markets. Waiting for N=3 or N=5 clustered trades could take minutes, by which time additional events may have occurred and confounded the measurement.
- "Tight band" requires a width parameter.
- Many events will have zero post-event trades within any reasonable window, especially small events on lightly-traded matches. Measurement becomes impossible for these.
- Highly sensitive to which traders are active — a single algorithmic trader doing repeated small fills could dominate the cluster.

### 2.6 Dual condition: spread normalized AND price stable

Define `P_post` as the bid-ask midpoint at the first moment after `T_event` where two conditions hold simultaneously: (a) the spread is within a small multiple of the pre-event spread (e.g., 1.5x), and (b) the price has stayed within a tight band for at least N consecutive seconds (e.g., 10s).

**Advantages:**
- Combines the strengths of spread-normalization and stability detection.
- Filters out single-tick noise (the N-second hold period) and market-maker uncertainty (the spread requirement) simultaneously.
- Adaptive to event type — bigger events take longer to satisfy both conditions.
- For events where the conditions never resolve within a reasonable cap (say 5 minutes), the event is excluded from the measurement set with a flag, which is the right behavior for measurement-context use.

**Disadvantages:**
- More parameters to choose and tune than simpler definitions (spread multiple, stability band, hold duration, max-time cap).
- Computationally more involved than a fixed-delay snapshot.
- Flagged-as-unsettled exclusions may bias the measurement set if exclusion correlates with event characteristics.
- Doesn't address the trading-context need — by the time both conditions are satisfied, the trading opportunity has likely passed.

## 3. Tradeoffs and recommendations by context

### 3.1 Measurement context (Phase 7 analysis, retrospective characterization)

The measurement context can afford rigor, can exclude ambiguous events, and benefits from event-type-aware tuning if data justifies it.

**Recommended starting point:** Definition 2.6 (dual condition). The combination of spread normalization and price stability handles different event types automatically and excludes events that don't settle within a reasonable cap.

**Tuning parameters to set during Phase 7:**
- Spread multiple (initial guess: 1.5x pre-event spread)
- Stability band width (initial guess: 1¢ for prices < 0.20, 2-3¢ for mid-range prices, scaled to typical contract micro-volatility)
- Stability hold duration (initial guess: 10 seconds)
- Max time cap before excluding event (initial guess: 5 minutes)

**Event-type-specific tuning:** Worth investigating after first pass. If small events (within-game points) systematically settle faster than large events (set transitions, break points), tuning per event type will reduce bias.

**Cross-checking:** Compute Definition 2.1 (fixed-delay snapshots at 5s, 30s, 2min) alongside Definition 2.6 results for sanity. If they diverge wildly on most events, something is wrong with one or both. If they converge, Definition 2.1 may be acceptable as a simpler proxy.

### 3.2 Trading context (real-time decision support)

The trading context can't wait for full settling and can't exclude events. Operator judgment fills the gaps that mechanical classification would otherwise close.

**Recommended starting point:** Display multiple readings simultaneously rather than committing to a single definition.

A glanceable panel would show:
- 5-second mid-price (fast, noisy)
- 30-second VWAP (slower, smoother)
- 2-minute mid-price (slow, likely settled if anything will settle)
- Whether the 30s and 2min readings agree (visual indicator of convergence)
- Current spread vs. pre-event spread (visual indicator of remaining market-maker uncertainty)

The operator looks at the panel and forms judgment about where the price has actually settled. The instrument doesn't classify; it surfaces the data that classification would use.

**Migration path to model-driven trading recommendations:** After accumulating empirical data on settling times by event type and price range during measurement-context analysis, the trading-context display can be supplemented with predicted settling times ("based on this event type, expected settling within N seconds"). Eventually, automated classification with confidence levels.

## 4. Connection to over-reaction vs under-reaction analysis

Once `P_post` is defined consistently, over- and under-reaction analysis becomes:

- Compute `F_pre` = fair value implied by score state immediately before event
- Compute `F_post` = fair value implied by score state immediately after event
- Compute `ΔF` = `F_post` - `F_pre` (the fair-value change from the event)
- Compute `ΔP` = `P_post` - `P_pre` (the actual market price change)
- Over-reaction: `|ΔP| > |ΔF|` (market moved more than fair value warranted)
- Under-reaction: `|ΔP| < |ΔF|` (market moved less than fair value warranted)
- Reaction ratio: `ΔP / ΔF` (a single number characterizing the reaction)

The fair-value computation uses the Sackmann tables (or equivalent score-state-conditional probability data) joined with the pre-match handicap, computed in log-odds space and converted back to probability.

The measurement framework above produces the `P_post` term. The fair-value computation produces the `F_post` term. Together they enable systematic over-vs-under-reaction characterization across captured events.

This is a Phase 7 analysis target for the latency study, and it's what a trading instrument would surface live to support decisions about whether a current price reflects an over- or under-reaction.

## 5. Open questions and unresolved tuning

These items are flagged for resolution against real data rather than chosen up front:

- Whether event-type-specific tuning is necessary or whether a single set of parameters works across event types.
- The right scaling of stability-band width with contract price (linear? piecewise? based on observed micro-volatility?).
- How to handle events where two genuine events occur in rapid succession before the first has settled (game ends, break point begins immediately on next game).
- Whether `F_pre` and `F_post` should be computed using the same Sackmann lookup or whether the pre-match handicap should be re-derived from the running market state.
- Whether to use bid, ask, mid, or last-trade price as the basis for the `P` series. Mid is the default but trades may carry more signal.

These are tractable empirical questions once enough events have been captured.

## 6. Where this document goes

Project placement decision pending. Candidates:

- PM-Tennis project documentation, alongside the fair-price model section (relevant if v4 continues and incorporates over-vs-under-reaction analysis).
- Latency study findings or methods documentation (directly applicable to Phase 7 Q3 analysis).
- A spinoff project's design document (if the spinoff explicitly takes on real-time market response measurement as part of its instrument scope).
- Standalone methods note that multiple projects can reference.

Recommendation: file as a standalone methods note in the relevant repo (or in both repos as a cross-reference), since the underlying measurement problem is the same regardless of which project is consuming the result.

---

**End of working note.**
