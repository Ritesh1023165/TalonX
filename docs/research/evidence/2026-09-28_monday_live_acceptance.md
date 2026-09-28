# Monday 2026-09-28: live start, SEC refresh acceptance (INCONCLUSIVE) and SEC remediation package

Follows [2026-09-26_p0_package2a_weekend.md](2026-09-26_p0_package2a_weekend.md) and runbook [2026-09-28_MONDAY_RUNBOOK.md](../../runbooks/2026-09-28_MONDAY_RUNBOOK.md). Evidence: [`2026-09-28_monday_live_acceptance/`](2026-09-28_monday_live_acceptance/).

| | Verdict |
|---|---|
| Startup | **PASS** (one blocked attempt, root-caused: Redis down after a machine reboot) |
| No replay | **PASS** |
| SEC background refresh, live acceptance | **INCONCLUSIVE**: live same-data parity 0 mismatches; freshness BORDERLINE |
| SEC remediation package | built, tested, benchmarked, parity-checked. **Not deployed live** (the market session was open) |
| ACTIVE provider mutation | **OFF**; gated on the SEC verdict and explicit owner authorisation |
| AFTER_HOURS reserve, live confirmation | see §6 (collected tonight) |

## 1. Startup (07:00Z target = 08:00 UK)
- **Preflight PASS.**
  - Repo: branch `feature/continuous-opportunity-engine`, HEAD `cf0cffb`, `main` `696370e`, clean.
  - Processes: 0 stale, ports free, no PID registry, no start-lock; XNYS session today (13:30–20:00Z).
  - State: 19 of 19 databases `ok`; durable state exactly as left at the weekend shutdown (cursors 4,550; promotion 36 SIGNAL / 0 queued; Sentinel offset 920191867; 0 pending/failed outboxes; V2 $100,000 / 0 positions).
  - V2 release gate READY (21 PASS + 1 standing disclosed WARN: intelligence card delivery).
- **Window 1 attempt 1 (07:00:35Z):** `NOT_STARTED`, nothing spawned. Preflight `redis_reachable = NO_GO`.
  - Root cause: **the machine rebooted at 05:53Z**, so Docker Desktop (host of `talonx-redis`) was not running.
  - Recovery: started Docker Desktop. The container (`restart: unless-stopped`, persisted volume) came back healthy at 07:02:53Z, PING OK, nothing flushed.
  - **Finding F-M2 (MEDIUM, operations):** the pre-start checklist did not include "Docker Desktop running and `talonx-redis` healthy".
- **Window 1 retry (07:03:30Z): READY.** Base stack, V2 companion, checkpoint daemon, dashboard :8787.
- **Window 2 (07:04Z):** all 11 engine components STARTED under one supervisor loop, with the runbook §S3 environment.
- **Footprint:** 18 logical processes (36 python), 0 duplicates. Telegram pollers `EXPECTED_DISTINCT_POLLERS` (Signal 1, Sentinel 1).
- **Boundaries (07:04Z):**
  - supervisor and sentinel: OPERATIONS_ONLY (unchanged restart).
  - discovery, the 4 evaluators, notifier, outcomes and reporting: OPERATIONS_ONLY / DECLARED (weekend F-P2 declarations consumed). Discovery config still carries `SEC_CATALYST_CACHE=BACKGROUND_REFRESH_V1`.
  - ingestion: DATA_FIX (conservative default, as planned).
  - **promotion: STRATEGY_MATERIAL / CONFIG_FINGERPRINT_CHANGED.**
- **Finding F-M1 (LOW, reporting):** `promotion.py` is not in promotion's version-hash sources.
  - The weekend F-P2 check therefore missed that `promotion.py` changed in `40386fa` (the dormant OPERATOR_EXCLUDED gate), and its declaration reason wrongly says no component source changed.
  - The config-fingerprint rule (`promotion_src`) caught the change and recorded the conservative class. Nothing was replayed or downgraded.
  - Fix deferred: adding the file needs a `runtime.py` change, which moves every component hash.
- **No replay: PASS.**
  - Engine max event 4,550 unchanged, cursors 4,550, no new events before live data.
  - Promotion states unchanged.
  - Lab, Signal and shared outboxes unchanged. The only new row is V2's standard STARTUP notice to Sentinel (07:03:15Z).
  - Sentinel offset 920191867 unchanged, 0 Saturday commands replayed. V2 ledger sha `891cddac6ce2a1a6` unchanged.

