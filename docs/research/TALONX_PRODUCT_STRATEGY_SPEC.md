# TalonX Product & Strategy Specification

**Status: v0.3 — core specification CONFIRMED by explicit owner decision (Task 33, 2026-08-21).** This
document is the product-level strategy authority for TalonX. Every section below is marked with one of five
markers:

- **CONFIRMED** — an existing, verified requirement, an already-implemented/tested behavior, or a
  conceptual requirement explicitly answered by the product owner (`VERIFIED_FACT`, `EXISTING_REQUIREMENT`,
  or `OWNER_CONFIRMED` in the underlying traceability tables). Not reopened without contradictory evidence
  or a new owner decision.
- **CONFIRMED (concept) / RESEARCH_REQUIRED (implementation)** — the owner has answered WHAT is intended;
  engineering/measurement work remains to determine HOW to implement it safely. This is not an open owner
  decision — see `results/task33_owner_spec_finalization/specification_status.md` for why this distinction
  matters.
- **PROVISIONAL** — a Claude recommendation not yet addressed by the owner. Not to be treated as decided.
- **OWNER_DECISION_PENDING** — a genuinely open question with no recommended default, not yet answered.
- **TECHNICAL_CONSTRAINT** — a fact about the system's current limits (e.g., an unresolved verification gap)
  that is not an owner decision at all.

Nothing in this document changes production code, thresholds, or gate order — it is a specification, not an
implementation. It does not stand alone — each section links to its full supporting analysis in
`results/task31_owner_specification/`, `results/task32_owner_decision_capture/`, and
`results/task33_owner_spec_finalization/`, which should be read for complete evidence and reasoning. **All 9
priority owner decisions (FREQ-001, CONF-001, SIG-001/002/003, ATR-TRIGGER-001, ATR-REGIME-001, ATR-RISK-001,
COST-001) have now been answered explicitly by the product owner** — see
`docs/research/TALONX_OWNER_DECISIONS.md` for the verbatim answers and their implementation-alignment
consequences.

---

## 1. Product identity — **CONFIRMED**

> TalonX is a high-precision but REGULAR intraday opportunity scanner over a broad, liquid-equity watchlist
> (50+ symbols targeted). It prioritizes quality over raw frequency but is intended to surface a useful
> recurring flow of opportunities across the full watchlist — a few good opportunities per week, not a
> guaranteed daily quota. It is not intended to generate multiple trades every day, and it is not
> intentionally designed as an ultra-rare scanner. Zero-signal days are acceptable. It opens only long
> positions, uses bearish signals as exits from an existing long (never as new short entries), and closes
> all exposure intraday (no overnight positions).

Confirmed directly by the owner's FREQ-001 answer (`REGULAR_OPPORTUNITY`), which supersedes Task 31's
provisional "high-precision... prioritizes quality over frequency" wording — the qualitative frequency intent
is now part of the canonical identity statement itself, not a separate open question. No numeric weekly
quota is stated, per the owner's own qualitative "a few good opportunities per week" framing. Full evidence:
`docs/research/TALONX_OWNER_DECISIONS.md` FREQ-001, `results/task31_owner_specification/operating_model_
spec.md`.

## 2. Intended user experience — **CONFIRMED** (zero-day acceptability and qualitative cadence) /
**CONFIRMED (concept) / RESEARCH_REQUIRED (measurement)** (whether current behavior delivers it)

Zero-signal days are a normal, accepted outcome — **CONFIRMED**, both from prior evidence (`docs/modules/
dispatch.md`'s "mobile notification fatigue" concern) and now directly from the owner's FREQ-001 answer. The
qualitative cadence a user should experience is **CONFIRMED**: "a few good opportunities per week" across
the full watchlist, not daily, not silent for long stretches. Whether CURRENT implementation delivers this
at PRODUCTION scale (35-50+ symbols) is unresolved — `INSUFFICIENT_COVERAGE_TO_COMPARE`, since the only
measured data (26 trades/year, 85 signals/year) comes from the 10-symbol research subset, not the intended
production watchlist. See `results/task33_owner_spec_finalization/frequency_alignment.md`.

## 3. Watchlist — **CONFIRMED** (scale target) / **OWNER_DECISION_PENDING** (breadth-vs-frequency policy,
lower priority, not part of the P1-P5 set)

