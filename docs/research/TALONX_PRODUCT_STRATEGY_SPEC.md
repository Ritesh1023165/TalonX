# TalonX Product & Strategy Specification

**Status: DRAFT — produced by Task 31 (2026-08-21), pending owner review and sign-off.** This document is
intended to become the product-level strategy authority for TalonX, sitting below explicit future owner
decisions and above individual research tasks. Every section below is marked **CONFIRMED** (an existing,
verified requirement or already-implemented/tested behavior) or **PROVISIONAL** (a recommendation awaiting
owner sign-off via the decision box in the corresponding `results/task31_owner_specification/*.md` file).
Nothing in this document changes production code, thresholds, or gate order — it is a specification, not an
implementation.

This document does not stand alone — each section links to its full supporting analysis in
`results/task31_owner_specification/`, which should be read for complete evidence and reasoning.

---

## 1. Product identity — **PROVISIONAL**

> TalonX is a high-precision intraday opportunity scanner over a broad, liquid-equity watchlist (50+
> symbols targeted). It prioritizes quality over frequency, may produce zero-signal days as a normal and
> accepted outcome, opens only long positions, uses bearish signals as exits from an existing long (never as
> new short entries), and closes all exposure intraday (no overnight positions).

Full evidence and traceability: `results/task31_owner_specification/operating_model_spec.md`. Decision box
awaiting sign-off there.

## 2. Intended user experience — **PROVISIONAL** (frequency) / **CONFIRMED** (zero-day acceptability)

Zero-signal days are a normal, accepted, and even deliberately engineered-for outcome — `docs/modules/
dispatch.md`'s explicit "mobile notification fatigue" concern, with no corresponding concern about
inactivity anywhere in this project's history — **CONFIRMED**. A user watching Telegram daily should
currently expect no alert on the large majority of days (~90%, measured from Task 26's canonical trades).
The TARGET frequency a user should experience is **OWNER_DECISION_REQUIRED** — see §11 below and
`results/task31_owner_specification/frequency_spec.md`.

## 3. Watchlist — **PROVISIONAL**

Documented production engineering target: 50+ symbols (commit `7b7d815`). Observed practice: ~35-39 symbols.
Proposed normal operating range: 35-50+. Whether watchlist breadth is meant to increase opportunity
frequency, or only coverage while quality thresholds stay constant, is an open policy choice — full detail
in `results/task31_owner_specification/watchlist_spec.md`.

## 4. Trade direction — **CONFIRMED**

```
FLAT + BULLISH  -> open long
LONG + BEARISH/CONTRADICTED -> exit long (SIGNAL_EXIT)
FLAT + BEARISH  -> no short entry (rejected, NO_ACTIVE_POSITION)
```
`LONG_ONLY_CONFIRMED` — already implemented (Task 25A/25A.1), tested, and structurally proven (Task 26's
zero-short invariant check on all 26 canonical trades). Not proposed for change by this document.

## 5. Signal families — **PROVISIONAL**

RSI reversal, MACD crossover, and MA crossover are each documented as standalone, complete setups but
currently behave as a cross-family confirmation network. Recommended: classify all three as candidate
generators requiring another family's confirmation, formalizing existing behavior rather than proposing a
change. Full matrix: `results/task31_owner_specification/signal_family_spec.md`.

## 6. Confluence philosophy — **PROVISIONAL**

Recommended: "trigger + one independent confirmation." Matches MACD and RSI-curl's current behavior exactly;
MA crossover currently behaves closer to a stricter policy (needs two independent confirmations, has zero
self-credit) — flagged as an open inconsistency, not corrected here. Full analysis: `results/task31_owner_
specification/confluence_spec.md`.

## 7. Gate policy — **PROVISIONAL**

14 gates classified using a MANDATORY_SAFETY_GATE / MANDATORY_QUALITY_GATE / RANKING_FACTOR /
SOFT_PREFERENCE / OPERATIONAL_CONTROL / REMOVE_FROM_PRODUCT_CONTRACT / OWNER_DECISION_REQUIRED taxonomy.
Full table: `results/task31_owner_specification/gate_policy_spec.csv`.

## 8. Opportunity Score — **CONFIRMED** (purpose) / **PROVISIONAL** (redundancy acknowledgment)

Confirmed purpose: ranks already-qualified signals only, never participates in eligibility — matches current
implementation exactly. Flagged (not corrected): confluence (35%) and trend (15%) weight components have
severely compressed post-gate discriminating range, classified `POSSIBLE_OVER_FILTERING_DESIGN`. Weights
unchanged. Full detail: `results/task31_owner_specification/opportunity_score_spec.md`.

## 9. Holding horizon — **CONFIRMED**

Short intraday to intraday swing (minutes to a few hours), same trading session only — EOD flatten is
mandatory, multi-session holding is structurally disallowed. Premarket entries allowed (subject to
liquidity/news gates); after-hours entries not allowed. Full detail: `results/task31_owner_specification/
holding_horizon_spec.md`.

## 10. Session behavior — **CONFIRMED**

Opening blackout (09:30-09:45 ET, both directions), closing blackout (15:30-16:00 ET, new bullish entries
only — exits always allowed), premarket/regular/closed session classification, and EOD flatten (15:50 ET)
are all existing, tested production behavior. Not modified by this document.

## 11. Signal-frequency objective — **OWNER_DECISION_REQUIRED**

No historical target trade/signal frequency was ever specified, across this entire project's history
(exhaustive search, Task 30). Measured baseline: 26 trades/year, 85 signals/year, 10-symbol universe. Whether
this is acceptable, too low, or too high cannot be judged without a target. Category framework (VERY_RARE /
RARE / REGULAR / ACTIVE) proposed for owner selection: `results/task31_owner_specification/frequency_spec.
md`.

## 12. Cost-tolerance requirement — **OWNER_DECISION_REQUIRED**

No document states a target cost tolerance. System design (tight stops, short holds) implies a need for low
absolute tolerance, but no specific number can be defended without knowing the intended execution venue.
Classified `COST_TOLERANCE_REQUIREMENT_UNDEFINED`. Full framework: `results/task31_owner_specification/
cost_tolerance_spec.md`.

## 13. ATR semantics — **CONFIRMED** (current implementation) / **OWNER_DECISION_REQUIRED** (intended
semantics for 2 of 3 use cases)

