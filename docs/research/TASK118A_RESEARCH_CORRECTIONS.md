# Task 118A Priority 4 — dated corrections to Task 118 research reports (2026-09-11)

Per this task's explicit instruction: **original conclusions in
`TASK118_BASELINE_RECONCILIATION.md` and `TASK118_NEXT_EXPERIMENT.md` are
preserved unedited.** This document records three corrections found on
review, each dated, each explaining exactly what was wrong and what the
corrected statement is. Both original files now carry a one-line pointer to
this document at the top of the relevant section.

> **2026-09-11 (Task 118B) further correction, original text below
> unedited**: this protocol still under-specified the estimand, ignored
> issuer-repetition clustering, conflated "this scope's expectancy is
> negative" with "this scope underperforms the broader panel", and did
> not account for repeated-look multiplicity. See
> `TASK118B_RESEARCH_PROTOCOL.md` for the fully revised protocol, which
> supersedes the bounded observation protocol below.

## Correction 1 — the rejection criterion in `TASK118_NEXT_EXPERIMENT.md` was ambiguously/backwards worded

**Original text** (§"What would cause rejection of this recommendation"):
> "...the accumulated live sample continued to show negative net
> expectancy with a confidence interval that excludes zero on the positive
> side..."

**Problem**: "excludes zero on the positive side" is genuinely ambiguous
between two opposite readings — (a) the interval sits entirely on the
positive side, excluding zero from below (i.e. a **positive** result), or
(b) the interval's positive bound stops short of zero, i.e. the whole
interval is **negative**. Read as (a), the sentence describes exactly the
**opposite** of a rejection condition — a CI entirely above zero is
*evidence of profitability*, not grounds to reject the strategy. This is
the "reversed rejection criterion" defect named in the Task 118A request.
Whichever reading was intended, the sentence must not survive as written.

**Corrected, unambiguous bounded observation protocol** (replaces the
informal one-line criterion; does not retroactively change the frozen V2
contract or trigger any promotion):

