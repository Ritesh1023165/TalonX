# Next-version P0 package 1: SEC background refresh activation + AFTER_HOURS reserve fix (2026-09-26)

Follows [2026-09-25_continuous_live_validation.md](2026-09-25_continuous_live_validation.md) (§6.2 AH reserve defect, §8 SEC plan). Evidence: [`2026-09-26_p0_package1/`](2026-09-26_p0_package1/).

**Execution context:** Saturday 2026-09-26. There is **no XNYS session**; the engine was in CLOSED phase throughout. Every live boundary below was taken on a non-trading day, so the next live data is Monday 2026-09-28 (PREMARKET from 08:00Z).

| | Verdict |
|---|---|
| **SEC_REFRESH** | **NOT_ACCEPTED (live acceptance pending).** Deployed at a clean DATA_FIX boundary. Deterministic, parity and benchmark evidence PASS. No live scan exists yet to judge the §6 live criteria |
| **AH_RESERVE_FIX** | **ACCEPTED (deterministic replay of the 2026-09-25 transition).** Deployed at a ROUTING_FIX boundary. Live confirmation on Monday's after-hours window |

## 1. Baseline
- **Branch:** `feature/continuous-opportunity-engine`.
- **SHAs:** START `49798a6`; `main` `696370e` (untouched).
- **Tree:** clean (untracked runtime files only).
- **SEC refresher:** `talonx_opportunity/sec_refresh.py` @ `6e8dae6` (sha256 `4eaddf523aac3f0f…`). Flag unset in the live discovery process (PID 15904 since 2026-09-25 07:08:59Z).
- **Discovery hash sources** (before): discovery.py, aggregates.py, capabilities.py, premarket features, scoring, alerts, catalysts, config, plus the shared runtime modules. `sec_refresh.py` was **not** included.
- **AH reserve (before):** `notifier.py:165`, `later_phase_reserve.get(ev["phase"])`, i.e. the processing phase.
- **V2 end-of-day close for 2026-09-25: not run.** `prospective close` reports `NOT_DUE_YET` because `eod_state()` only checks whether *today* is a session, and Saturday is not.
  - Running it would need `--force`, and it shuts the stack down by default, so it was not run.
  - Finding F-P3: a missed Friday close is invisible over the weekend instead of showing STALE.
  - V2 itself: HEALTHY / CURRENT, $100,000, 0 positions, trades and intents, DB sha `891cddac6ce2a1a6` (unchanged).

## 2. Changes (two production changes)

| Commit | Change |
|---|---|
| `d2ce6b1` | **A. SEC activation support:**<br>• `sec_refresh.py` added to discovery's `COMPONENT_SOURCES`.<br>• Closed `CONFIG_KEY_CLASS` list: discovery `SEC_CATALYST_CACHE` → DATA_FIX, but only if every changed key is listed **and** a DATA_FIX declaration exists; anything else stays forced STRATEGY_MATERIAL.<br>• Per-scan SEC cache metrics in `scans.funnel_json["sec_cache"]` (bookkeeping; served data unchanged). |
| `18f3426` | **B. AH reserve data-phase fix:**<br>• Reserve looked up by `phase_at(data_as_of − 1 min)` in the event's window, the same convention as promotion and outcomes.<br>• Unknown data phase fails closed: it is treated as the earliest phase up to the processing phase and never takes a later reserve.<br>• Additive `decisions.data_phase` column.<br>• `after_hours_reserve` counters in the notifier detail.<br>• Config fingerprint gains `reserve_phase_basis=CAUSAL_DATA_PHASE_V1`.<br>• Caps, WATCH share, ranking, rates and policies unchanged. |

A side effect of A: `runtime.py` is part of every component's hash, so **every component's version hash changes**. Components not restarted today keep their running version; their next restart must carry a declaration, or it defaults to their component class.

## 3. Deployment boundaries (live, 2026-09-26)

