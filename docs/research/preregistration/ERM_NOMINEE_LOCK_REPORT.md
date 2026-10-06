# ERM nominee: decision and lock report (2026-10-06)

**Verdict: `LOCKED_AWAITING_SEPARATE_GO`.** Owner decisions D1, D2, D4–D7 are recorded, and the final protocol and
the reviewed implementation are locked. Both locks verify from a fresh clone.

**This is NOT a GO.**
- No release is active and no guard has been lifted.
- No Task75 consumption entry exists.
- No validation-window data has been acquired, and no validation has run.

Historical validation requires a separate, explicit GO. That GO must instantiate the reference date R in the locked
scope template.

**Declared acquisition prerequisite.** S&P coverage through 2026-09-30 is unconfirmed until the first authorised
request (S0). If it is insufficient, the run ends ACQUISITION_BLOCKED: no scoring, no FAIL, no substitute source and
no window switch.

## Records

| Record | Path | sha256 |
|---|---|---|
| Final protocol | `docs/research/preregistration/ERM_NOMINEE_PROTOCOL_FINAL.md` | `7e71fabc9ed68e6de99981839a97d75d235792e1ca57decd98bd735194613043` |
| Owner decision record | `docs/research/preregistration/ERM_NOMINEE_OWNER_DECISION_RECORD_B.md` | `33095e0e0329907ae070de0c2e893f71cf3b7bfec1fdda3c98357f035d250355` |
| Decision fields | `docs/research/preregistration/ERM_NOMINEE_OWNER_DECISIONS_B.json` | `b430eead25ae05cbf0ec6172fb4667de15274b75a6733abe78fc50a0824c09b3` |
| Protocol lock | `docs/research/preregistration/ERM_NOMINEE_PROTOCOL_LOCK.json` | `55a31d24a7d1e9d2eecc03073af0e29e89bc2f8bc1530798c6b14cc6e0440829` |
| Implementation lock | `docs/research/preregistration/ERM_NOMINEE_IMPLEMENTATION_LOCK.json` | `1584e460676f3d3703588b05860f45a44f4b90905d692d9307bc1ad02734a0b3` |
| Implementation aggregate | built from commit `d23d9fe44120b12b8038267cae282fa7230925ef` | `ce924d902d620a873d6bf693e0e590b6ac066d4ce8117deddf04ff96a942c75e` |
| Config hash (window B, decided) | `config.ValidationConfig("B", decisions)` | `d8ad21af7d7f646373947041b8cd86e76057889d0386e099cd0307710c8bdf90` |
| Authoritative V2.1 rules | spec / freeze record / `v2_rules.py` | `b805ce41…2ded2` / `8581e3d3…b31f5` / `a4e3b82d…548ef` |
| Preserved drafts | r9 / r10 | `fa59a9ca…a3a32b` / `e6385dd0…9929` |

**Config.** The configuration bound by the lock:

- hypothesis `GAP_UP_10|SHORT|H10|L1`; spec and rules V2.1;
- window B, 2024-01-02..2026-09-30;
- stock cost 30 bps; ETF cost 4 bps, with 0/12/20 descriptive;
- floor 100 valid events / 40 distinct entry dates, adopted;
- D2, D6 and D7 true.

**Scope template.** Locked with R symbolic:

| Category | Template |
|---|---|
| bars | 2023-11-01..2026-09-30 |
| corporate_actions, etf_cash_dividends | 2024-01-01..2026-09-30 |
| form345 | 2018-01-01..2026-09-30 |
| master_idx | 2024-01-01..2026-09-30 |
| filing_headers | history..2026-09-30 |
| assets_current, sec_reference_current, submissions, sp500_pit | history..R+1 |
| identity_renames | 2026-10-01..R |

The GO instantiates R, and `release.validate_request` requires the release scope to equal `scope_envelopes(B, R)`
exactly. The release also refuses an implementation hash that differs from the implementation lock, and a config hash
that differs from the protocol lock.

## Byte representation and digest rules

**Authoritative bytes** are the committed git blob bytes, checked out verbatim:

- every locked path is `-text` or `text eol=lf`;
- this task added `docs/research/preregistration/ERM_NOMINEE_* -text`;
- `workflow.py` and `run.py` are now LF.

**Digest rules** (stated in full in `lock.py`):

- The implementation aggregate covers the package and frozen modules only. It excludes documents, tests and both lock
  records.
- The protocol lock covers neither itself nor the implementation lock.
- The implementation lock covers neither itself nor the protocol lock.
- A GO binds sha256(protocol lock) and the implementation aggregate.

**Superseded hash citations, kept as history.** Two earlier review JSONs had hashes taken from an autocrlf CRLF working
copy:

- `ERM_NOMINEE_LOCK_AND_GO_PACKAGE_REVIEW.json`: `61cb7f50…` cited; committed blob `8552181e…`.
- `ERM_NOMINEE_VALIDATION_PACKAGE_REVIEW.json`: `242f3b14…` cited; committed blob `1edcf75f…`.

The CRLF values appear in no committed record. The committed blob hashes are authoritative, and both files now check
out byte-exact. No historical record was edited.

## Verification

| Check | Result |
|---|---|
| Lock verifier, working tree | PASS |
| Fresh clone of the pushed branch (`core.autocrlf=true`) | verifier from the clone's own package: **PASS**; `git status` clean (0 lines); every hash in the tables above reproduced, including r9, r10, the final protocol, the decision record, both locks and the replay manifest `3824fa6a…`, which equals development parity |
| Focused tests in the fresh clone | **129 passed**: acquisition review, acquisition E2E, workflow, plumbing |
| Full ERM regression (worktree) | **222 passed** |
| Development parity | Not rerun. This round changed no manifest construction (builder unchanged); the latest replay `REPLAY_PARITY_PASS` (`dev_replay_review`) stands. |

**New tests.**

D6a, the attempt budget:

- a blockage consumes no scoring run, and one retry with a reason then completes;
- a retry without a reason is refused;
- a second failure stops;
- a new or renamed directory, or a restarted process, cannot reset the budget;
- there is no retry after outcome exposure, even in a new directory;
- a retry outside the R + 1 day envelope is refused before it starts and consumes nothing;
- transport retries are not attempts;
- the ledger is required.

S&P, against the real 450-ticker floor:

- a snapshot dated at the window end is accepted;
- a snapshot dated after it is accepted;
- a last change before the window end is INSUFFICIENT;
- event-style rows are FORMAT_NOT_FULL_SNAPSHOTS;
- non-increasing dates are rejected.

## State confirmations

- `production_guard` returns the always-refusing ValidationGuard.
- No release store, release authorisation, GO record or Task75 consumption entry exists.
- `run.py --window B --execute` stops at the guard before any request or run state.
- The real ERM guard state is `b512322d…`, unchanged.
- Live runtime: not touched.
