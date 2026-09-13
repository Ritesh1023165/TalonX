# Task 129 — research programme decision

Full mechanism-by-mechanism evidence: `TASK129_EVIDENCE_MATRIX.csv`.
This document is the concise synthesis and decision only.

## 1. Actual product requirements

**Stated, and operationally delivered**: configured tickers; intraday
and short/long-term opportunity SUPPORT (both horizons are now
authorized product surfaces, Task 127); understandable BUY/SELL
alerts; local paper portfolios and dashboard (V2/Original/Experimental
lanes, `:8787`); long-only execution, SELL only closes a long; free
data/existing infrastructure reused throughout; alerts and paper
outcomes tracked separately (never conflated in any report this
programme produced).

**Stated, economically still unsupported**: "positive aggregate
economics" itself. No mechanism in this repository currently has a
supported, positive, materiality-clearing profitability result on a
live-configured population. This is the actual open requirement.

**Not required, and not treated as required anywhere in this
programme**: every ticker must alert; every session must trade; every
signal must differ per ticker; long-term holdings are prohibited (the
opposite was affirmed, Task 127); a complex strategy beats a simple
baseline by default (Task 128 found the reverse).

## 2. Evidence summary

Ten distinct mechanisms have been examined (`TASK129_EVIDENCE_MATRIX.csv`).
None currently carries an `ADVANCE_TO_FURTHER_VALIDATION` or economically
supported verdict:

- **Free price/volume alpha (8 grouped hypothesis spaces, 93–101B)**:
  CLOSED — 0 of ~300+ pre-registered experiments passed; the closure
  clause's own bar (a materially new data/feature class) has not been
  met by anything free identified to date.
- **Original**: `INSUFFICIENT_EVIDENCE` — 1 trade in 18.7 months, no
  sample exists either way.
- **Experimental**: `DO_NOT_ADVANCE`, archived — negative gross/net,
  PF 0.764, CI does not clear ±$1.25/trade, same-population data
  exhausted.
- **V2, configured 39-name live scope**: `INCONCLUSIVE` — N=57, 95% CI
  [−4.57%,+1.11%] includes zero. Genuinely undetermined, not rejected.
- **V2, broader research populations**: positive, CIs exclude zero —
  but a different population; not transferred to the live scope.
- **Overnight-attention, Track A (association)**: `ASSOCIATION_SUPPORTED`
  (qualified) — real but explicitly non-actionable.
- **Overnight-attention, Track B (actionable)**: `DO_NOT_ADVANCE` —
  re-tested on a 5.4× larger, independently feed-verified dataset;
  same negative-leaning, CI-includes-zero result.
- **52-week-high, 6-month hold**: `DO_NOT_ADVANCE` — positive absolute
  return, but the no-selection benchmark did better; incremental CI
  includes zero.
- **No-selection long-term benchmark**: `USEFUL_AS_TRACKING_BENCHMARK_ONLY`
  — a genuine, now-correctly-reconciled research control, not a
  standalone product.
- **Turn-of-month**: `DO_NOT_ADVANCE` on product-fit grounds only —
  never economically tested.

## 3. Why this has taken this long (five causes, concrete evidence, lightweight fixes)

1. **Stale-worktree/runtime-parity errors** — Task 121's "no exit
   caller exists" claim was false (a stale research-worktree copy of
   `run.py` missed 38 upstream commits), corrected in 121A.
   *Prevention*: reuse the provenance-manifest check already built in
   121A (`verify_provenance()`) as a standing pre-replay step against
   any production-adjacent code.
2. **Accounting/labeling corrections found a task later** — Task120's
   gross/net equity bug, Task122's "chronologically propagated"
   mislabel, Task127's "adds no value"/beta-attribution overclaims,
   Task128's discovery that "+13.70%" was a cohort average, not a
   portfolio return. *Prevention*: at freeze time, state in one
   sentence which exact function/computation produces the headline
   number — the average-vs-portfolio class of error is caught before
   publishing, not after.
