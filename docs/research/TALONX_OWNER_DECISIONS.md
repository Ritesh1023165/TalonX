# TalonX Owner Decisions

**Status: DRAFT — produced by Task 32 (2026-08-21).** A compact, human-readable decision form for the
product owner. Every `OWNER ANSWER` field below is deliberately left blank (`PENDING`) because no actual
human owner instruction exists yet — Claude has not answered on the owner's behalf anywhere in this
document. Recommendations are labeled as recommendations, never as decisions. Once the owner fills in an
answer, update this document (do not delete the question/evidence context — append the answer and change
Status) and propagate the resolution to `docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md`.

Full supporting analysis for every item below lives in `results/task32_owner_decision_capture/` (built on
`results/task31_owner_specification/`, not re-derived).

---

## FREQ-001 — Opportunity-Frequency Objective

**Question**: What operating category should govern TalonX's expected signal/trade frequency —
`RARE_HIGH_CONVICTION`, `REGULAR_OPPORTUNITY`, `ACTIVE_INTRADAY`, or a `CUSTOM` range?

**Why it matters**: blocks determining whether the current extreme selectivity (26 trades/year) is a problem
to fix or a correct design outcome — without this, no future gate-loosening OR gate-tightening decision can
be evaluated against anything.

**Verified current behavior**: 26 executed trades/year across 10 symbols (~2.6/symbol-year), ~9.9% of
trading days with a long entry, 5/10 symbols zero trades all year; 35-symbol live day: 52 candidates, 0
published (consistent with, not an outlier from, the historical rate, per Task 27).

**Options**: `RARE_HIGH_CONVICTION` (many zero-signal days, occasional setups, strongest filtering) /
`REGULAR_OPPORTUNITY` (meaningful weekly opportunities, broad watchlist expected to materially increase
aggregate flow) / `ACTIVE_INTRADAY` (frequent setups — not supported by any evidence, would represent a
mission change) / `CUSTOM`.

