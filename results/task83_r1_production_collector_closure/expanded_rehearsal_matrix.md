# Task 83-R1 §7 — Expanded Offline Rehearsal Matrix

Exact machine results: `expanded_rehearsal_matrix.csv` (scenarios 21–33),
`retained_20_scenarios_matrix.csv` (scenarios 1–20, unchanged from Task
83, re-run under R1).

All scenarios drive the **production** surface — `CollectorService`
(async), `ComparisonCollector`, `CompareArchive`, and the dashboard
projections. No helper-only exercising. No network, no real Redis, no
production state dir. Synthetic inputs are labelled
`TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE`.

## Retained (1–20) — `tests/test_task83_offline_dual_run.py`

`20 passed`. Original 20 isolation/read-only/telemetry/process-ownership
scenarios (see the Task 83 `offline_rehearsal_matrix.csv`), unchanged.

## Added (21–33) — `tests/test_task83_r1_production_loop.py`

| # | Scenario | Production surface exercised | Result |
|---|---|---|---|
| 21 | Two real collector passes, different clocks, stable bindings | `ComparisonCollector.collect_once` ×2 | PASS — `manifest_conflict=False`, second pass no-op |
| 22 | Same-day multiple decisions for one symbol | collector → `comparison.json` | PASS — 3 distinct `decision` rows (`d1/d2/d3`), `piv_events=3` |
| 23 | Same-day different session/run scopes | collector ×2 | PASS — both `run_scope`s retained; `manifest_conflict=True`; original manifest untouched |
| 24 | Original scope unavailable | collector (no `runtime_metadata.json`) | PASS — `original_run_scope=UNSCOPED`, `event_level_agreement_assertable=False` |
| 25 | Original Redis disconnected, PIV healthy | `CollectorService.run_for` (async fake, Original `unreachable`) | PASS — `original_redis=DISCONNECTED`, PIV state-file `HEALTHY`, PIV records archived |
| 26 | PIV Pub/Sub disconnected, Original healthy | `CollectorService.run_for` (PIV `unreachable`) | PASS — `piv_pubsub=DISCONNECTED` separate from `piv_session_identity=HEALTHY` |
| 27 | Disconnect → reconnect, buffered messages preserved | `CollectorService.run_for` (`fail_ping_times=1`) | PASS — `reconnect_count>=1`, state recovers to RUNNING/STALE, no loss |
| 28 | Missing PIV notification telemetry | collector → `telegram.json` | PASS — verdict `UNVERIFIED`, `piv_zero_attempt_assertion=False` |
| 29 | Disabled PIV notification, verified zero counters | `merge_telemetry` + collector | PASS — verdict `VERIFIED_ZERO`, assertion `True` |
| 30 | Enabled fake sender with a persisted failed attempt | real `EventBus` (sender raises) + collector | PASS — verdict `ATTEMPTS_RECORDED`, `attempts=1 failures=1` archived |
| 31 | Archive corruption before the next collection pass | collector ×2 + `compare_view` | PASS — `write_aborted=True`, hashes not regenerated, dashboard `trustworthy=False`, `per_stage_totals={}` |
| 32 | Concurrent collect-once / service writer contention | genuine competing OS subprocess holding `CollectorLock` + `ComparisonCollector.collect_once` | PASS — `collect_once` waits for the lock, archive stays `HEALTHY` |
| 33 | Fresh-clone evidence-manifest verification | `_make_manifest.py` LF-normalized hashing round-trip + committed-blob check | PASS — 0 mismatches |

## Coverage map to §7 required cases

| §7 required case | scenario |
|---|---|
| two real collector passes, different clocks, stable bindings | 21 |
| same-day multiple decisions for one symbol | 22 |
| same-day different session/run scopes | 23 |
| Original scope unavailable | 24 |
| Original Redis disconnected while PIV healthy | 25 |
| PIV Pub/Sub disconnected while Original healthy | 26 |
| disconnect → reconnect with buffered message preservation | 27 |
| missing PIV notification telemetry | 28 |
| disabled PIV notification with verified zero counters | 29 |
| enabled fake sender with a persisted failed attempt | 30 |
| archive corruption before the next collection pass | 31 |
| concurrent collect-once / service writer contention | 32 |
| fresh-clone evidence-manifest verification | 33 |

Task 83-R2 generation is explicit: `scripts/generate_task83_r2_rehearsal_evidence.py`
runs the complete production-loop module into a temporary candidate, refuses
publication unless scenarios 21–33 are present exactly once and all PASS, then
atomically replaces the committed CSV. Ordinary or partial pytest runs do not
write this evidence file.
