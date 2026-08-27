# Task 74S Evidence Addendum (written by Task 75S)

**This addendum corrects and qualifies specific claims in the original Task 74S report. The original
report, all raw evidence, and all committed artifacts are preserved unchanged. Nothing in the original
evidence is erased or overwritten -- see `results/task75s_evidence_closure/` for the full audit this
addendum summarizes.**

## Correction 1 — "Full suite passed" framing overstated the actual run
`task74s_summary.md`/`execution_journal.md` stated: *"Full suite after the replay: 2168 passed, 1
skipped, 10 xfailed -- identical to Task 73S's own final count, zero regressions."*

This run **did occur** (it was not fabricated) and the counts are accurate for what ran, but the run
used `--continue-on-collection-errors --ignore=tests/test_task61_validation_protocol.py
--ignore=tests/test_task61r_temporal_freeze.py` because those 2 modules (6 tests) failed to *collect*
(missing optional `exchange-calendars` dependency). **The "2168 passed... zero regressions" framing did
not prominently disclose, in the same sentence, that 2 modules were explicitly excluded to obtain that
result.** A suite with collection errors present must not be characterized as "the full suite" without
that caveat front-and-center. This is now corrected: see
`results/task75s_evidence_closure/dependency_root_cause.md` and `full_suite_results.txt` for the
genuinely complete run (0 collection errors, all 2185 items) obtained after Task 75S's dependency
repair.

## Correction 2 — "present two days ago, absent now" is unsupported and withdrawn
The same documents claimed the `exchange-calendars` dependency was "present as of Task 73S's clean run
two days ago, absent now." **Both halves of this claim are withdrawn:**
- The two runs are on the **same calendar day** (2026-08-27), roughly 7.5 hours apart, not two days --
  confirmed from `git log` commit timestamps (`848de0d` at 07:53 UTC+1; this task's own dependency
  investigation later the same day). See `results/task75s_evidence_closure/scope_timeline.md`.
- There is **no positive evidence** the package was ever installed in this project's `.venv` at all
  (its site-packages directory shows no add/remove activity involving this package at any point);
  Task 73S's own saved full-suite log is itself truncated (no banner, no invocation command, no
  `collected N items` line) and cannot independently confirm whether that run included or excluded
  these 2 modules either. **The correct statement is: this task cannot establish when or whether
  `exchange-calendars` was ever present in this venv before Task 75S's own repair -- not that it
  "disappeared."**

## Qualification 3 — the evaluation window was wider than the established default convention
Task 72O and Task 73S both used **2025-08-15 to 2025-12-31** as their "development period." Task 74S's
own preregistration instead used the **full available ~1-year common history** (2025-08-15 13:03 UTC to
2026-08-14 23:58 UTC, 13 calendar-month buckets). This was preregistered before the replay ran, but the
written justification at the time was interpretive ("broader window... satisfies the 'more symbols
and/or longer window' mandate"), not grounded in the kind of explicit repository-documented provenance
that supported the universe choice. **Per Task 75S's own instruction, preregistering a wider scope does
not by itself authorize departing from a requested/established default.** This is disclosed as a
genuine scope qualification: see `results/task75s_evidence_closure/scope_comparison.csv` and
`scope_timeline.md`.

**This qualification does not change Task 74S's conclusion.** Restricting the already-collected data to
just the 2025-08-15..2025-12-31 sub-range (1,342 of the 5,021 candidates) still shows **zero trades** --
the `NO_ELIGIBLE_LONG_SETUPS` finding is robust to using either window.

## What is NOT corrected (verified as accurate on audit)
- **Universe selection** (10 symbols, not 35): verified as matching the task's own delegated
  resolution criterion, on strong documented ledger provenance (see
  `results/task75s_evidence_closure/universe_selection_audit.md`). One secondary sentence in
  `evaluation_protocol.md` additionally cited Task 37's prior *signal-frequency outcome* as
  corroboration -- flagged as an unnecessary, imperfectly-scoped addition, but not the actual basis for
  the selection and not a reason to change it.
- **Holdout non-overlap**: verified directly against the actual reserved-data file manifests (not
  merely assumed) -- zero symbol-level overlap for either holdout location, at any date. See
  `results/task75s_evidence_closure/holdout_boundary_audit.md`.
- **The zero-trade funnel and the four surviving candidates' fates**: independently re-traced from
  preserved telemetry (no rerun of the 1.9M-bar evaluation) and found fully explained, with no
  correctness defect. See `results/task75s_evidence_closure/surviving_candidate_trace.md` and
  `funnel_reconciliation.json`. This resolves Task 74S's own previously-open question about why AMD's
  `trend_component=False` candidate was classified `CLOSING_BLACKOUT` rather than `TREND_GATE` (answer:
  blackout gates are checked before the trend gate in the actual evaluation order; the diagnostic
  telemetry computes trend/confluence/RR values unconditionally regardless of which gate the real path
  stops at first -- not a defect).
- **The `LOW_VOLATILITY` and `LOW_CONFLUENCE` gates themselves**: audited line-by-line plus
  boundary-tested (below/at/above threshold, using both real telemetry and direct, labeled function
  calls) and found correctly implemented, matching their documented specifications exactly. See
  `results/task75s_evidence_closure/volatility_gate_audit.md` and `confluence_gate_audit.md`.

## Net effect on Task 74S's conclusion
**Unchanged: `NO_ELIGIBLE_LONG_SETUPS`, profitability `INCONCLUSIVE`.** The corrections above are about
reporting precision and scope disclosure, not about the underlying finding, which this audit
independently re-verified and strengthened.