Documented production engineering target: 50+ symbols (commit `7b7d815`). Observed practice: ~35-39 symbols.
Normal operating range: 35-50+ — **CONFIRMED** as part of the product identity statement (§1). Whether
watchlist breadth is meant to increase opportunity frequency, or only coverage while quality thresholds stay
constant, remains an open policy choice not addressed by the P1-P5 priority decisions — full detail in
`results/task31_owner_specification/watchlist_spec.md`.

## 4. Trade direction — **CONFIRMED**

```
FLAT + BULLISH  -> open long
LONG + BEARISH/CONTRADICTED -> exit long (SIGNAL_EXIT)
FLAT + BEARISH  -> no short entry (rejected, NO_ACTIVE_POSITION)
```
`LONG_ONLY_CONFIRMED` — already implemented (Task 25A/25A.1), tested, and structurally proven (Task 26's
zero-short invariant check on all 26 canonical trades). Not proposed for change by this document.

## 5. Signal families — **CONFIRMED**

RSI reversal, MACD crossover, and MA crossover are all **`CANDIDATE_REQUIRING_CONFIRMATION`** — confirmed
directly by the owner's SIG-001/002/003 answers. None should be treated as a final, standalone signal merely
because its trigger occurred. Confirmation may come from a different technical dimension (volume, RSI state,
MACD event, trend where conceptually appropriate) rather than necessarily another signal family firing — the
three families are not required to share identical implementation mechanics. Distinguish the TRIGGER FAMILY
(which technical event generated the candidate) from the CONFIRMATION COMPONENT (what independent evidence
validates it) — these are different roles, not interchangeable. Implementation alignment: MA is `ALIGNED`
already; RSI and MACD are `REQUIREMENT_INTERPRETATION_NEEDED` (see §6). Full matrix:
`results/task33_owner_spec_finalization/family_confluence_alignment.csv`.

## 6. Confluence philosophy — **CONFIRMED** (concept) / interpretation needed (2 of 3 families)

**`TRIGGER_PLUS_ONE_CONFIRMATION`** — confirmed directly by the owner's CONF-001 answer. A valid setup
consists conceptually of a signal-family trigger PLUS at least one independent confirmation; confluence is a
hard quality gate, not merely a ranking input. The trigger itself must NOT automatically be interpreted as
an additional confirmation unless its family contract explicitly says so.

**Traced against current implementation** (`results/task33_owner_spec_finalization/family_confluence_
alignment.csv`): MA crossover is `ALIGNED` (zero self-credit, genuinely independent confirmation required,
no ambiguity). RSI reversal and MACD crossover are both `REQUIREMENT_INTERPRETATION_NEEDED` — RSI curl's
trigger bundles a volume-surge precondition that confluence then re-scores as if independently arrived at;
MACD's trigger check and its own confluence credit are the literal same boolean, evaluated once and counted
twice. Neither is proven to violate the owner's contract, but neither is proven to comply with it either —
this is exactly the kind of case the owner instructed be traced rather than assumed. Notably, if MACD's
trigger self-credit were disallowed outright, MACD could never publish at all under the current
`confluence_score_min=2` threshold (the remaining two legs, RSI-extreme and volume-surge, have never
co-occurred on a MACD-cross bar in the entire dataset — 0 of 4,725 candidates). This is flagged for
follow-up owner interpretation, not resolved here.

## 7. Gate policy — **PROVISIONAL**

14 gates classified using a MANDATORY_SAFETY_GATE / MANDATORY_QUALITY_GATE / RANKING_FACTOR /
SOFT_PREFERENCE / OPERATIONAL_CONTROL / REMOVE_FROM_PRODUCT_CONTRACT / OWNER_DECISION_REQUIRED taxonomy.
Full table: `results/task31_owner_specification/gate_policy_spec.csv`.