## 2. SEC background refresh: live acceptance (INCONCLUSIVE)
- **Collector:** ran once at 16:00Z (task `buc4rhu6x`, done 16:00:58Z) and re-evaluated at 17:05Z. Output: `sec_live_1600.json` / `sec_live_1705.json`.
- **Steady state:** 83 scans after 2 warm-up scans (08:04 and 08:15, 0 lookups before the first pre-market data; the real cold fill was 08:30, 113 s).

| Criterion (unchanged) | Monday live | Friday (no refresher) | Pass |
|---|---|---|---|
| heavy-scan p90 < 120 s | **78.7 s** (p50 32.1, max 192.6 at the 13:50Z open burst: 511 never-seen CIKs) | p90 285 s, max 328 s | ✅ |
| 0 skipped slots after warm-up | **0** | 7 | ✅ |
| cache-hit wait p99 < 2 s | 0.0 s (max 0.86 s) | — | ✅ |
| max served age < 600 s | **600.0 (display)** at 15:45Z | — | ❌ as written |
| SEC request rate < 5/s | max 2.9/s | — | ✅ |
| provider-incomplete / cursor lag | 0 / 0 | — | ✅ |
| category G | **0 of 250 movers** (16:00Z) | — | ✅ |
| data / state loss | 0 / 0 | — | ✅ |

**Live same-data parity** (16:05:46–17:04:45Z):
- Setup: today's ingestion state (5,652 symbols, data as of 15:49Z), decision clock fixed, SEC throttled to 2 req/s (combined with live peak ~4.1/s).
- **0 mismatches** in candidate identity, presence, classification, score, catalyst and lifecycle event type, over **1,267 candidates/events**. This held for both sync-vs-cold and sync-vs-refreshed.
- 6,630 SEC requests, 0 errors, 0 throttles.

**Freshness finding: BORDERLINE.**
- 7 live scans had a per-scan max served age ≥ 590 s; 6 ≥ 595 s; 1 displayed 600.0.
- The live metric was rounded to 0.1 s at source, so the 15:45 raw value lies in [599.95, 600.05) and is not recoverable.
- A cache hit is strictly < 600 s by construction. A value ≥ 600 is possible only through the uninstrumented stale-copy-on-failure / back-off path.

## 3. Root cause (verified in code, 2026-09-28)
1. **Served age computed:** `BackgroundSecCache.get`.
   - Hits: `now - fetched_at`.
   - Sync fallbacks: `clock() - cache[cik][0]` after `SecSubmissions.get`.
2. **Rounded:** `end_scan()`, `round(max_served_age_s, 1)`.
3. **Hit freshness enforced:** `now - hit[0] < ttl_s` (strict), identical to `SecSubmissions.get`.
4. **Expired entry synchronous fetch:** `SecSubmissions.get` inside `BackgroundSecCache.get`, under the cache lock.
5. **Stale copy returned** (`SecSubmissions.get`, documented: "a stale cached copy is preferred over no data if a refresh fails"):
   - on any fetch exception (HTTP error, timeout, other);
   - during the 429 back-off window, with no request made.
6. **Stale fallback age:** folded into the same max, so a stale serve would show as ≥ 600.2 s unless the failure happened within ~50 ms of expiry. No reason was recorded, and there was no per-scan stale count.
7. **Capacity:** the refresher ran only while discovery was idle and held the cache lock for its whole network request.
   - Live throughput was ~2.2–2.6 refresher req/s (e.g. 3,065 refreshes 15:00–15:20Z) against ~1,500 tracked CIKs, including names discovery had not asked for in up to 30 min.
   - That is a ~625 s refresh cycle, longer than the 600 s TTL, so served ages rode the ceiling from ~1,000–1,300 lookups/scan.

**Contract note (no conflict to stop on):** the code contract **permits** stale-on-failure. The acceptance criterion requires max served age < 600 s. The remediation therefore makes every stale serve explicit and does **not** change serving semantics; the next acceptance judges any stale serve against the contract explicitly.

## 4. Remediation (single file: `talonx_opportunity/sec_refresh.py`; discovery identity only)