| element | value |
|---|---|
| **What is observed** | Live 39-name-scope V2 paper trades, forward, from the 2026-09-11 controlled activation onward — never the already-inspected 2024–2026 backtest window. |
| **Sample requirement before any verdict** | At minimum N=30 closed round trips (a conventional lower bound for a t-based CI to be minimally informative; still not "large" — this is a floor, not a target) — matching the same order of magnitude Task 107B/109's discovery-set sizing used before drawing a conclusion. Below N=30, only "insufficient sample" may be reported, never a verdict either way. |
| **Review horizon** | Reviewed no more often than monthly, and not before 60 calendar days of live observation have elapsed — avoids stopping on a favorable or unfavorable short streak (the same "do not peek and stop early" discipline as the frozen V2 contract's own pre-registration). |
| **Uncertainty handling** | A block-bootstrap or issuer-clustered CI (matching `talonx_research.validation`'s existing machinery for the full-panel case, Task 107B/112R) on net expectancy per 10-trading-day trade — a plain normal-approximation CI is not adequate at this sample size. |
| **Adverse-result criterion (the actual, corrected rejection rule)** | The 39-name scope is flagged as **underperforming the broader validated panel** only if, at the next scheduled review with N≥30, the live sample's net-expectancy CI is **entirely negative (its upper bound is below zero)** — i.e. the data excludes a zero-or-positive outcome, not the reverse. |
| **What a flag means** | A trigger prompts *re-examining the scope's composition* (which names are in it, not the frozen strategy rule) — it is not, by itself, grounds to alter `INSIDER_BUY_CLUSTER_V2`, which stays governed by its own frozen contract and lifecycle (`docs/STRATEGY_LIFECYCLE.md`). |
| **What does NOT trigger anything** | A CI that includes zero (inconclusive, expected at small N); a CI that is entirely positive (that is evidence FOR the scope, not a rejection signal); single-trade or single-week swings. |

No threshold above was chosen post-hoc to force a particular verdict — N=30
and the monthly/60-day cadence are stated before any further live data is
observed, and are visibly less favorable to a "pass" than the frequency
with which the underlying frozen contract itself was validated (Task
107B/109/112R used hundreds to low-thousands of episodes).

> **2026-09-11 (Task 118B) further correction, original text below
> unedited**: the −$23,042.30 / −0.23% / −7.68% figures below are
> **cash-path**, not portfolio drawdown — `portfolio_cash_after` is
> uninvested cash only; buying an asset reduces cash without an
> equivalent economic loss. The **real, mark-to-market equity drawdown**
> is **−$7,132.76** (**−0.0713%** on $10m, **−2.3560%** on $300k) — see
> `TASK118B_EQUITY_RECONCILIATION.md` for the full daily equity series.

## Correction 2 — the −$23,042.30 "drawdown" figure needed reconciliation, and is base-dependent

**Original text** (`TASK118_BASELINE_RECONCILIATION.md` §C.3):
> "real portfolio-equity max drawdown (dollars): −$23,042.30 ... (% of peak
> book value): −0.2304%"

This number was **correctly computed** against the **$10,000,000
research-convention book** it was labelled against, and is **correctly
distinguished** there from the unrelated −42.7% cumulative-trade-return
running-sum figure (a different quantity entirely — that distinction
stands, unchanged). **What was missing**: the same **identical dollar**
drawdown (−$23,042.30 — identical because the $300k diagnostic run in §C.4
produced byte-identical trades/prices to the $10M run) was **never
re-expressed as a percentage of the $300,000 live-campaign base**, even
though §C.4 discusses the $300k diagnostic specifically. Reporting only
the $10M-based percentage there, adjacent to a $300k discussion, invites
exactly the confusion the Task 118A request names: *"identical dollar
results on $300k and $10m imply different percentages."*

**Reconciliation, computed directly from the $300k diagnostic's own trade
sequence** (`baseline_a_300k_replay_result.json`, `portfolio_cash_after`
trace):

| book | max drawdown (dollars) | max drawdown (% of peak) |
|---|---:|---:|
| $10,000,000 research-convention book | **−$23,042.30** | **−0.23%** |
| $300,000 live-campaign-sized book (diagnostic) | **−$23,042.30** (same dollar path — trades are byte-identical) | **−7.68%** |

**Corrected interpretation**: the dollar-drawdown figure is a property of
the trade sequence and fixed $10,000/position sizing, not of the book size
— it is identical either way. The **percentage** figure is a property of
the book size, and is **~33x larger relative to the $300,000 book than to
the $10,000,000 book**. The **decision-relevant number for the actual live
$300,000 campaign is −7.68%, not −0.23%** — the smaller figure, reported
alone, understated the drawdown's practical significance to the real
capital base by roughly two orders of magnitude relative significance. Both
numbers remain far smaller than the unrelated −42.7% cumulative-trade-
return figure (Correction/§C.3's own distinction), which stays correctly
labelled as a different, non-dollar-scaled quantity.

Reproducible: `results/task118_profitability/baseline_a_300k_replay_result.json`
(gitignored, hash in the Task 118 journal record), same drawdown-walk logic
as `reconcile.py`, re-run against `portfolio_cash_after` with `peak =
max(peak, 300000.0)` as the starting reference instead of $10,000,000.

## Correction 3 — "every free-data alpha space is closed" was an overbroad claim

**Original text** (multiple places, e.g. `TASK118_NEXT_EXPERIMENT.md` §Recommended
next experiment, point 3): "every alternative free-data alpha space...
is already closed."

**Problem**: stated as a blanket, unqualified claim, this overclaims —
"every" implies exhaustive closure of *all conceivable* free-data
hypotheses, which was never tested or true. What is actually true, and
what should have been cited, is a **specific, named list** of hypotheses
that were tested and rejected, each with its own limiting finding:

| task | hypothesis tested | specific limiting result |
|---|---|---|
| 93 | frozen-strategy baseline edge | strategy makes 1 trade across all history — edge weak/unproven at that sample |
| 94 | intraday alpha discovery (49 studies) | best candidate (09:30–10:00 drift, +0.048R@5bps) is sub-threshold — signal ≈ round-trip cost |
| 95A | expanded-regime intraday (2020–26, 25.8M SIP bars) | intraday drift ~5bps ≈ cost across every regime tested |
| 95B | swing (3–10 day) foundation | economics feasible but price/volume features add no directional information at that horizon |
| 95D | earnings-event alpha (902 8-Ks, 56 experiments) | post-earnings reaction **mean-reverts**; consensus-surprise data unavailable free |
| 95E/95G | cross-sectional / broad cross-sectional (620-symbol panel) | relative momentum **inverts negative**, strengthened by breadth |
| 95I | deterministic filing-event alpha (3,282 events, 101 experiments) | only signed effect found is **negative** (risk-factor-change, −67bps@k5) |
| 95K | risk-avoidance filter (63 experiments) | every flagged-name forward return is **positive** — TalonX is not better at avoidance than entry |
| 97 | catalyst-displacement (8-K × gap/RVOL) | reproduces 95D's inversion; no edge found in Group A (n=183, every CI includes 0) |
| 106A | "V2"-shaped catalyst × multi-day | not a new hypothesis — materially identical to 97 and 95D, already tested |

**Corrected statement**: these **ten specific, named hypothesis families**
were tested and rejected under the conditions and sample sizes shown above.
This is not evidence that no other free-data hypothesis could ever work —
it is evidence that these ten, specifically, did not, at the power available
when each was run. A future task proposing to revisit any of them needs a
**new, specific reason** that condition has changed (new data, a
materially different sample, a different causal mechanism) — "closed"
describes these ten spaces, not the space of all possible future research.

## Where these corrections are referenced

- `docs/research/TASK118_BASELINE_RECONCILIATION.md` §C.3/§C.4 — pointer added.
- `docs/research/TASK118_NEXT_EXPERIMENT.md` — pointer added at the
  "Recommended single next experiment" and decision-table sections.
- `docs/task_journal/entries/2026-09-11_task118_profitability_diagnostics/record.md`
  — a "Corrections" section appended (this entry predates Task 118A but is
  the one these corrections apply to).
- `docs/task_journal/RETROSPECTIVE.md` — summary + link added.