## 8. Opportunity Score — **CONFIRMED** (purpose, as a fact) / **OWNER_DECISION_PENDING** (accepted as
ongoing policy) / redundancy finding acknowledged

Confirmed AS FACT: ranks already-qualified signals only, never participates in eligibility — matches current
implementation exactly, this is simply a correct description of the running code. Whether the owner ACCEPTS
`RANKING_ONLY_AFTER_HARD_GATES` as intended, ongoing product policy (as distinct from merely describing what
the code happens to do today) is a separate question — **OWNER_DECISION_PENDING**, no response recorded.
Flagged (not corrected): confluence (35%) and trend (15%) weight components have severely compressed
post-gate discriminating range, classified `POSSIBLE_OVER_FILTERING_DESIGN`. Weights unchanged. Full detail:
`results/task31_owner_specification/opportunity_score_spec.md`, `results/task32_owner_decision_capture/
specification_status.csv`.

## 9. Holding horizon — **CONFIRMED**

Short intraday to intraday swing (minutes to a few hours), same trading session only — EOD flatten is
mandatory, multi-session holding is structurally disallowed. Premarket entries allowed (subject to
liquidity/news gates); after-hours entries not allowed. Full detail: `results/task31_owner_specification/
holding_horizon_spec.md`.

## 10. Session behavior — **CONFIRMED**

Opening blackout (09:30-09:45 ET, both directions), closing blackout (15:30-16:00 ET, new bullish entries
only — exits always allowed), premarket/regular/closed session classification, and EOD flatten (15:50 ET)
are all existing, tested production behavior. Not modified by this document.

## 11. Signal-frequency objective — **CONFIRMED** (concept) / **RESEARCH_REQUIRED** (measurement at
production scale)

`REGULAR_OPPORTUNITY` — confirmed directly by the owner's FREQ-001 answer (see §1/§2). Measured baseline
(10-symbol research subset, not production scale): 26 trades/year, 85 signals/year. Current alignment:
`INSUFFICIENT_COVERAGE_TO_COMPARE` — no measurement exists yet at the intended 35-50+ symbol production
scale, so whether current gate-stack behavior actually delivers "a few good opportunities per week" cannot
yet be determined. This is now a well-defined, answerable product-fit question rather than an undefined one.
Resolving it requires a multi-week live observation period at production scale, not a new backtest or
parameter experiment. See `results/task33_owner_spec_finalization/frequency_alignment.md`.

## 12. Cost-tolerance requirement — **CONFIRMED** (execution-model components) / **RESEARCH_REQUIRED**
(numeric threshold)