**Current implementation (verified fact)**: ATR(14) is computed on 14 one-minute bars, continuous across
session boundaries, identical between live and backtest at the mechanism level. `ATR_INTRADAY_14_CONFIRMED`
for CURRENT behavior.

**Per-use-case intent**:
- `atr_move_multiplier` (bar-movement gate): current 1-minute timeframe is `SEMANTICALLY_COHERENT` —
  definitionally correct, not an open question.
- `min_atr_pct` (volatility floor): `REQUIREMENT_AMBIGUOUS` — could plausibly be intended as intraday-scale
  or daily-regime-scale; not resolved by any historical document.
- **Stop/target geometry** (`atr_stop_multiplier`): `TIMEFRAME_MISMATCH` — the highest-priority open item. A
  stop sized to 1.5x of 1-minute-scale ATR is plausibly, though not proven causally, too tight for the
  confirmed minutes-to-hours holding horizon (§9), and is consistent with — though not proven to cause —
  Task 26's own observed fast-STOP-exit pattern (median 4 minutes vs. 14 min/2.6 hr for TARGET/EOD exits).

Live/backtest parity: `PARTIAL_PARITY` — computation mechanism proven identical by shared code; end-to-end
numerical parity remains unverified due to Task 25C's unresolved warmup-seed-capture gap.

**No code was changed.** Full detail: `results/task31_owner_specification/atr_current_implementation.md`,
`atr_semantics_matrix.csv`, `atr_parity_audit.md`, `atr_future_change_scope.md`.

## 14. Risk/exit philosophy — **CONFIRMED** (mechanism) / cross-references §13 (geometry basis)

STOP/TARGET/SIGNAL_EXIT/END_OF_SESSION exit paths, post-loss lockout (75 min), and per-ticker cooldown (20
min) are existing, tested production behavior. The GEOMETRY basis for the stop distance specifically is the
open ATR question in §13 — this section describes the MECHANISM (confirmed), not whether its current
calibration is optimal (open).

## 15. Evidence standard — **PROVISIONAL**

Eight-dimension policy (sufficient trade count via CI, multi-regime coverage, non-concentrated symbols,
cost robustness, OOS validation, formal concentration limits, deterministic reproducibility, confidence-
interval reporting) proposed as the bar for calling TalonX's edge "demonstrated." No arbitrary trade-count
number is forced. Current n=26 baseline meets 1 of 8 dimensions fully (reproducibility). Full policy:
`results/task31_owner_specification/statistical_evidence_policy.md`.

## 16. Open owner decisions

See `results/task31_owner_specification/decision_register.csv` for the complete, itemized list (15 rows, all
`owner_answer=PENDING`). Highest-priority items: (1) target signal/trade frequency, (2) cost-tolerance
requirement, (3) ATR stop-distance intended timeframe.

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

**Revision history**: v0.1 (DRAFT) — created by Task 31, 2026-08-21. Not yet committed/pushed, pending
review — see `docs/research/TALONX_RESEARCH_LEDGER.md`'s Task 31 entry for the corresponding checkpoint SHA.
