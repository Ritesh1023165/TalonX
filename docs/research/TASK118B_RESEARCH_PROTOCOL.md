# Task 118B Part 4 — corrected observation protocol (2026-09-11)

Revises the bounded observation protocol from
`TASK118A_RESEARCH_CORRECTIONS.md` Correction 1. That correction fixed the
backwards-worded rejection criterion; this revision fixes deeper
statistical-design gaps in the same protocol, found on further review.
**Preserves INCONCLUSIVE as a legitimate, non-forced outcome throughout —
nothing here is designed to produce a pass/fail verdict on a schedule.**

## What was under-specified before

- N≥30 and a 60-day/monthly cadence were **administrative** choices (a
  floor and a "don't peek too often" habit), presented without stating
  they do **not**, by themselves, guarantee adequate statistical power or
  that the 30 observations are independent.
- No **estimand** was named — "net expectancy" was used loosely, without
  saying whether the object of interest is the **per-trade** net return
  (each of N trades weighted equally) or the **portfolio-level** return
  (time-weighted, reflecting that positions overlap and capital is
  reused) — these can disagree, especially with issuer concentration
  already observed (MSTR alone was 64% of this scope's absolute P&L).
- Repeated issuers (MSTR appeared in 4 of this scope's 10 trades) and
  overlapping holding periods were not accounted for — treating 30
  trades as 30 independent draws overstates precision when several share
  an issuer or a market regime.
- "Entirely negative CI" was correctly named as the adverse-result
  trigger, but its **scope** was not stated precisely: it is evidence
  about **this 39-name scope's own expectancy**, not, by itself, evidence
  the scope underperforms the broader validated panel — that is a
  **different, relative** claim requiring its own comparison method.
- Monthly repeated looks at the same accumulating sample is a form of
  repeated significance testing; presented without a sequential method,
  it silently inflates the true false-positive rate above whatever CI
  level is nominally used at each look.

## Corrected protocol

**Estimand (named explicitly)**: the primary estimand is the
**per-trade net expectancy** (mean net return per closed round trip,
20bps convention, matching every other Task 116/112R/118 figure) —
chosen for direct comparability with the already-published population
figures. The **portfolio-level (time-weighted) equity return** is
reported as a **secondary** estimand alongside it at every review, using
the same daily-equity-curve method introduced in
`TASK118B_EQUITY_RECONCILIATION.md` — the two are never conflated, and a
disagreement between them (e.g. per-trade expectancy negative while
time-weighted equity return is flat, or vice versa) is itself reported,
not resolved by picking whichever is more favorable.

**Clustering**: the uncertainty interval on the per-trade estimand is
computed by **issuer-block bootstrap** (resample whole issuers, not
individual trades — the same block-bootstrap machinery
`talonx_research.validation` already uses for the full-panel case,
extended here to this scope), so repeated appearances of the same issuer
do not count as independent evidence. A plain trade-level CI (ignoring
issuer repetition) may still be reported for transparency, but is
**never** the basis for the adverse-result trigger.

**Sample floor**: N≥30 **closed round trips after issuer-block
resampling still yields a stable interval** — not merely 30 raw trades.
If issuer concentration is high enough that 30 trades reduce to
materially fewer effective independent blocks, this is reported
explicitly at review time, and the floor is not considered met by trade
count alone.

**Review cadence and multiplicity**: reviews still occur no more than
monthly and not before 60 calendar days, but each review's interval is
now computed with an **alpha-spending correction** (O'Brien-Fleming-style
boundary, tightening the nominal confidence level at each successive
look) rather than a fixed-CI claim repeated at every check — this is
named explicitly as the reason the naive fixed-test framing was
withdrawn. No specific spending function is committed to a fixed
numerical schedule here (that requires knowing how many looks will
actually occur, which is not yet known); the requirement is simply that
**no review claims a fixed-α guarantee without stating the correction
applied**.

**Adverse-result trigger, restated precisely**: an issuer-block-bootstrap
CI on this scope's per-trade net expectancy that is entirely negative (at
the alpha-spending-corrected level) is evidence **about this scope's own
expectancy** — it flags the scope's composition for re-examination. It is
**not**, by itself, evidence the scope underperforms the broader
validated panel; that separate, relative claim requires a **paired
difference analysis** (e.g. a block-bootstrap CI on the *difference*
between this scope's per-trade expectancy and the full-panel's, on the
same matched window/method) — not attempted here, and not claimed.

**INCONCLUSIVE preserved**: a CI (issuer-block, alpha-spending-corrected)
that includes zero remains INCONCLUSIVE at every review before and
including the point where N≥30 effective blocks is reached — this is the
expected, default state at small N and is never treated as either a pass
or a fail.

## Estimated time to accumulate useful evidence — labelled extrapolation

This 39-name scope produced **10 closed trades over the ~19-month
2024-09→2026-03 backtest window** — ≈0.53 trades/month, all from the
already-inspected historical period, **not** a forward live rate (stated
explicitly: this is a retrospective frequency, carried forward as the
best available estimate, not a measured live rate). At that frequency,
reaching a **raw** N=30 would take **≈57 months** (≈4.75 years) of live
forward observation at the SAME 39-name scope — far longer than any
practical review horizon. Reaching a stable **issuer-block-adjusted**
effective sample (given MSTR alone contributed 4 of the historical 10)
would take **materially longer still**, since several future trades in
the same handful of frequently-clustering issuers do not each add a full
independent observation. **This extrapolation is explicitly uncertain**:
live SEC filing/insider-cluster frequency for this narrow scope could run
faster or slower than the historical rate for reasons unrelated to the
strategy itself (issuer-specific insider activity patterns, filing
timing). **Waiting for enough natural 39-name-scope trades alone is not
a viable sole profitability programme on a multi-year task horizon** —
stated plainly, not softened.

## One recommended next analysis (bounded, current-data-supported)

**Extend the already-existing full-panel block-bootstrap CI machinery
(`talonx_research.validation`, used for Task 107B/112R/116) to compute
the paired-difference comparison named above**: a block-bootstrap CI on
(39-name-scope per-trade expectancy − full-panel per-trade expectancy),
matched window (2024-09→2026-03) and method, using data **already
collected** (Task 116's full-panel replay + this scope's already-run
10-trade replay) — **no new backtest, no new data collection, no new
live waiting required.** This directly answers "does the current 39-name
scope's composition matter" using existing evidence, rather than treating
the multi-year live-accumulation wait as the only path to an answer.

**Rejection criterion for this specific next analysis**: if the
paired-difference CI is entirely negative (this scope significantly
underperforms the full panel on the same window/method), that is
evidence the scope's composition (not the frozen strategy rule) warrants
re-examination. If it includes zero, report INCONCLUSIVE — the 39-name
sample is too small relative to the full panel's variance to distinguish
the two, and no further scope change is justified by this result alone.

**Explicitly not proposed**: broad parameter optimization, removing
underperforming tickers post-hoc, or any automatic strategy promotion —
none of these follow from either outcome above.

## What this protocol still does not settle

Whether the 39-name scope reflects genuine selection value or pure
retrospective coincidence remains open regardless of the recommended
analysis's outcome — a paired-difference CI answers "is this scope
different from the panel," not "why," and not whether a *different*
39-name-sized scope would do any better or worse. That question is out of
scope for this correction.