Confirmed execution-model components (owner's COST-001 answer): liquid US equities, realistic spread
represented, realistic slippage represented, paper/live market-order-style execution assumptions acceptable
for current research. The exact numeric deployability threshold (bps) remains
`NUMERIC_TOLERANCE_PENDING` — 6 of 8 execution-environment sub-questions (broker/venue, order type, fill
latency, etc.) are still open, see `results/task32_owner_decision_capture/execution_environment_questions.
md`. Task 26's own 0/5/10/20bps cost-sensitivity result is retained strictly as evidence of
`CURRENT_CANONICAL_EDGE_NOT_COST_ROBUST_UNDER_TESTED_ASSUMPTIONS` — explicitly not used to select a
threshold, per the owner's own instruction. **Any future claim of `PRODUCTION_EDGE_CONFIRMED` remains
blocked until the numeric tolerance is established.** See `docs/research/TALONX_OWNER_DECISIONS.md` COST-001,
`results/task33_owner_spec_finalization/cost_requirement_status.md`.

## 13. ATR semantics — all three use cases now owner-confirmed conceptually; one has a proven implementation
gap

**Current implementation — CONFIRMED (`VERIFIED_FACT`)**: ATR(14) is computed on 14 one-minute bars,
continuous across session boundaries, identical between live and backtest at the mechanism level.
`ATR_INTRADAY_14_CONFIRMED` for CURRENT behavior.

**Per-use-case contract (all three owner-confirmed, per `docs/research/TALONX_OWNER_DECISIONS.md`)**:

- **ATR-USE-2, `atr_move_multiplier`** (bar-movement gate) — **CONFIRMED**: owner accepted current
  implementation as-is (`SHORT_TERM_INTRADAY_ATR`). Implementation alignment: `ALIGNED`. No follow-up.
- **ATR-USE-1, `min_atr_pct`** (volatility/regime qualification) — **CONFIRMED (concept) / RESEARCH_
  REQUIRED (implementation)**: owner confirmed `MULTI_TIMEFRAME` — the qualification should reflect broader
  market/instrument volatility context while still allowing short-term intraday information where
  appropriate; no numeric period/threshold chosen. Implementation alignment:
  `CURRENT_IMPLEMENTATION_INCOMPLETE_FOR_CONFIRMED_REQUIREMENT` — not a historical bug, since this
  requirement was only just defined; no broader-timeframe context exists anywhere in the current gate. 5
  design questions defined for future research, none answered, lower priority than ATR-USE-3 below. See
  `results/task33_owner_spec_finalization/next_controlled_research_design.md`.
- **ATR-USE-3, stop/target geometry** — **CONFIRMED (concept) / RESEARCH_REQUIRED (implementation),
  HIGHEST-PRIORITY IMPLEMENTATION GAP IN THIS SPECIFICATION.** Owner confirmed `MARKET_STRUCTURE_PRIMARY` —
  the stop should primarily reflect market-structure invalidation (pivots/swing levels/support-resistance);
  ATR is permitted only as fallback, buffer, or minimum-noise allowance, never as the dominant unconditional
  source. **A direct code trace found the current implementation is `MISALIGNED`** — not a hypothesis, a
  proven fact: `calculate_trade_geometry` (`talonx_quant/strategy.py:211-269`) computes `stop = price - 1.5
  x ATR(14, 1-minute)` UNCONDITIONALLY for every candidate; there is categorically no structural-stop code
  path anywhere in this function. Structural pivot data is used exclusively on the TARGET/reward side, never
  the stop/risk side — the inverse of the confirmed contract. This upgrades Task 31's `TIMEFRAME_MISMATCH`
  hypothesis (based on the STOP-exit-timing pattern: Task 26 median 4 minutes vs. 14 min/2.6 hr for
  TARGET/EOD exits) to a confirmed structural gap now that a concrete contract exists to trace against. See
  `results/task33_owner_spec_finalization/current_stop_geometry_flow.md`.

**Live/backtest parity — TECHNICAL_CONSTRAINT (not an owner decision)**: `PARTIAL_PARITY` — computation
mechanism proven identical by shared code; end-to-end numerical parity remains unverified due to Task 25C's
unresolved warmup-seed-capture gap.

**Production posture while implementation work remains open**: `RUN_OBSERVATIONAL_SHADOW_ONLY` — see
`results/task32_owner_decision_capture/atr_live_policy.md`. No real capital is at risk under this posture
(TalonX runs on `talonx_paper`, simulated execution).

**No code was changed in Tasks 31-33.** Full detail: `results/task31_owner_specification/atr_current_
implementation.md`, `atr_semantics_matrix.csv`, `atr_parity_audit.md`, `atr_future_change_scope.md`,
`results/task32_owner_decision_capture/atr_use_case_decisions.csv`, `atr_risk_model_options.md`,
`results/task33_owner_spec_finalization/atr_use_case_contract.csv`, `current_stop_geometry_flow.md`,
`next_controlled_research_design.md` (Task 34 — Structural Stop Geometry Contract Audit — designed, not
started).

## 14. Risk/exit philosophy — **CONFIRMED** (mechanism) / **MISALIGNED** (geometry basis, per §13)

STOP/TARGET/SIGNAL_EXIT/END_OF_SESSION exit paths, post-loss lockout (75 min), and per-ticker cooldown (20
min) are existing, tested production behavior — the MECHANISM is `CONFIRMED`. The GEOMETRY basis for the
stop distance specifically is now a confirmed gap, not an open question: per §13's `MARKET_STRUCTURE_
PRIMARY` contract, traced against the code, the stop is `MISALIGNED` — 100% ATR-derived, 0% structural, for
every candidate that has ever executed. The mechanism (stop/target/exit-path plumbing) works correctly; the
GEOMETRY FORMULA it currently uses does not yet match the confirmed risk philosophy. See
`results/task33_owner_spec_finalization/current_stop_geometry_flow.md`.

## 15. Evidence standard — **PROVISIONAL**

Eight-dimension policy (sufficient trade count via CI, multi-regime coverage, non-concentrated symbols,
cost robustness, OOS validation, formal concentration limits, deterministic reproducibility, confidence-
interval reporting) proposed as the bar for calling TalonX's edge "demonstrated." No arbitrary trade-count
number is forced. Current n=26 baseline meets 1 of 8 dimensions fully (reproducibility). Full policy:
`results/task31_owner_specification/statistical_evidence_policy.md`.

## 16. Open owner decisions

**All 9 priority (P1-P5) owner decisions are now `OWNER_CONFIRMED`** — see
`docs/research/TALONX_OWNER_DECISIONS.md` for the verbatim answers (FREQ-001, CONF-001, SIG-001/002/003,
ATR-TRIGGER-001, ATR-REGIME-001, ATR-RISK-001, COST-001). What remains open is narrower in scope: (a) two
implementation-interpretation questions within the already-confirmed confluence philosophy (RSI/MACD trigger
self-credit, §6), (b) lower-priority items not part of the P1-P5 set (watchlist breadth-vs-frequency policy,
§3; per-gate hard/soft sign-off, §7; Opportunity Score policy acceptance, §8), and (c) `RESEARCH_REQUIRED`
implementation work for the concepts the owner already confirmed (multi-timeframe volatility design,
structural stop-geometry formula design, cost-model numeric threshold). See
`results/task33_owner_spec_finalization/owner_decisions_captured.csv` for the complete before/after status
of all 9 priority items, and `results/task32_owner_decision_capture/future_experiment_blockers.csv` for what
each remaining open item blocks.

## 17. Version / change-control policy — **PROVISIONAL**

This document is append-only in spirit, matching `docs/research/TALONX_RESEARCH_LEDGER.md`'s own convention:
once an owner decision box is signed off, that section's status changes from PROVISIONAL to CONFIRMED in a
dated revision, with the prior provisional text preserved (struck through or moved to a changelog), not
silently overwritten. Any future task that materially changes gate thresholds, ATR semantics, or confluence
behavior MUST update this document as part of that task's own required artifacts, not as a separate
afterthought. This document does not supersede `TALONX_RESEARCH_LEDGER.md` — the ledger remains the
chronological research record; this document is the synthesized, current-state product authority derived
from it.

---

**Revision history**: v0.1 (DRAFT) — created by Task 31, 2026-08-21, committed at checkpoint
`4c6ef7e6691be4dd144cb7c1e1e3644d5e664e45`. v0.2 (DRAFT) — refined by Task 32, 2026-08-21, committed at
checkpoint `baa0cc6efecababf2da519b7455700165e842c10`: split several PROVISIONAL markers into the more
precise OWNER_DECISION_PENDING/TECHNICAL_CONSTRAINT taxonomy, resolved ATR semantics per-use-case rather
than as a single item, added the canonical `TALONX_OWNER_DECISIONS.md` form. **v0.3 — Task 33, 2026-08-21:
all 9 P1-P5 priority owner decisions captured and promoted to CONFIRMED (product identity, frequency
objective, confluence philosophy, signal-family roles, all three ATR use-case contracts, cost-model
components); traced current implementation against each and found ATR-USE-3 (stop/target geometry)
`MISALIGNED` — a proven, code-traced structural gap (§13/§14), the highest-priority open implementation item
in this specification. RSI/MACD confluence self-credit flagged as needing narrower interpretation, not a new
open-ended decision.** Not yet committed/pushed, pending review — see
`docs/research/TALONX_RESEARCH_LEDGER.md`'s Task 33 entry for the corresponding checkpoint SHA once
committed.
