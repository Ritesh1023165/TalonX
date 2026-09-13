1. **Statistical and product verdicts**: Statistical (Cohort A,
   primary) = **`INCONCLUSIVE`** (95% CI [−0.7946%,+0.3458%] includes
   zero). Product = **`DO_NOT_ADVANCE`** — negative on both the
   incremental (−0.2284%) and absolute (−0.1196%) basis, CI includes
   zero and does not clear the ±10bps materiality band in either
   direction; the frozen protocol's own "if the result is negative or
   economically inadequate, close this contract" applies. All 4
   cohorts individually are `INCONCLUSIVE` (every CI includes zero).

2. **SHAs**: release verified `f28986999eec5e313cfc89db24e4dbacfb378891`
   unchanged (research-only task). Research `79c3591` (confirmed exact)
   → **`<this commit>`**, pushed to `research/talonx-profitability-2026-09`
   only. Intermediate checkpoint: protocol freeze committed and pushed
   as `bfd1205` before any return was computed.

3. **Acquired coverage, feed provenance, exclusions**: 15 symbols (12
   original Track-B + BABA/SHOP/SPCX), `feed=sip`/`adjustment=raw`,
   2022-12-01→2025-08-14, 60/60 partitions acquired with 0 failures.
   Feed identity of the legacy `task93_canonical_v1` dataset resolved
   from acquisition code (no `feed` param ever passed) + confirmed via
   a bar-for-bar-matching live probe: it is **SIP**, not IEX as
   previously suspected (Task 124). SKHY and BLSH excluded from the
   added cohort on coverage grounds (post-window listing / near-zero
   prior history), decided before any return.

4. **Contract fidelity and timing validation**: Task 123 Track B's
   decision rule (15:50 ET cutoff, same-time-of-day cumulative volume,
   2.0× trigger, 2-min delay, 15:52 ET reference entry, next-session-
   open reference exit, 5bps cost, ±10bps materiality, date-block
   bootstrap seed 123123) carried unchanged — no substitution. Cohort D
   (original sub-window, new verified-SIP data) reproduces Task 123's
   original 579/31/−0.5504%/[−2.1445%,+1.2090%] numbers **bit-for-bit**,
   confirming both feed consistency and zero implementation drift.

5. **Corporate-action and cost treatment**: raw/unadjusted bars
   correctly show AVGO's (2024-07-15) and NVDA's (2024-06-10) real
   10-for-1 stock splits as single-bar discontinuities — confirmed
   against public split dates, not a data defect. No manual
   adjustment applied; the predeclared `EXTREME_RETURN_EXCLUSION_ABS=0.50`
   guard caught and excluded 1 observation spanning a split. Cost:
   5bps round-trip, applied once, unchanged.

6. **Original-cohort and added-cohort economics**: Cohort A (primary,
   original 12, expanded window): 3,201 eligible, 158 triggers, 12
   issuers, 542 distinct bootstrap dates — incremental −0.2284%,
   negative in all 3 calendar years (2023/2024/2025). Cohort B (added,
   secondary): 395 eligible, 31 triggers, but 58% concentrated in one
   issuer (BABA) with no stable year-over-year direction — not treated
   as a rescue for Cohort A's result.

7. **Absolute vs. incremental net returns and uncertainty**: Cohort A's
   absolute trigger net return (−0.1196%) is itself negative, not
   merely underperforming a positive control (+0.1088%) — this alone
   would fail the "economically credible positive absolute net return"
   requirement for `ADVANCE` even had the incremental CI excluded
   zero. Uncertainty via the SAME date-block joint-resampling bootstrap
   (5,000 reps, seed 123123) as Task 123, now over 542 distinct dates
   (vs. 100 previously) — a materially stronger test of the same null.

8. **Limitations and one next decision**: event-return statistics
   only, no portfolio/equity/drawdown simulation. SPCX remains
   genuinely illiquid (573/606 dates with any cutoff-window bar).
   Raw/unadjusted prices mean dividends are not reflected. Next
   decision: close the overnight-attention pre-close actionable
   candidate as tested — no further reruns of this exact contract, no
   threshold/delay/exit/subset search within this task. Track A's
   daily association remains retained, unaffected. Two untouched
   Task-122-shortlist hypotheses (52-week-high proximity, turn-of-month)
   remain available for a future task.

9. **Production preservation**: no release-branch change; no
   application process started; Redis `talonx:*` key count 0 both
   before and after; no stray/duplicate download or evaluation
   processes left running (the initial slow background evaluation run
   was explicitly stopped before being re-run, vectorized, in the
   foreground).

10. **Journal/reports**: `entries/2026-09-13_task125_extended_intraday_evaluation/`
    + `docs/research/{TASK125_FROZEN_EXTENSION_PROTOCOL,TASK125_DATA_ACCEPTANCE,TASK125_OVERNIGHT_ACTIONABLE_RESULTS}.md`
    + `docs/research/evidence/task125/*.json` +
    `research/scripts/task125_{feed_provenance_probe,acquire_intraday,merge_and_validate,overnight_evaluation}.py`
    + `tests/test_task125_evaluation_fixture.py` — all pushed
    (protocol freeze at `bfd1205`, remainder at this commit).

Priority followed as instructed: acquire → validate → evaluate → decide
— completed as one bounded task. The overnight-attention actionable
candidate is now closed on a materially larger (3,201 vs. 579
observations, 542 vs. 100 distinct dates, 3 calendar years vs. 7
months), independently feed-verified dataset, with the same negative/
null result Task 123 first found — not merely repeated, but stress-
tested and confirmed.
