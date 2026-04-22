# Findings — Latency & Validation Study, v1

Structured around the four research questions. Evidence accumulates as matches are captured during Phase 6 (measurement window). Substantive write-up is Phase 7.

Each question gets: a headline number or distribution, a chart, and a paragraph explaining method and interpretation.

Framing: comparison and validation, not competition. A null result (sources agree, no material lag, fast CLOB reaction) is a valid and informative outcome.

---

## Summary

*[Written in Phase 7. One paragraph. Headline answers to Q1–Q4.]*

---

## Q1 — Agreement

**Question.** Does API-Tennis agree with Polymarket's Sports WS at game and point boundaries within an acceptable delta?

**Threshold.** "Acceptable" is defined after Phase 4 calibration once empirical jitter is visible. Preliminary jitter sense recorded in the working log during Phase 4.

**Method.** *[Phase 7: describe event-pairing approach, how disagreements are counted, how ambiguous matches are handled.]*

**Result.** *[Phase 7: distribution, chart, headline.]*

**Interpretation.** *[Phase 7: what the result means. Agreement is confidence; disagreement is itself a finding.]*

---

## Q2 — Lag

**Question.** Does Polymarket's Sports WS lag API-Tennis materially?

**Framing.** "Material" is framed relative to the delta a trading strategy would need to exploit it. This study reports the distribution, not a single number.

**Method.** *[Phase 7: describe how paired events are timestamped, which timestamp is treated as ground truth for each source, handling of events present in only one source.]*

**Result.** *[Phase 7: distribution of (Polymarket Sports WS arrival) − (API-Tennis arrival) per paired event. Chart.]*

**Interpretation.** *[Phase 7.]*

---

## Q3 — CLOB reaction time

**Question.** Once a game boundary is known (per whichever source reports it first), how long does the CLOB take to re-price?

**Noise-floor treatment.** Chosen in Phase 7 against real data. Options:
- Raw distribution: first subsequent CLOB best-bid or best-ask change after earliest game-boundary event.
- Price-move filtered: only CLOB changes exceeding a minimum price-move threshold.
- Causality filtered: CLOB changes consistent with game-boundary causation.

*[Phase 7: record which treatment was chosen, why, and what the alternatives considered would have shown.]*

**Method.** *[Phase 7.]*

**Result.** *[Phase 7.]*

**Interpretation.** *[Phase 7. Acknowledge that CLOB quotes move for reasons unrelated to game boundaries.]*

---

## Q4 — Reliability

**Question.** How reliable is each source — drop rates, late events, explicit errors, reconnect frequency?

**Metrics.**
- Drop rate: events expected but missing (e.g., missing games in a reconciled match sequence).
- Late events: events arriving out of order or after the next-sequence event.
- Errors: explicit error payloads or connection failures.
- Reconnect frequency: worker reconnect count per match or per session.

**Method.** *[Phase 7.]*

**Result.** *[Phase 7: per-source table of reliability metrics.]*

**Interpretation.** *[Phase 7.]*

---

## Caveats and limitations

*[Phase 7: clock-skew residuals documented in Phase 4, match-identity resolution edge cases, any capture gaps from unobserved worker deaths, calendar-induced sample bias (which tournaments the 14-day window covered), anything else that qualifies the headlines.]*

---

## PM-Tennis v5 implications

*[Phase 7: findings relevant to PM-Tennis v5 are added to PM-Tennis's `pm_tennis_v5_ideas.md`, not duplicated here. This section lists what was added there, with a one-line rationale each.]*