| Change | Why |
|---|---|
| **Raw freshness evidence** per scan (`scans.funnel_json.sec_cache`), kept alongside the historical rounded `max_served_age_s` | proves strict < 600 s instead of inferring it |
| Fields: `served_source` counts (`cache_fresh_count`, `sync_refresh_count`, `stale_fallback_count`, `no_data_count`); `stale_fallback_reasons` (`FETCH_ERROR`, `TIMEOUT`, `RATE_LIMIT`, `RATE_LIMIT_BACKOFF`, `OTHER`); `stale_fallback_max_age_raw`; `max_served_age_raw` (6 dp); `served_age_p95_raw` / `p99_raw`; `count_age_ge_590/595/600`; `lookup_wait_p99_s` / `max_s` | same |
| **Global request-start limiter** (`RateLimiter`, slot reservation) on every SEC request, both discovery and refresher: starts ≥ 0.21 s apart, so ≤ 4.76 req/s | enforced cap, not timing luck. Discovery reserves first; the refresher takes only a slot that is free now with no discovery request pending |
| **Refresher I/O outside the cache lock**; refreshing continues during scans, paced to 2.0 req/s | the Friday starvation came from lock-held I/O, now removed. Discovery cache hits never wait for a refresher request |
| **Reuse window 660 s**: refresh only CIKs discovery asked for in the last two cadences | stops spending budget on names no longer gapping |
| **High-resolution timing** (`time.perf_counter`) in the limiter, pacing and wait metrics | on Windows `time.monotonic` and `Condition.wait` tick at ~15.6 ms, which cut limiter throughput (≈7 % at 0.21 s, ~45 % in a 1:25 bench) and made live hit-wait readings of "0.0" meaningless below one tick |

Still one refresher thread. Serving semantics, parsing, scoring and classification are unchanged. `scan_refresh_rate_per_s=0` reproduces the old idle-only refresher exactly.

**Alternatives considered:**
- *A second worker lane*: rejected. Throughput is bounded by the global cap, not by thread count, once I/O leaves the lock.
- *Adaptive concurrency*: subsumed by the limiter plus the scan budget.
- *Earlier refresh threshold*: adds no throughput; oldest-first is already optimal under saturation.
- *Reuse priority*: adopted.

## 5. Offline load benchmark (OLD `cf0cffb` vs NEW, same synthetic load, real threads, 1:25 compression)
- **Load model:** live-fitted scan compute (5 s + 0.035 s/lookup), 15 % CIK churn per scan, 300 s cadence, TTL 600 s.
- **Network model:** OLD serial 0.26 s/request (live fit); NEW 0.05 s latency with starts spaced by the 0.21 s limiter.
- **Method:** 9 scans per point, first 2 excluded as warm-up. **Only run v3 is valid.** Runs v1/v2 were invalidated by the Windows 15.6 ms tick (a limiter and harness timing defect, since fixed); they are kept in the evidence folder and marked invalid.

| Lookups/scan | OLD max served age (raw) | NEW max served age (raw) | OLD / NEW scan p90 | OLD / NEW sync fallbacks | NEW req/s (overall; max in-scan) | NEW discovery wait p99 / max |
|---|---|---|---|---|---|---|
| 500 | 278.9 | **148.1** | 43.0 / 36.9 | 493 / 493 | 4.28; 3.20 | 0.27 / 0.30 s |
| 1,000 | 599.9 | **329.1** | 81.7 / 68.3 | 983 / 972 | 4.21; 3.30 | 0.26 / 0.71 s |
| 1,250 | 599.9 | **428.1** | 183.2 / 84.0 | 2,191 / 1,202 | 4.13; 3.32 | 0.25 / 0.30 s |
| **1,300** | 599.6 | **448.0** | 194.2 / **87.1** | 2,494 / **1,254** | 4.13; 3.35 | 0.27 / 0.41 s |
| 1,500 | 600.0 | **515.9** | 254.0 / 100.8 | 4,107 / 1,477 | 4.10; 3.37 | 0.26 / 0.30 s |
| 2,000 | 600.0 | 599.8 (no headroom) | 381.2 / 194.1 | 7,135 / 3,309 | 4.07; 3.95 | 0.27 / 0.54 s |

- **Headroom:** ~150 s at 1,300 lookups (448 vs the 600 s TTL) and ~84 s at 1,500. **No freshness headroom at 2,000**, so scalability beyond ~1,500 lookups/scan (let alone 5,653) is **not** claimed.
- **Stale fallbacks:** 0 in every run of both designs (no injected failures), and no item served ≥ 600 s.

## 6. Post-change same-data parity (today's data) and AFTER_HOURS live confirmation
**Post-change parity: PASS** (NEW code, in-process; live engine untouched). `sec_parity_live_v2.json`:
- **Run:** 18:29:06–18:59:58Z on today's ingestion state (5,652 symbols, data as of 18:13Z), decision clock fixed at 18:29:06Z. SEC throttled to 2 req/s; 3,333 requests, 0 errors, 0 throttles.
- **Mismatches:** candidate identity 0, presence 0, classification 0, score 0, catalyst 0, lifecycle event type 0 over **1,076 candidates/events**. This held for both sync-vs-cold and sync-vs-refreshed.
- **Refreshed scan, from the new instrumentation:** 1,043 cache hits, 70 sync refreshes, **0 stale fallbacks**, raw max served age **564.672 s**, 0 items ≥ 590 s.