3. **Product restrictions inferred without user support** — Task126
   assumed "no existing multi-month strategy ⇒ unauthorized" and
   "ticker differentiation is required," both withdrawn in Task 127.
   *Prevention*: tag every scope-limiting claim as REQUIREMENT (user
   said so) or INFERENCE (this programme's own gloss) — a labeling
   habit, not new tooling.
4. **Data-extension checked one task later than necessary** —
   Task123 ran on the then-existing 7-month intraday window; Task124
   then checked for more; Task125 acquired it. *Prevention*: reuse
   Task124's own "inventory before running" step as the standing FIRST
   move for any new hypothesis.
5. **Provenance assumed instead of verified** — Task124 first
   suspected `task93_canonical_v1` was IEX; Task125 checked the actual
   acquisition code and a live probe and found it was SIP all along.
   *Prevention*: verify feed/runtime provenance from source code or a
   direct probe, never from a cached description — reusing the exact
   pattern 121A/125 already established.

No new governance platform, test-suite rewrite, or documentation
cleanup is proposed for any of these — each fix reuses a mechanism this
programme already built.

## 4. Is a next experiment justified?

Applying the six-point gate to every remaining candidate:

- **Turn-of-month**: blocked by a PRODUCT decision (accept
  non-differentiating alerts?), not a data or mechanism gap — a result
  would not change a RESEARCH decision, only a prior product choice.
  Fails gate point 5.
- **52-week-high at the published 6–12 month horizon**: would require
  either a longer usable history than exists locally (fails point 4 —
  only 12 non-overlapping macro-blocks are available from the current
  free daily panel) or a materially longer product-horizon
  authorization (a product decision, not a research one).
- **V2 (configured scope)**: genuinely inconclusive, but the only
  "next step" available is more elapsed live time on the same frozen
  contract — explicitly excluded by this task's own rule against
  indefinite live observation and automatic follow-ons after an
  inconclusive result.
- **A new free price/volume hypothesis**: the closure clause's own bar
  (materially new data/feature class) has not been met by anything
  free; inventing one now would be exactly the "new shortlist merely
  to keep work moving" this task prohibits.

**No candidate clears the gate.** This is not a claim that all
free-data research is exhausted in any absolute sense — only that,
against THIS repository's actual accumulated evidence, no bounded,
non-parameter-variation, gate-passing experiment is currently
identifiable.

## 5. Programme decision

> **`PAUSE_ALPHA_RESEARCH_UNDER_CURRENT_CONSTRAINTS`**

- **Remains usable**: the descriptive Intelligence/Risk-Event system
  (no predictive claim, unaffected); V2/`INSIDER_BUY_CLUSTER_V2` as a
  live paper strategy (inconclusive, not rejected — may continue to
  run and accumulate passively); the dashboard/paper-portfolio
  infrastructure and the now-corrected chronological-benchmark tooling
  (Task 128), reusable for any future candidate.
- **Unsupported claims**: no mechanism in this repository currently
  supports a positive, materiality-clearing profitability claim on any
  live-configured population, intraday or long-term.
- **What would justify resuming**: (a) an explicit user product
  decision authorizing a genuine long-hold alert type or accepting
  non-differentiating calendar alerts, unblocking an already-scoped
  candidate without new data; (b) authorization for a materially new,
  paid, or non-price data/feature class (consensus estimates, options)
  — the specific bar this programme's own closure clause already sets;
  (c) V2's live paper campaign accumulating a materially larger N,
  observed passively as part of normal product review, not as a
  dedicated task.
- **Stops immediately**: any further free daily/intraday price-volume
  hypothesis generation; any parameter variation of an already-closed
  contract (overnight-attention, 52-week-high, Experimental).

## 6. Budget for future authorized work (not spent now)

At most ONE new evaluation; at most 2 working days of active effort
unless a measured, disclosed computation requires more; no tuning
after results; no automatic follow-on after an inconclusive result.
**Roadmap start date retained: 2026-09-11** (Task 118H's product
roadmap decision) — not reset by this or any prior correction. **Stop
condition, defined now**: the programme stays paused until one of the
three resuming conditions in §5 occurs, or the 2-day budget on any
subsequently authorized single evaluation is exhausted without a
clearing result — whichever comes first.

## 7. Three-row roadmap

| | deliverable | completion gate | what the user gains |
|---|---|---|---|
| **Now** | this decision + evidence matrix, published | this document's commit | an honest, closed accounting of what has and hasn't worked — no new unsupported claim |
| **Next authorised action** (not started) | ONE user product decision (long-hold/non-differentiating alerts) OR a data/feature-class authorization | the user's explicit choice, recorded | a concretely bounded next research task, only if chosen |
| **Decision afterward** | the resulting single bounded experiment, OR continued passive V2 observation | the frozen acceptance criteria from whichever path is chosen | a definitive verdict, not another open cycle |

**Intraday status**: `INSUFFICIENT_EVIDENCE` (Original) /
`DO_NOT_ADVANCE`, archived (Experimental) — no working free intraday
edge found. **Long-term status**: `INCONCLUSIVE` (V2, open) /
`DO_NOT_ADVANCE` (overnight-attention, 52-week-high) /
`USEFUL_AS_TRACKING_BENCHMARK_ONLY` (no-selection baseline) — no
working long-term edge found either; V2 alone remains genuinely open.
No deployment is recommended anywhere in this document.

## 8. Task 128 closing notes (dated, no recalculation)

- `USEFUL_AS_TRACKING_BENCHMARK_ONLY` stands unchanged.
- Lower return with lower max drawdown (baseline −19.58% vs. SPY
  −33.79%) does **not**, by itself, establish that SPY dominates the
  baseline on a risk-adjusted basis — no Sharpe-type or risk-adjusted
  metric was computed in Task 128; the return comparison and the
  drawdown comparison are two separate facts, not yet combined into
  one ranking.
- The survivor-universe limitation means this HISTORICAL panel cannot
  show a past delisting by construction — it does **not** mean future
  delisting risk for currently-active names is impossible; that risk
  is real and unmeasured here, not ruled out.
- The distinction between Task 127's original cohort-return average
  and Task 128's chronological portfolio result stands as reported —
  not re-collapsed here.
