# Task 130A — corrected economics, identity reconciliation, and final gate

Full outputs: `results/task130a_corrected_replay/{summary,corrected_stats,
identity_reconciliation,episode_comparison,daily_marks}.json` (compact
copies in `docs/research/evidence/task130a/`).

## Per-episode comparison vs. Task 130 (Part 9)

| | count |
|---|---:|
| Unchanged (identical episode_id, timing, P&L) | **153 of 153** |
| Newly excluded | 0 |
| Newly admitted | 0 |
| Changed timing/quantity/P&L | 0 |
| Identity-related difference | 0 |

**The corrected, genuinely in-line-gated replay produced the EXACT
SAME 153 closed trades as Task 130's post-hoc-filtered Track B** — same
`episode_id`s, same entry/exit sessions, same P&L to full precision.
This is explained, not assumed: Task 130's own funnel already showed
the $300k/20-slot capacity was never binding (minimum cash observed
$181,392.76 of $300,000) — with capacity never actually constraining
either implementation, an in-line gate and a post-hoc filter converge
on the same admitted set. **The REJECTION reasons for non-entered
episodes do differ** (this driver: `SKIPPED_NO_PRIOR_INTENT`=7 vs.
Task 130's implicit 4 "cold-start" trades that were entered-then-
excluded) — because capacity is now checked at INTENT-CREATION time
(a new rule this repair introduces), a few episodes that previously
reached the entry loop under the permissive policy are now stopped one
step earlier, at intent creation, for the same underlying reason. This
is a genuine, explained implementation difference with zero effect on
the final admitted set or its economics in this specific run.

**This is not evidence the two approaches are always equivalent** — it
reflects THIS window's own capacity slack, not a general property of
the correction.

## Historical economic result (unchanged from Task 130, now on a verified implementation)

- N=153 closed trades, 106 distinct issuers.
- **Net mean +2.0219%/round trip** (clears +0.50%), median +1.674%,
  win rate 62.75%, PF 2.1399.
- Issuer-block bootstrap 95% CI **[+0.7222%, +3.3989%]** — excludes
  zero.
- Date-block (19 monthly blocks) bootstrap 95% CI **[+0.5723%,
  +3.4573%]** — excludes zero. **Both methods agree.**

## Concentration and stability (Part 8)

**Original, preregistered, trade-count-ranked** (Task 130's own
convention, preserved unchanged): excl. top-1 (SPG) → +2.1629%; top-3
(SPG, TPL, LUV) → +1.9907%; top-5 → +1.9523%. Sign never reverses.

