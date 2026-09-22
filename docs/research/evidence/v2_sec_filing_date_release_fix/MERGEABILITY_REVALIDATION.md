# PR #17 mergeability recovery and bounded revalidation

Checked 2026-09-22T23:1xZ. There was no new PR, no strategy/provider/accounting change, and no full-day session.

## 1. Root cause of the reported `mergeable = false`

| Item | Value |
|---|---|
| PR #17 head before | `5a3aed79dc3f8c8ec1c27a089ad0982f0db0b90a` |
| PR #17 base SHA (GitHub) | `3e2067c0fe2a4fd4cc69ac15b505dc2c8c7e943e` |
| `origin/main` after `git fetch` | `3e2067c0fe2a4fd4cc69ac15b505dc2c8c7e943e` (**has not moved**) |
| Merge base | `3e2067c` |
| Divergence (PR ahead / behind main) | 3 / **0** |
| Local merge simulation (`git merge-tree --write-tree origin/main HEAD`) | exit 0, **no conflicts** |
| GitHub REST `pulls/17` | `mergeable: true`, `mergeable_state: clean`, `rebaseable: true` |
| GitHub GraphQL | `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN` |
| `main` branch rules | `pull_request`, `non_fast_forward`, `deletion`, all satisfied by a normal PR merge |

**Classification: `UNKNOWN_MERGEABILITY_REASON`, not reproducible, and currently resolved.**
- There was no textual conflict and no stale base.
- There is no branch-protection block beyond the normal requirement to merge via a PR.
- The most likely explanation is GitHub's asynchronous mergeability computation. Right after a push, GitHub reports `mergeable: null` (UNKNOWN) until the background job finishes, and some clients display that as `false`. The previous push (`5a3aed7`) was seconds before that report.
- This could not be proven after the fact, so it is recorded as unknown.

## 2. Base update and conflicts

- **No update from `main` was needed. Merged: none. Rebased: none. Force-push: none.**
- Conflict files: **0**.
- The accepted commits are preserved unchanged: `44428a5` (fix + tests), `4e37e57` (evidence), `5a3aed7` (reacceptance).

## 3. Bounded revalidation on the unchanged head `5a3aed7`

| Check | Result |
|---|---|
| `tests/test_v2_sec_filing_date_admission.py` + `tests/test_pre_full_day_cleanup.py` (freeze allowlist, HEAD-descends-from-frozen, gate checks) + `tests/test_v2_final_release_acceptance.py` (release gate, fingerprints) | **84 passed, 0 failed** |
| ADC / ABCL regressions (`test_7…`, `test_8…`) | PASS (inside the above) |
| Strategy fingerprint | `e2acf6454789217e` (unchanged) |
| Provider contract fingerprint | `ac5e51aa3599d6c9` (unchanged) |
| Strategy / provider / pricing / accounting / ledger files changed vs frozen `a56ec8c` | **none** |
| Live ingestion ledger (read-only; backfill **not** re-run) | NULL `filing_date`: filings 0, transactions 0, purchase rows 0 |
| Release gate (release env, 2026-09-22T23:18:37Z) | **READY 21/21**: `authoritative_filing_date_readiness` PASS (76/76), strategy/provider FP PASS, Signal/Sentinel validation bound PASS, `lab_off` PASS, `account_blocks` PASS |
| `--verify-campaign` (not initialised) | clean; cash 100,000; reserved 0; intents 0 (pending 0); open positions 0; blocks 0; EXIT_UNRESOLVED 0; realized P&L 0; 2 processed (terminal skip) episodes |

Release semantics are unchanged from the reacceptance (`REACCEPTANCE.md` §3):
- the entry session comes from `filing_date`; `accepted_at_utc` is not used for the session date
- a missing `filing_date` fails closed
- the receipt knowledge gate is unchanged
- ADC stays `LEGITIMATE_TIMING_REJECTION`, and ABCL is unchanged
- the cold-start defect stays closed

The full suite was not re-run, because no file changed.

## 4. Verdict

**`PR17_MERGEABLE_REVALIDATED`.** PR #17 is mergeable (clean) against `main` `3e2067c`, and it is not merged. GitHub's mergeability after this evidence-only push is recorded in the task report.
