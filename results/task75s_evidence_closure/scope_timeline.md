# Task 75S — Stage 2: Scope Timeline (exact commit-level chronology)

| Commit | Timestamp (local, repo) | Timestamp (UTC) | Content |
|---|---|---|---|
| `13328eb` | 2026-08-27 07:12:32 +0100 | 06:12:32 | Task 73S Stage 1 (fixture repair) |
| `848de0d` | 2026-08-27 07:53:38 +0100 | 06:53:38 | Task 73S final (Stage 2-4 evidence) -- **Task 74S's starting baseline** |
| `4a3fc3e` | 2026-08-27 08:09:25 +0100 | 07:09:25 | Task 74S Stage 0/1 (preregistration, committed BEFORE the replay) |
| (launch) | -- | 07:13:10 | Task 74S replay launched (background), per `stage3_replay_launch_manifest.json` |
| `f7ff865` | 2026-08-27 08:14:03 +0100 | 07:14:03 | Task 74S Stage 2 (integrity checks + launch manifest, committed minutes after launch) |
| (replay completes) | -- | ~14:27 | Replay finishes (`run_timestamp` in `task74s_10symbol_full_summary.json`); actual runtime ~7h14m, not the ~234min estimate (hardware/environment variance, not a correctness issue) |
| (Task74S own full-suite check) | -- | ~14:30-14:45 | `pytest -q` hits the same 2-module collection error found by this audit; re-run with `--continue-on-collection-errors --ignore=...` → 2168 passed, 1 skipped, 10 xfailed |
| `45814d2` | 2026-08-27 15:48:39 +0100 | 14:48:39 | Task 74S Stage 3-5 evidence (final commit) |
| (this audit) | -- | ~15:50 onward | Task 75S Stage 0-1 work; dependency repair applied |

## Correction: the "two days ago" claim
Task 74S's `execution_journal.md` and `task74s_summary.md` stated the `exchange-calendars` collection
error was a change from "Task 73S's clean run **two days ago**." **This is factually wrong and is
withdrawn.** `848de0d` (Task 73S's final commit, containing that clean full-suite run) and Task 74S's
own full-suite check are **on the same calendar day** (2026-08-27), roughly **7.5 hours apart**, not two
days. This appears to have been an unverified assumption carried over from this session's own prior
(compacted) context rather than something checked against `git log` timestamps at the time. See
`task74s_evidence_addendum.md` for the formal correction.

## Window scope: requested default vs. executed scope
Task 72O and Task 73S both consistently used **2025-08-15 to 2025-12-31** as their "development period"
(Task 72O's own `stage3_preregistration.json` labels it `regime: range_chop_2025`, explicitly separate
from a deferred "validation_period"). Task 74S's own preregistration (`4a3fc3e`,
`evaluation_protocol.md` §3) instead adopted the **full available common history**
(2025-08-15 13:03 UTC → 2026-08-14 23:58 UTC, ~1 year, 13 calendar-month buckets) -- a materially wider
window than the established development-period convention.

**This was preregistered before the replay ran** (satisfying the letter of "preregister before
execution"), but per this task's own instruction, **preregistration does not itself authorize a
departure from the requested scope**. The written justification at the time
(`evaluation_protocol.md` §3: "satisfying this task's 'more symbols and/or a longer window' mandate
with both") was **my own interpretive judgment**, not a citation of repository-documented provenance
establishing "the full available year" as itself a frozen research window -- unlike the universe
choice (§ see `universe_selection_audit.md`), which WAS grounded in strong, explicit ledger provenance.

**Classification: PREREGISTERED BUT WIDER THAN THE ESTABLISHED DEFAULT DEVELOPMENT-PERIOD CONVENTION.**
See `scope_comparison.csv` for the exact requested-vs-executed breakdown and the outcome-invariance
check (restricting to just the 2025-08-15..2025-12-31 sub-range does not change the zero-trade result).