**Supplemental, NOT-preregistered, P&L-contribution-ranked** (this
task's own completion test, added alongside — never substituted):
ranking by aggregate POSITIVE net dollar P&L, deterministic tie-break
(P&L desc, symbol asc): excl. top-1 (LB) → **+1.7911%**; top-3 (LB, EL,
LUV) → **+1.4560%**; top-5 (LB, EL, LUV, SEDG, BBWI) → **+1.1421%**.
**Sign never reverses, but the magnitude declines more steeply under
this lens** than under trade-count ranking — a real, disclosed
difference: a meaningful share of the aggregate P&L is concentrated in
a handful of large winners (69 of 106 issuers are net-positive
contributors; removing the top 5 of those removes roughly a third of
the point estimate's magnitude, from +2.02% to +1.14%). The result
remains positive throughout both lenses, but this concentration
pattern is named explicitly, not smoothed into a single number.

**Calendar half-year stability, UNCHANGED, period boundaries not
moved**: 2024H2 +4.26% (n=21), 2025H1 +2.72% (n=47), 2025H2 +2.09%
(n=52), **2026H1 −0.50% (n=33)** — three of four independently
positive; the negative most-recent half-year remains visible.

## Daily marked equity and drawdown (Part 6)

- **Max drawdown (true daily mark-to-market): −2.7478%** — peak
  2026-03-04, trough 2026-03-20, **NOT recovered within the replay
  window** (the window ends 2026-03-31, 11 sessions after the trough —
  too little time to determine whether it would have recovered; this
  is an honest boundary effect, not a claim of failure to recover).
  This is measurably worse than Task 130's flawed −2.25%
  "realized-equity" figure, as expected — the correct measure now
  captures intra-holding unrealized fluctuation the old one could not.
- Ending cash = ending equity = **$330,935.40** (0 open positions at
  window end — natural completion, not forced).
- Capital utilization: 85.99% of sessions had ≥1 open position
  (frequency measure — see the acceptance document for why this is not
  the same as an invested-capital/equity exposure ratio, which was not
  computed).
- No unavailable mark was silently defaulted to zero or excluded — any
  stale mark is flagged per-session in `daily_marks.json`.

## Issuer identity reconciliation (Part 7)

35 ambiguous symbols within the frozen 626-name Discovery Universe v1
(re-verified, matches Task 130's own manifest exactly): **19
classified LIKELY_LEGITIMATE_HISTORICAL_IDENTITY_CHANGE** (sequential,
non-overlapping CIK date ranges with materially different issuer
names — consistent with a rename/re-incorporation), **2 classified
MULTIPLE_SECURITIES_SAME_ISSUER_NAME**, **14 classified
MAPPING_DEFECT_OR_UNRESOLVED_OVERLAPPING_DATES** (genuinely ambiguous
even after this analysis — reported as incomplete identity coverage,
NOT resolved, and NOT used to shrink the 626-name population
definition).

**Of the 8 ambiguous symbols that actually had an entered trade** (CZR,
DOC, LB, MRVL, MTCH, PCG, TPL, WTW) — **3 of these (LB, PCG, TPL) fall
in the "unresolved" bucket at the symbol level**. Critically, checked
directly against the actual trade data (not assumed): **for every one
of the 8, the specific traded episode's entry date matches exactly ONE
issuer_cik's own filing date range** (`single_cluster_spans_multiple_ciks
== False` for all 8) — **proving no episode/cluster combined filings
from two different issuers under a shared ticker**, even where the
symbol's broader historical identity remains ambiguous. Classification
was made from accession-level `issuer_name`/date-range evidence alone
— never by trade profitability.

**Coverage honestly reported**: identity is NOT fully resolved for
14/35 ambiguous symbols in general (though the 3 of those with actual
trades are specifically cleared of cluster-merge risk). This is named
as a residual, incomplete-coverage limitation, not silently smoothed
over or used to shrink the population.

**Correction to Task 130's own text**: Task 130's economic-decision
document stated the prior Task 112R headline (+1.01%/10td) belonged to
"the 39-name live scope." **This is corrected: Task 112R's +1.01%
figure is the FULL-PANEL, runtime-semantics-corrected result (N=756,
per `docs/research/TASK112R_...` / the release-branch rehearsal), not
a 39-name-scope-specific number** — the 39-name live-scope's own
corrected figure is Task 120A-C's N=57/net@20bps=−0.85% result. Neither
figure is what produced this task's PASS — restated for the record,
not used to justify anything here.

## Final gate (Part 10) — separate acceptances

| gate | result |
|---|---|
| **Historical economic result** | Net +2.0219%/round trip, N=153 — clears +0.50% |
| **Prospective-policy implementation acceptance** | **ACCEPTED** — genuinely in-line-gated (Part 2), tested (9/9 fixture tests), phantom-exit-proof, no-partial-fill enforced |
| **Timestamp-evidence limitations** | Session-granular only, date-only filings, explicitly not minute-level observed dissemination — disclosed, not resolved (cannot be resolved from this dataset) |
| **Portfolio/risk acceptance** | Daily mark-to-market drawdown −2.7478%, NOT recovered within window (boundary effect); capacity never binding in this run; no user-approved risk tolerance exists or is invented here |
| **Identity/coverage acceptance** | **PARTIAL** — 21/35 ambiguous symbols resolved, 14/35 remain genuinely unresolved (though 0 actual trades are compromised by any of them, proven directly) |
| **Statistical criterion** | Both issuer-block and date-block 95% CIs exclude zero and AGREE |
| **Concentration/stability** | Both original (trade-count) and supplemental (P&L-ranked) sensitivities stay positive; no single half-year is the sole source of the result |

### Verdict

> **`PASS_FOR_INTEGRATION_REVIEW`**

All required economic/statistical/sensitivity/stability gates are met,
on a NOW-CORRECTED, genuinely gated, phantom-exit-proof, daily-marked
implementation — reaffirming (not merely carrying over) Task 130's
original number, which turned out, in this specific window, to be
numerically identical once properly gated. **This is still not a
deployment recommendation.** Two gates remain explicitly PARTIAL/
disclosed rather than fully clean: (1) 14/35 ambiguous issuer
identities remain unresolved at the symbol level (though proven not to
have contaminated any actual trade), and (2) this driver's own
restart/idempotency and invested-capital-exposure measures were not
built within this task's budget — named as residual gaps for a later
task, not silently assumed away.

## One next action

No further repair task is proposed. The remaining named gaps (14
unresolved identities at the symbol level; restart/idempotency
testing; an invested-capital exposure-ratio metric) are small, bounded,
and appropriate for the SAME later, separately-authorized integration-
review task Task 130's own handoff already named — not a new research
cycle. Task 129's broader alpha-research pause remains in effect for
every other mechanism.