**AFTER_HOURS reserve live confirmation:** collector `ah_live_check.py`, runs at 21:30Z and 00:10Z. Results are appended in §10.

## 7. Tests
- **Focused:**
  - `tests/test_sec_refresh_remediation.py` (15): served source and raw age; stale fallback reasons FETCH_ERROR / TIMEOUT / RATE_LIMIT / RATE_LIMIT_BACKOFF; NO_DATA; 599.95 vs 600.0 distinguishable; limiter spacing and window bound across threads; discovery priority; production wrap installs the limiter on every request; concurrent fallbacks plus refresher respect the cap; hits never wait on refresher I/O; reuse window; a newer copy is never overwritten; refresher failure keeps the old copy and discovery keeps working.
  - Plus the existing `test_sec_background_refresh.py` (updated for the new contract; legacy idle-only mode still tested) and `test_p0_sec_refresh_activation.py`: **45 passed ×3**.
- **Regression sweep:** Opportunity Engine, P0-1/2A, promotion, operator control, V2 routing, notification isolation, prospective, owner dedup, premarket and legacy: **434 passed.**
  - 2 baseline failures, identical on START_SHA (live-stack `ConcurrentStartError`).
  - 1 non-hermetic test fixed: `test_b6_shim_child_pair_is_one_logical_owner` read the real process table, where the live Sentinel poller now counts as a second role.

## 8. Deployment (NOT done: the market session was open) and next live acceptance
**Version identity:**
- Only discovery moves (`eb716fb149b8` → the new hash); `runtime.py` is untouched, so no other component gains a pending boundary.
- `sec_refresh.py` and `catalysts.py` are both in discovery's hash sources.

**Deploy window:** after the AFTER_HOURS session ends (after 00:15Z, when the after-hours collector has run) or before 07:00Z. Run from a shell carrying the runbook §S3 environment; this is **required**, because `restart` spawns with the calling shell's environment.
```
$env:TALONX_SEC_BACKGROUND_REFRESH_ENABLED='1'   # plus the rest of runbook §S3
.venv\Scripts\python.exe -m talonx_opportunity declare-change discovery --class DATA_FIX --reason "SEC refresh remediation: raw freshness evidence, global request limiter, refresher I/O outside the cache lock, reuse window; serving semantics unchanged; parity 0 mismatches"
.venv\Scripts\python.exe -m talonx_opportunity restart discovery
```
- **Expected boundary:** discovery `DATA_FIX / DECLARED` (code only; config fingerprint unchanged).
- **Rollback:** check out the previous `sec_refresh.py`, then declare DATA_FIX and restart discovery; or unset the flag, declare DATA_FIX and restart discovery.

**Next full-session acceptance** (tool: `docs/research/evidence/2026-09-26_p0_package1/tools/live_acceptance.py`, which now evaluates raw served age):
- raw max served age < 600 s;
- `stale_fallback_count` = 0, or every stale serve reported with reason and raw age and judged against the contract;
- no ≥ 600 s serve hidden;
- p90 scan < 120 s;
- 0 skipped slots after warm-up;
- lookup wait < 2 s;
- request rate < 5/s;
- same-data parity 0 mismatches;
- category G = 0;
- cursor lag 0;
- data/state loss 0.

**Operating-envelope report:** served-age distribution bucketed at ~1,000, ~1,250 and ≥ 1,300 lookups/scan.

## 9. Findings / follow-ups
- **F-M1:** promotion hash gap (promotion.py not in its version sources).
- **F-M2:** Redis/Docker Desktop is not in the pre-start checklist.
- **F-M3:** Windows `time.monotonic` resolution (~15.6 ms). Fixed for the SEC limiter, pacing and wait metrics here.
  - `SecSubmissions`' own 0.21 s spacing (`talonx_premarket/catalysts.py`) also uses `time.monotonic` and could, on its own, space a start up to one tick early.
  - In production it is now fronted by the `perf_counter` limiter, which governs the cap.
  - Other engine uses of `time.monotonic` are duration measurements and have not been audited for sub-tick precision.
- **Follow-ups (not in this task):** Dynamic Tradable Universe / symbol-count reduction (needed beyond ~1,500 lookups/scan), S-UX1 / S-OPS1, ACTIVE provider mutation proof.