| UTC | Component | Boundary | Class / rule | Version | Config |
|---|---|---|---|---|---|
| 08:58:33 | notifier | `20260926T085833Z-notifier-4c02a5` | ROUTING_FIX / CONFIG_FINGERPRINT_CHANGED (declared reason #6) | a3f10999a967 → e4c8cc285ff6 | + `reserve_phase_basis` |
| 09:05:36 | discovery | `20260926T090536Z-discovery-efcad5` | **DATA_FIX / CONFIG_KEY_MAPPED+DECLARED** (#7, declared=1) | cd560a2b3190 → a5bd67035a4d | + `SEC_CATALYST_CACHE=BACKGROUND_REFRESH_V1`; strategy fps `2ef115ee19f99574` / `62ba413daf85e674` unchanged |
| 09:06:17 | supervisor loop | `20260926T090617Z-supervisor-b3e672` | **STRATEGY_MATERIAL / UNDECLARED_CODE_CHANGE_DEFAULT** (bookkeeping defect, see F-P1) | c87ea35f2378 → 75437e48756a | — |

**Environment:**
- The flag is `TALONX_SEC_BACKGROUND_REFRESH_ENABLED=1`. It is set in the discovery process, and in the supervisor loop so that a respawn keeps it.
- It is read only by `discovery.main` (`sec_refresh.enabled()` has no other caller).
- The notifier policy is unchanged (`LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925`).

**Restart set:**
- Restarted: notifier (22620 → 9384) and discovery (15904 → 18600), plus a relaunch of the supervisor loop.
- Not restarted: ingestion, the 4 evaluators, outcomes, reporting, promotion (16348), V2 (12840), run_talonx, the intelligence poller and the dashboard.

**No replay / no duplication** (pre vs post snapshots):
- All 6 consumer cursors are 4,550 before and after.
- Candidates 2,065 = 2,065 distinct; events 4,550 = 4,550 distinct.
- Decisions: 4,550 before and after, byte-identical apart from the new NULL `data_phase` column.
- Lab outbox 294 SENT before and after; promotion 36 SENT / 0 queued before and after.
- Scans +3 (CLOSED ticks only).
- V2: only its heartbeat and tick advanced.

## 4. SEC refresh evidence

### 4.1 Same-data parity shadow (`sec_parity.json`, real SEC EDGAR)
The input was the final 2026-09-25 ingestion state (5,653 symbols, data as of 23:44Z) with the decision clock fixed at 23:59Z. There were 391 SEC lookups per scan.

| Run | Wall | SEC path |
|---|---|---|
| R1 SYNC_REFERENCE (plain SecSubmissions) | 109.2 s | 391 requests |
| R2 ON_COLD | 103.2 s | 391 misses → sync fallback, 3.8 req/s |
| background refresher (idle-gated) | 91.1 s | 391 refreshed, 0 errors |
| R3 ON_REFRESHED | **15.9 s** | 391 hits / 0 misses; hit wait p99 0.0 s; max served age 91 s; 0 SEC requests during the scan |

- **CANDIDATE_PARITY:** 0 identity mismatches (380 events).
- **CLASSIFICATION_PARITY:** 0 of 5,653.
- **SCORE_PARITY:** 0.
- **CATALYST_PARITY:** 0.
- **MISMATCHES:** 0, for both R1 vs R2 and R1 vs R3.

### 4.2 Benchmarks (2026-09-25, deterministic; unchanged)
- Heavy-scan p90 OFF → ON: 1,000 symbols 306 → 24 s; 1,500 symbols 453 → 24 s; 2,000 symbols 594 → 24 s.
- Served age < 600 s at every size.
- Single-lane capacity: SAFE to ~1,000, TIGHT at 1,250–1,500, INSUFFICIENT at 2,000. There, the synchronous fallback keeps the contract.

### 4.3 Failure tests (focused, green)
- Timeout.
- 429 back-off.
- A failed refresh keeps the previous copy and its fetch time.
- An expired entry forces the synchronous path.
- A refresher crash never affects discovery.
- A cache-write failure restores the copy.
- Clean shutdown while the worker is active.
- Cold and partially warm cache after a restart.
- In-flight refresh versus a scan start (discovery waits for at most one request).
- A 3,000-step freshness property test.
- New: a stale-copy-on-failure served age is reported; a refresh in flight at scan start is counted.

### 4.4 Live acceptance: **pending**
- `tools/live_acceptance.py <window>` evaluates every scan after the DATA_FIX boundary.
- It expects warm-up scans 1–2 to be heavy (cold cache) and records them separately.
- Steady-state criteria:
  - heavy-scan p90 < 120 s
  - 0 skipped slots
  - hit wait p99 < 2 s
  - max served age < 600 s
  - SEC rate < 5/s
  - no provider-incomplete
  - cursor lag 0
- Category G comes from the full-day missed-mover audit.
- **Run it on 2026-09-28** after about 16:00Z (it should cover the 13:45–15:30Z heavy period) and again after the close.
- **Rollback** if the criteria fail or correctness is at risk:
  1. Unset the flag in the supervisor-loop environment.
  2. `declare-change discovery --class DATA_FIX --reason ...`.
  3. Restart discovery only.

## 5. AH reserve evidence

### 5.1 Deterministic replay of 2026-09-25 20:00Z → 00:00Z (`ah_replay.json`)
- **Start state:** the live notifier state at the last pre-20:00Z event (seq 4,009; 72/75 used).
- **Replayed:** all 541 post-close events through the fixed notifier, with the live policy and delivery off.

| | Live 2026-09-25 | Fixed notifier |
|---|---|---|
| counted surfacings after the close | VEON, CERT, DRVN (REGULAR data, 19:44Z) | **HP, EXFY, OVID** (AFTER_HOURS data) |
| VEON / CERT / DRVN | SELECTED | BUDGET_RESERVED_LATER_PHASE ("3 kept for phases after REGULAR data (processed in AFTER_HOURS)") |
| AH_RESERVED_USED_BY_TRUE_AH | 0 | 3 |
| REGULAR_DATA_AFTER_CLOSE_COUNTED_NEW | 3 | **0** |
| TRUE_AH_SENT / HELD | 0 / 49 | 3 / 46 |

- **Decisions changed:** 111. Only **7 are send changes**: −3 REGULAR-data, +3 true after-hours, and +1 follow-up invalidation of a now-surfaced true after-hours candidate.
- **Hold-reason changes (104):** events held in both runs whose reason changed because the budget was no longer exhausted:
  - 72 WATCH: `EXHAUSTED_TOTAL` → `EXHAUSTED_WATCH`
  - 32 REGULAR-data setups: `EXHAUSTED_TOTAL` → `RESERVED_LATER_PHASE`

### 5.2 Regression tests (`tests/test_p0_ah_reserve_data_phase.py`, 12)
1. REGULAR data before the close is handled as before, with identical reason text.
2. The 2026-09-25 shape: VEON/CERT/DRVN-style events can't take the reserve; HP takes it.
3. Three true after-hours setups use exactly 3 slots, and the 4th is held.
4. The first true after-hours setup is served even after delayed REGULAR events, including 20:16Z still-REGULAR data.
5. An update to a never-sent candidate doesn't consume the reserve.
6. A missing data phase fails closed.
7. PREMARKET data processed after the open can't take REGULAR capacity (same keying).
8. No replay after the boundary, and old-schema rows aren't reinterpreted (lost slots aren't handed back).
9. A restart preserves the reserve accounting.
10. A pure REGULAR day is unchanged.
11. The data-phase function itself.
12. The config fingerprint records the reserve basis, and the caps are unchanged.

**Live counters:** the notifier detail now carries `after_hours_reserve`: AH_RESERVED_TOTAL / USED_BY_TRUE_AH / REMAINING, REGULAR_DATA_AFTER_CLOSE, TRUE_AH_SENT / HELD.

## 6. Tests

| Suite | Result |
|---|---|
| focused SEC (`test_p0_sec_refresh_activation.py`, 12) + AH (`test_p0_ah_reserve_data_phase.py`, 12) | 24 passed |
| discovery / notifier / engine (`test_continuous_opportunity_engine.py`) + SEC (`test_sec_background_refresh.py`) | passed (×3 repeats) |
| promotion, operator control, V2 routing fix, notification isolation (same-chat, ri2, task138, task77i, task83 r1/r2), freeze/preflight guards, premarket engine, session03, legacy cleanup, canary hardening | passed |
| total regression sweep | **369 passed, 2 failed** + 77 passed |
| baseline failures | `test_task114_prospective::test_start_stack_*enable_broad_discovery*` (2): `ConcurrentStartError` because the live prospective stack is running. **Identical on START_SHA `49798a6`** |
| commit A in isolation (`d2ce6b1`) | 78 passed |

## 7. Findings
- **F-P1 (LOW, reporting):** the relaunched supervisor loop recorded `STRATEGY_MATERIAL / UNDECLARED_CODE_CHANGE_DEFAULT`.
  - Cause: `supervisor` has no `COMPONENT_DEFAULT_CLASS` entry. Its hash covers `__main__.py`, which changed on 2026-09-25 (`e94e335`, promotion dispatch), and the loop had not been relaunched since.
  - It is an OPERATIONS_ONLY restart in substance, and it fell on a non-trading day.
  - Fix next version: supervisor default class OPERATIONS_ONLY, or declare it before each relaunch.
- **F-P2 (LOW, operations):** `runtime.py` is in every component's hash, so any change to `COMPONENT_SOURCES` moves every identity.
  - The next restart of ingestion, the evaluators, outcomes, reporting or promotion must be declared (OPERATIONS_ONLY: hash-list change only). Otherwise it defaults to its component class; the evaluators default to STRATEGY_MATERIAL.
- **F-P3 (MEDIUM, operations):** the V2 end-of-day close for 2026-09-25 was never run, and `eod_state()` hides it over the weekend. See §1.
- **Erratum to the 2026-09-25 report:** 2026-09-25 was a **Friday**, not a Thursday.

## 8. Not changed
- Scoring, gates, lifecycle, horizons and cadence.
- Notifier caps, WATCH share, ranking and rates, and the selected policy.
- The promotion contract (REGULAR-only, BULLISH-only, paper, 3 per 5 minutes, 30-minute expiry, no replay). Promotion was not restarted.
- V2 strategy, provider and campaign.
- The Sentinel control plane: still DRY_RUN, no poller, no universe change.
- No broker path; no replay of any held event.

## 9. Next package preview: P0 package 2 (prepared, not implemented)

| Item | Dependency / blocker |
|---|---|
| Sentinel single-poller health fix (`talonx_ops/prospective/telegram_owner.py` must recognise the registered Sentinel OPERATIONS poller) | none; code + tests |
| Real-Telegram DRY_RUN (`/help`, `/help exclude`, `/help universe`, `/scanned`, `/scanned file`, `/exclude status`, `/universe status`) | health fix; owner at the Sentinel chat |
| Control-plane ACTIVE activation proof (exclude → absent from yfinance and Alpaca batches → no discovery or promotion → restore → no replay) | real-Telegram DRY_RUN; explicit owner authorisation; declared boundaries for ingestion, discovery, promotion and run_talonx (see F-P2) |
| Promotion supervisor/status hardening (add to `supervise.COMPONENTS`, status/dashboard row, mode switch as ROUTING_FIX, broker-import guard) | F-P1 fix belongs with it |
| Blocker to clear first | SEC live acceptance on 2026-09-28; the pending V2 end-of-day close (F-P3) |
