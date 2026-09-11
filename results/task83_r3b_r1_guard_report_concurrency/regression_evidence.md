# Task 83-R3B-R1 Regression Evidence

## Deterministic pre-fix reproduction

Run `20260830_134944` coordinated two local writer threads without opening a network connection. The first thread held a serialized one-event payload, the second published a two-event payload, and the first then replaced it with the stale payload.

- Result: 1 failed, exit code 1
- Expected permitted-loopback count: 2
- Durable report count: 1
- Failure: `assert 1 == 2`
- Global guard: initialized, reconciled, zero unexpected attempts, zero initialization failures

The earlier `20260830_134817` harness attempt passed because simultaneous replacement of the shared source did not fail on that scheduling instance. It is preserved as a non-reproducing harness diagnostic and was superseded by the deterministic stale-payload barrier.

## Repair-development diagnostics

All diagnostic artifacts are preserved and are not qualification runs:

- `guard_and_dashboard_stress_20260830_135335_187`: 34 passed, 3 failed; proved transient Windows replacement denial remained after unique temp names.
- `guard_and_dashboard_stress_final_20260830_135558_123`: 37 passed, 1 failed; gapless readers prevented replacement progress.
- `guard_and_dashboard_stress_accepted_20260830_135701_639`: 37 passed, 1 failed; raw readers received transient Windows sharing denial.

These observations produced the bounded replacement retry and the explicitly single-process locked reader API. No production or dashboard code was changed.

## Accepted verification sequence

| Run | Result | Exit | Expected blocks | Unexpected | Init failures | Reconciled | Loopback |
|---|---:|---:|---:|---:|---:|---:|---:|
| Deterministic repaired regression | 1 passed | 0 | 0 | 0 | 0 | yes | 0 |
| Final concurrency and dashboard stress | 38 passed | 0 | 4 | 0 | 0 | yes | 78 |
| R3B Phase 1 equivalent | 73 passed | 0 | 4 | 0 | 0 | yes | 57 |
| R3B Phase 2 equivalent | 89 passed | 0 | 0 | 0 | 0 | yes | 11 |
| R3C focused run 1 | 262 passed | 0 | 4 | 0 | 0 | yes | 113 |
| R3C focused run 2 | 262 passed | 0 | 4 | 0 | 0 | yes | 113 |
| Final complete concurrency file | 21 passed | 0 | 0 | 0 | 0 | yes | 0 |

The 21-test concurrency file covers exact concurrent counters, mixed permitted/expected events, concurrent complete reads, unique writer filenames, successful cleanup, scoped failure cleanup, transient replacement recovery, persistent failure visibility, unexpected-attempt classification, and 12 repetitions of the original dashboard route contract.

No accepted run left a writer-owned report temporary file. The deliberately unrelated cleanup sentinel was proven preserved during writer failure and then removed by test teardown. All task-owned pytest base directories were removed only after durable raw evidence was retained.

## Raw artifact hashes

SHA-256:

- Pre-fix failure output: `98141b93e05e4123f2276bf418d4fbb67471892f6ec67b4f93bb257d4aff8bf4`
- Pre-fix exit file: `f1b2f662800122bed0ff255693df89c4487fbdcf453d3524a42d4ec20c3d9c04`
- Final stress output: `2458584678a6eebe09b1183ecafabc9a48daf9115bcea235fe994b15d8cedbc2`
- Final stress guard report: `0e017d27d9d481a20bbd831565a0e06dae59018fbb6f10c1352d685b363661c3`
- R3B Phase 1 report: `5c8df6b564df86275ecb5afc74eb90cca42194fe92dfd5aad49b00d5558d5612`
- R3B Phase 2 report: `37f811b033813f6de1c19551720f5da8400664c86bf821f5d3298964694ef771`
- R3C focused run 1 report: `1eb7208355db19015a5dd2c71399bbb071bfc722d538578495d0a36dc60cf7ac`
- R3C focused run 2 report: `1eda770b9eac9e9c4c818b0bc16ffdc258fe813d2e36816339c82ac1d551fda0`

Raw logs remain ignored under `results/task83_r3b_r1_guard_report_concurrency/raw_test_output/`.