**Evidence**: no historical numeric target exists anywhere in this project (Task 30's exhaustive search).
Every reactive design decision in this project's history reduced frequency, never increased it. The
50+-symbol watchlist engineering investment (commit `7b7d815`) is the strongest evidence AGAINST
`RARE_HIGH_CONVICTION` being the deliberate original target, even though it's the closest match to CURRENT
measured output.

**Claude recommendation**: none offered — this is the one decision Task 30/31/32 deliberately refuse to
default, since the evidence is genuinely split between two defensible categories and any default here would
functionally become the missing historical requirement by fiat.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## CONF-001 — Confluence Philosophy

**Question**: What should confluence mean as a product requirement —
`TRIGGER_PLUS_ONE_CONFIRMATION` (A), `TWO_CONFIRMATIONS_EXCLUDING_TRIGGER` (B),
`MULTI_INDICATOR_SAME_BAR_CONSENSUS` (C), `RANKING_ONLY` (D), or `CUSTOM` (E)?

**Why it matters**: blocks any confluence-rule experiment (component weighting, threshold value, per-family
self-credit changes).

**Verified current behavior**: RSI curl gets automatic credit via its bundled volume requirement, needs 1
more (almost always MACD). MACD gets automatic credit via its own cross, needs 1 more 91.9% of the time.
MA crossover gets zero automatic credit, needs 2 of the other 3 legs.

**Options and alignment**: A matches RSI-curl and MACD's current behavior, not MA's. B/C match MA's current
behavior, not RSI-curl's or MACD's. D matches none of the three (confluence is a hard gate today, not a
ranking input). E allows the owner to declare intentional per-family asymmetry.

**Evidence**: full option/alignment matrix in `results/task32_owner_decision_capture/confluence_decision.md`.

**Claude recommendation**: A (`TRIGGER_PLUS_ONE_CONFIRMATION`) — matches 2 of 3 families exactly as
currently implemented (the smallest gap between stated policy and actual behavior of any option), and
matches the plain reading of the confluence gate's own reactive origin story (Task 24/27/28). This is a
recommendation only — not adopted as fact anywhere in this document.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## SIG-001 — Signal-Family Independence: RSI Reversal

**Question**: Should RSI reversal be `INDEPENDENT_PUBLISHABLE_SETUP`, `CANDIDATE_REQUIRING_CONFIRMATION`,
`CONTEXT_ONLY`, or `CUSTOM`?

**Why it matters**: blocks RSI-family-specific gate/confluence redesign.

**Verified current behavior**: cannot publish without a same-bar MACD cross in practice (Task 28's confirmed
structural self-exclusion of its own RSI confluence leg).

**Evidence**: `results/task32_owner_decision_capture/signal_family_decision.csv` (row SIG-001).

**Claude recommendation**: `CANDIDATE_REQUIRING_CONFIRMATION` (B) — formalizes existing behavior exactly, no
code change implied. Recommendation only.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## SIG-002 — Signal-Family Independence: MACD Crossover

**Question**: Same options as SIG-001, applied to MACD crossover.

**Why it matters**: blocks MACD-family-specific gate/confluence redesign.

**Verified current behavior**: closest of the three families to independently publishable (own cross
auto-credits), but still fails confluence 91.9% of the time absent a coincident factor.

**Evidence**: `results/task32_owner_decision_capture/signal_family_decision.csv` (row SIG-002).

**Claude recommendation**: `CANDIDATE_REQUIRING_CONFIRMATION` (B), for consistency with SIG-001/SIG-003 —
though this family has the strongest case of the three for `INDEPENDENT_PUBLISHABLE_SETUP` if the owner
wants to treat families asymmetrically (permitted under E in CONF-001). Recommendation only.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## SIG-003 — Signal-Family Independence: MA Crossover

**Question**: Same options as SIG-001, applied to MA crossover.

**Why it matters**: blocks MA-family-specific gate/confluence redesign, including whether a future task
should add a dedicated MA self-credit leg to the confluence formula.

**Verified current behavior**: purely a candidate generator today — zero self-credit, needs 2 of the other 3
legs.

**Evidence**: `results/task32_owner_decision_capture/signal_family_decision.csv` (row SIG-003).

**Claude recommendation**: `CANDIDATE_REQUIRING_CONFIRMATION` (B) — already matches current implementation
exactly, no change implied. Recommendation only.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## ATR-REGIME-001 — ATR-USE-1 (min_atr_pct) Semantic Intent

**Question**: What market property is `min_atr_pct` supposed to represent — current short-term (1-minute)
volatility as implemented, a slower intraday volatility regime, or a daily volatility regime?

**Why it matters**: blocks any volatility-filter redesign; determines whether the 0.25% default (calibrated
to a 1-minute reading) is measuring the right concept at all.

**Verified current behavior**: `ATR(14, 1-minute bars) / price >= 0.25%`, internally coherent math,
numerically consistent only with a 1-minute-scale interpretation (a daily interpretation would make 0.25%
an almost non-restrictive floor).

**Options**: `SHORT_TERM_INTRADAY_ATR` (matches current) / `SLOWER_INTRADAY_ATR` / `DAILY_ATR` /
`MULTI_TIMEFRAME` / `CUSTOM`.

**Evidence**: `results/task32_owner_decision_capture/atr_use_case_decisions.csv` (row ATR-REGIME-001),
`results/task31_owner_specification/atr_semantics_matrix.csv`.

**Claude recommendation**: none offered — classified `REQUIREMENT_AMBIGUOUS` with no historical evidence
resolving which was intended; both readings are legitimate designs for an intraday scanner.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## ATR-TRIGGER-001 — ATR-USE-2 (atr_move_multiplier) Semantic Intent

**Question**: Does the owner accept the current 1-minute-scale trigger-movement comparison
(`bar_true_range(1-min) >= atr_move_multiplier x ATR(14, 1-min)`)?

**Why it matters**: blocks ATR-move-gate calibration experiments (though this is the lowest-risk of the
three ATR decisions).

**Verified current behavior**: both sides of the comparison are the same timeframe by construction.

**Evidence**: classified `SEMANTICALLY_COHERENT` in Task 31 — the trigger bar being evaluated IS a 1-minute
bar, so a same-scale ATR comparison is definitionally sound regardless of what's decided for the other two
uses.

**Claude recommendation**: `SHORT_TERM_INTRADAY_ATR` (i.e., accept current behavior as-is) — the one ATR
recommendation with the highest confidence of the three, since no plausible alternative timeframe would be
more conceptually correct for this specific use case. Recommendation only, not yet owner-accepted.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## ATR-RISK-001 — ATR-USE-3 (Stop/Target Geometry) Semantic Intent

**Question**: What risk model should govern stop distance and the ATR-fallback target —
`SHORT_TERM_INTRADAY_ATR` (current), `SLOWER_INTRADAY_ATR`, `DAILY_ATR`, `MARKET_STRUCTURE_PRIMARY`,
`MULTI_TIMEFRAME_RISK_MODEL`, or `CUSTOM`?

**Why it matters**: **the highest-priority open ATR decision.** Blocks any stop-geometry experiment and any
future canonical baseline re-run (a baseline must be re-established after any geometry change before OOS
evaluation).

**Verified current behavior**: `stop = 1.5 x ATR(14, 1-minute bars)`; ATR-fallback target
`= 2.0 x ATR(14, 1-minute bars)` (pre-pivot-warmup only).

**Options with trade-offs**: full detail in `results/task32_owner_decision_capture/atr_risk_model_options.
md` (options A-F).

**Evidence**: classified `TIMEFRAME_MISMATCH` hypothesis (not proven, not an implementation defect) — a
1.5x-of-1-minute-ATR stop is plausibly too tight for the confirmed minutes-to-hours holding horizon, and is
CONSISTENT WITH (not proven to cause) Task 26's observed exit-timing asymmetry: STOP-exit median holding
time ~4 minutes vs. TARGET/EOD-exit medians of ~14 minutes / ~2.6 hours.

**Claude recommendation**: none offered — per explicit instruction not to default to `DAILY_ATR` merely
because that is the conventional TA reading of "ATR 14," and not to select any other option without owner
input on intended trade horizon philosophy. All six options remain open.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## COST-001 — Cost-Tolerance / Execution-Cost Model

**Question**: What execution environment should TalonX's cost-tolerance requirement be defined against, and
in what format (`ROUND_TRIP_BPS` / `PER_SIDE_BPS_PLUS_FEES` / `EMPIRICAL_FILL_MODEL`)?

**Why it matters**: blocks any deployability conclusion about the current or any future canonical baseline.

**Verified current behavior**: `talonx_paper` simulates a 5bps spread, no commission (assumes a
commission-free retail broker, unnamed); `talonx_backtest`'s cost-sensitivity grid tests 0/5/10/20 bps as a
fixed, non-calibrated testing tool, never as a stated requirement.

**Evidence**: `results/task32_owner_decision_capture/execution_environment_questions.md` (8 unresolved
sub-questions), `cost_model_decision.md`. Task 26's own cost-sensitivity result, retained strictly as
evidence, not as a threshold-selection input: 0bps +4.29R, 5bps -4.64R, 10bps -13.56R, 20bps -31.41R —
implying only `CURRENT_CANONICAL_EDGE_NOT_COST_ROBUST_UNDER_TESTED_ASSUMPTIONS`, nothing about what tolerance
SHOULD be required.

**Claude recommendation**: none offered on the specific bps number (explicitly out of scope — "do NOT choose
a cost threshold from Task26"). No format recommendation offered either, since it depends on unresolved
execution-environment answers.

**OWNER ANSWER**: PENDING

**Status**: OPEN

---

## Revision history

v0.1 (DRAFT) — created by Task 32, 2026-08-21. Not yet committed/pushed, pending review — see
`docs/research/TALONX_RESEARCH_LEDGER.md`'s Task 32 entry for the corresponding checkpoint SHA.
