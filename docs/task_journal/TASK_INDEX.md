# Task index

One row per task. Links to the existing evidence bundle(s) rather than
duplicating them. `prompt` column: `AVAILABLE` (captured in this journal's
`entries/`) or `NOT_AVAILABLE` (not separately captured as a file for that
task — its own audit/research document's prose is the only record, and is
linked instead of reconstructed). Full narrative history predating this
journal (Tasks 1–116) lives in `docs/research/TALONX_RESEARCH_LEDGER.md`
and `docs/RESEARCH_STATUS.md` — linked here, not repeated.

| task | date | branch(es) | verdict | evidence | prompt |
|---|---|---|---|---|---|
| 1–116 | 2026 (various) | mixed | see `docs/RESEARCH_STATUS.md` §Task-by-task | `docs/research/TALONX_RESEARCH_LEDGER.md`, `docs/RESEARCH_STATUS.md` | NOT_AVAILABLE (predates this journal; not reconstructed per this journal's own scope) |
| 117 (overnight release closure) | 2026-09-10/11 | release (`research/talonx-strategy-validation`) | `READY_FOR_CONTROLLED_ACTIVATION_REVIEW` | `docs/audits/task117_overnight_release_closure/` | NOT_AVAILABLE |
| 117 (final-activation corrections) | 2026-09-11 | release | corrections applied, `827366f` | `docs/audits/task117_final_activation_corrections/` | NOT_AVAILABLE |
| 117 (controlled activation) | 2026-09-11 | release | `LIVE_PAPER_SESSION_STARTED`, `fb4b071` | `docs/audits/task117_controlled_activation_2026-09-11/` | NOT_AVAILABLE |
| 118 (dataset inventory) | 2026-09-11 | research (`research/talonx-profitability-2026-09`) | inventory complete, `863d1ed` | `docs/research/TASK118_INVENTORY.md` | NOT_AVAILABLE |
| 118 (Deliverable A baseline) | 2026-09-11 | research | `BASELINE_COMPLETE` (small-sample), `c85a72f` | `docs/research/TASK118_BASELINE_A_RESULTS.md` | NOT_AVAILABLE |
| **118 (profitability diagnostics + task journal)** | 2026-09-11 | research | see `entries/2026-09-11_task118_profitability_diagnostics/outcome.md`, commit `c0cfa5d` | `docs/research/TASK118_BASELINE_RECONCILIATION.md`, `TASK118_ORIGINAL_SELECTIVITY.md`, `TASK118_EXPERIMENTAL_OUTCOMES.md`, `TASK118_NEXT_EXPERIMENT.md`, this journal | **AVAILABLE** — `entries/2026-09-11_task118_profitability_diagnostics/request.md` |
| **118A (priority hotfixes + controlled restart)** | 2026-09-11 | release (`research/talonx-strategy-validation`) + this journal (research) | `HOTFIX_DEPLOYED_AND_RESTART_VERIFIED`, deployed `c88f4d4` | `docs/audits/task118a_priority_hotfixes_2026-09-11/` (release branch), `docs/research/TASK118A_RESEARCH_CORRECTIONS.md` (this branch) | **AVAILABLE** — `entries/2026-09-11_task118a_priority_hotfixes/request.md` |
| **118B (exit-timing, equity correction, readiness)** | 2026-09-11 | research (+ release doc-only `813bfc0`) | `VALID_UNDER_EXISTING_PAPER_POLICY` (VRT); runtime unchanged (no defect proven) | `docs/research/TASK118B_EXIT_TIMING.md`, `TASK118B_EQUITY_RECONCILIATION.md`, `TASK118B_READINESS.md`, `TASK118B_RESEARCH_PROTOCOL.md` | **AVAILABLE** — `entries/2026-09-11_task118b_exit_equity_readiness/request.md` |
| **118C (feed incident, recovery, readiness)** | 2026-09-11 | research (+ release doc-only `0209ada`) | `RECOVERED_TRANSIENT`; runtime unchanged (no defect proven) | `docs/audits/task118c_feed_incident_20260911T143728Z/INCIDENT_REPORT.md` (release branch) | **AVAILABLE** — `entries/2026-09-11_task118c_feed_incident/request.md` |
| **118D (matched-scope comparison + live evidence)** | 2026-09-11 | research | A vs B vs C comparison, runtime unchanged | `docs/research/TASK118D_SCOPE_COMPARISON.md`, `TASK118D_LIVE_EVIDENCE.md` | **AVAILABLE** — `entries/2026-09-11_task118d_scope_comparison/request.md` |
| **118E (readiness/SPCX/decision)** | 2026-09-11 | research | `ONE_TESTABLE_HYPOTHESIS` (exploratory); runtime unchanged (no defect proven) | `docs/research/TASK118E_READINESS_SPCX_DECISION.md` | **AVAILABLE** — `entries/2026-09-11_task118e_readiness_spcx_decision/request.md` |
| **118F (resilient warmup + volatility test)** | 2026-09-11 | release (deployed `5c0b3f3`) + research | Deployed live, readiness 30/43→42/43; `EXPLORATORY_ASSOCIATION_SUPPORTS_ONE_FURTHER_TEST` | `docs/audits/task118f_resilient_warmup/` (release branch), `docs/research/TASK118F_VOLATILITY_RETURN_TEST.md` (this branch) | **AVAILABLE** — `entries/2026-09-11_task118f_resilient_warmup_volatility_test/request.md` |
| **118G (final acceptance + handoff)** | 2026-09-11 | research (+ release doc-only `d4177b3`) | `PRE_EOD_ACCEPTANCE_COMPLETE`, 43/43 readiness confirmed live | `docs/research/{TASK118G_FINAL_ACCEPTANCE,SESSION_2026-09-11_OUTCOMES,NEXT_SESSION_HANDOFF}.md` | **AVAILABLE** — `entries/2026-09-11_task118g_final_acceptance_handoff/request.md` |
| **118H (canonical EOD closure + product roadmap decision)** | 2026-09-11 | research (release unchanged, `5c0b3f3`/docs `d4177b3`) | `EOD_PASS_WITH_FINDINGS`; SPCX +$50.30 unrealized, open, carries to Monday; Option 3 (attributable per-lane reconciliation surface) selected as next task | `docs/research/{SESSION_2026-09-11_FINAL,NEXT_SESSION_HANDOFF,PRODUCT_REQUIREMENTS_AND_NEXT_DECISION}.md` | **AVAILABLE** — `entries/2026-09-11_task118h_eod_closure_roadmap/request.md` |
| **119 (attributable paper-performance dashboard)** | 2026-09-11 | release hotfix `hotfix/task119-paper-performance-dashboard` (not merged, candidate), `d65a410` | `PAPER_PERFORMANCE_SURFACE_ACCEPTED`; 18/18 tests, 6/6 rendered fixtures, 27/27 field checks match | `docs/audits/task119_paper_performance_dashboard/TASK119_PAPER_PERFORMANCE_ACCEPTANCE.md` (release branch) | **AVAILABLE** — `entries/2026-09-11_task119_paper_performance_dashboard/request.md` |

## Cross-branch note

This journal lives on the research branch. Task 117's three audit bundles
above live on the release branch (`research/talonx-strategy-validation`) —
linked by path for a reader with that branch checked out; this journal does
not merge or copy their content across branches.
