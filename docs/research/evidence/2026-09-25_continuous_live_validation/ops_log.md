# Continuous engine full-day validation: ops log (2026-09-25)

Validation boundary (owner decision, 2026-09-25):
- **Frozen and unchanged:** V2 strategy, provider and campaign logic.
- **Under validation:** the operational shell/runtime, i.e. feature/continuous-opportunity-engine @ 6fa1581, run from C:\workspace\TalonX.

## Pre-session log

| UTC | Event | Class | Semantics |
|---|---|---|---|
| 2026-09-25T07:07:48Z | Broad universe rebuilt with the current rules (`python -m talonx_premarket universe`): 14,395 total / 5,653 eligible (09-24: 14,384 / 5,653) | OPERATIONS_ONLY / DATA_REFRESH | No strategy semantics changed. It happened before any engine component had started, so no in-session deployment boundary was needed. |

Fingerprints after the refresh:
- CONTINUOUS_RESEARCH_V1 2ef115ee19f99574 base 62ba413daf85e674
- V2 strategy e2acf6454789217e provider ac5e51aa3599d6c9

Pre-session SHA-256 prefixes:
- v2_release_rc1.db 891CDDAC6CE2A1A6
- v2_release_rc1_notifications.db A57F7D97B4E7DE08
- v2_lane.db 10E6C542DF213221

## Phase 1: V2 (unchanged release procedure, run from the branch checkout)

- 07:08:37Z `prospective start --release --expected-sha a56ec8c ...`: verdict READY.
  - Release gate READY; scope 39; HEALTHY / CURRENT.
  - Cash $100,000; 0 positions / intents / blocks / unresolved.
- Process tree: supervisor (1644 → 19044), run_talonx (15852 → 21840), intelligence (9588 → 11712), dashboard (2424 → 17804), V2 companion (21032 → 21408), session-loop (8396 → 23008).
- No Experimental process: it is retired by design.

## Phase 2: Opportunity Engine (record-only)

- ~07:09Z `python -m talonx_opportunity up --supervise`.
  - No `--deliver`. `TALONX_NOTIFY_RESEARCH_ENABLED` is unset in the process environment. `.env` has 0.
- All 9 components are UP, each with a FIRST_START deployment boundary.
  - Commit 6fa1581823cb.
  - The notifier's config fingerprints include `deliver=0`.
- First scan at 07:08:59Z: OVERNIGHT → DATA_UNAVAILABLE (NOT_SUPPORTED). No overnight bars fetched.
- PAPER_EXECUTION maps to the frozen V2 companion (observed read-only), not an engine component.

## Live issue 1 (07:08:58Z): supervisor startup race

**Class:** OPERATIONS_ONLY, observability. **No live fix.**

**Symptom:** each of the 9 components logged a `SUPERVISOR_RESTART` (attempt 1) at 07:08:58, one second after `up`.

**Root cause:** `supervise()` starts polling right after `up()` spawns the components. A just-spawned process has not written its lock file yet, so it is seen as "not running" and spawned a second time.

**Integrity:** the second copies all exited immediately with `AlreadyRunning` (the lock held). Verified exactly one process per component, and exactly one FIRST_START deployment boundary each.

**Effect on detection / classification / execution / notification / counts / P&L / comparability:** none.

**Decision:** not fixed during the validation day. It is harmless, and restarting the supervisor mid-session would add risk.

**Post-session fix:** give components spawned by `up()` a startup grace period before `supervise()` judges liveness.

## Lab delivery enabled mid-session (owner instruction)

- **07:38:01Z pre-state:**
  - Engine PIDs: ingestion 19072, discovery 15904, INTRADAY 12596, SAME_DAY 21528, SHORT_TERM 23280, LONG_TERM 14440, notifier 2164, outcomes 18852, reporting 13012.
  - 0 candidates / 0 events / 0 decisions (phase OVERNIGHT, before any market data).
  - Notifier `deliver=0`; policy LAB_NOTIFY_POLICY_V1 50dfea564413f30a.
  - V2 HEALTHY / CURRENT, $100k, 0 positions / intents / blocks; strategy e2acf6454789217e / provider ac5e51aa3599d6c9.
  - `.env` `TALONX_NOTIFY_RESEARCH_ENABLED=0`.
  - Lab probe (process-scoped): RESEARCH resolves to the LAB bot, distinct from Signal / Sentinel / legacy; same chat allowed; disabled without the enable (no fallback).
- **07:38Z** declaration #1: notifier ROUTING_FIX, with reason.
- **Supervisor loop only** (PIDs 20652 + 10840) stopped by individual kill, no tree kill. All 9 component PIDs verified unchanged. This avoids the supervisor respawning a record-only notifier.
- **07:39:01Z** boundary `20260925T073901Z-notifier-5cd876`:
  - ROUTING_FIX (RULE:CONFIG_FINGERPRINT_CHANGED, `deliver` 0→1); declaration #1 consumed.
  - Impact: notification, alert_counts and delivery_metrics only. Detection, classification, execution, candidate counts, P&L and profitability: none.
  - Notifier 2164 → 11020 (shim 16156). The other 8 PIDs are unchanged; V2 PIDs unchanged.
  - Notifier process env: `TALONX_OPP_DELIVER=1`, `TALONX_NOTIFY_RESEARCH_ENABLED=1`. Other components: 0 / 0.
  - Its drain resolves `RESEARCH enabled (distinct Lab bot)`. `.env` still 0.
- **~07:40Z** supervisor loop relaunched (`up --deliver --supervise`, process-scoped enable). All 9 components ALREADY_RUNNING; nothing spawned.
- **Backlog:** 0 pre-boundary events, so there is nothing record-only to replay. All Lab deliveries today are post-boundary events (30-minute `deliver_by`, event-id dedup).

## Live issue 2 (07:39Z): `declared` column is 0 although the declaration was consumed

**Class:** REPORTING_ONLY, LOW. **No live fix.**

On the config-fingerprint rule path, `declared` is set only when `decided_by == DECLARED`. The declaration's reason *is* recorded and consumed, so no information is lost.

## Live issue 3 (07:40Z): `up --deliver` prints `research_destination_enabled=False`

**Class:** UI / OPERATIONS, LOW. **No live fix.**

The `up` process does not load `.env` (where the Lab token/chat live) before its resolution printout. The notifier loads `.env` itself, and its own drain resolves enabled (verified). The printout is a false negative.

## Timeline

- **08:04:07Z** OVERNIGHT → PREMARKET: the first PREMARKET scan was `PROVIDER_STALE`. Ingestion had no PREMARKET state yet, and no bar is visible before 08:15Z. Everything was held (fail closed) and retried every 60 s.
- **08:30:48Z** first data-bearing scan (as-of 08:15Z): 1,291 data-ready, 23 alert-worthy, 23 NEW persisted, 0 incomplete.
  - Notifier: 4 BULLISH + 15 WATCH SELECTED. That is the WATCH share (15) full; the 10-slot setup reserve is intact.
  - 4 WATCH BUDGET_EXHAUSTED_WATCH (TWST, AMD, CZFS, NOK), persisted.
  - 19 Lab messages SENT on attempt 1, all destination RESEARCH.
  - V2-scope names: VRT surfaced; AMD budget-exhausted.
  - Evidence only; no tuning.

## Integrity audit (10:44Z, read-only)

Evidence: `integrity_audit_1.json`.

**Links:**
- 43/43 Lab SENT rows link to a valid candidate and lifecycle event.
- 0 orphans, 0 duplicates, 0 field mismatches (classification, phase, event type, score, symbol, horizon, time order).
- 90/90 events were evaluated by the notifier. The policy reproduces exactly from stored state.
- Held candidates stay persisted; no setup was blocked.

**Lifecycle:**
- 25 multi-event chains, 0 chain defects, 0 duplicate identities.
- JAGX GAP_UP → INVALIDATED (faded), then GAP_DOWN NEW: a legitimate V1 direction flip.

**Outcomes:** 0 rows, as expected; not mature before the regular open. Re-audit after 14:00Z (+30m).

**Live issue 4 (MEDIUM, STRATEGY_MATERIAL if changed, so NOT fixed today): the stale-invalidated identity stays closed for the whole window.**

- 11 "price went stale" invalidations. All are THIN_LIQUIDITY_EXPECTED (≤ 11 pre-market bars, mostly < 1% ADV).
- There is no provider gap: 0 incomplete symbols, 0 failed batches.
- MUFG, SCHL, WTTR, TWST and PHI resumed trading and currently classify WATCH again (moves of 3.8%, −10.2%, 7.0%, 2.2% and −3.8%).
- Because the frozen V1 rule keeps an invalidated identity closed for the window (`discovery.py:203`, inherited from V1), they cannot re-surface in REGULAR / AFTER_HOURS.
- Outcome tracking still covers them (outcomes read every candidate).
- **Candidate for a pre-registered CONTINUOUS_RESEARCH_V2:** stale invalidation should not close the identity once data resumes. Evidence only; no change today.

## 11:40–11:46Z: live fixes and restart test

**Live fix A (supervisor startup race)**
- **Class:** OPERATIONS_ONLY; commit f5a1d92.
- **Fix:** 90 s startup grace before `supervise()` judges liveness. The supervisor now records its own boundary.
- **Deployment:** old loop killed (20220 / 22460) and relaunched with the same process-scoped env. Boundary `20260925T114259Z-supervisor-32ad17` (OPERATIONS_ONLY, FIRST_START, version c87ea35f2378).
- **Verification:** all 9 component PIDs unchanged, and all 9 component versions unchanged (supervise.py and __main__.py are in no component hash). No spurious restart events.

**Live fix C (`up --deliver` false negative)**
- **Class:** UI / OPERATIONS; same commit.
- **Fix:** `up` loads `.env` before resolving. The live status now reads `research_destination_enabled=True`.

**Finding B (`declared=0`)**
- **Deferred.** The fix lives in `runtime.py`, which is part of every component's version hash, so it would turn every later restart today into a code-change boundary.
- Display flag only; no functional effect.

**Restart-resilience test (reporting)**
- Boundary `20260925T114339Z-reporting-60556c`: OPERATIONS_ONLY / RULE:UNCHANGED_RESTART, every impact flag false.
- Reporting PID 13012 → 15840. The other 8 PIDs, the 89 candidates, 148 events, 148 decisions, notifier cursor 148, the 4 evaluator cursors (148 each) and the 61 SENT / 61 outbox rows were all identical before and after.

## 11:45Z: baseline tracks (`tracks_premarket.json`)

- **Attention budget exhausted (NEW-ALERT BUDGET 25/25).** WATCH 15/15; setups 10 (the reserve is fully used).
  - Any NEW setup after this point will be BUDGET_EXHAUSTED_TOTAL. Detection and persistence are unaffected.
  - HIGH notification-policy finding. **Budget values are frozen today, so no change.**
- **Movers (≥ 5%, actionable), 55 in total:** A 12, B 10, C 1, F 28 (scoring/gates, mostly thin names), G 4 (AESI, CGNT, PPLI, WTTR closed identities), **D 0**.
- **Latency:** provider age 960 s (SIP 15-minute entitlement plus minute flooring); internal scan-start → Telegram p50 60 s / max 61 s.
- **Backpressure:** none (cursor lag 0; 0 tick errors; ingestion cycle about 10 s).
- **Stale shadow:** 13 invalidations, 7 of which would be WATCH-worthy now.

## 12:30–12:40Z — LIVE NOTIFICATION BUDGET EXTENSION (authorized, today only)
- Pre-snapshot 12:30:46Z PREMARKET HEAD f5a1d92: 112 cand / 196 ev / decisions 69 SEL, 31 TOTAL, 63 WATCH, 33 NSP; outbox 69 SENT; NEW 25/25 (W15, S10); 94 held; V2 e2acf645/ac5e51aa CURRENT 0 trades 0 intents; BUY/SELL 0; Signal/Sentinel research rows 0. File: pre_budget_override_full.json
- Commit 1b5ef6f: closed-list override LAB_NOTIFY_POLICY_V1_LIVE_OVERRIDE_20260925 (40 total / 25 reserved → WATCH 15) via TALONX_OPP_NOTIFY_POLICY; test added (46 pass)
- Declaration #2 → boundary 20260925T123424Z-notifier-b02188 ROUTING_FIX (RULE:CONFIG_FINGERPRINT_CHANGED), policy fp 50dfea56→3b5d65a6; impacts alert_counts/delivery_metrics/notification only
- Supervisor loop 14416 killed; notifier restarted 11020→24332 (env DELIVER=1, RESEARCH=1, override); loop relaunched (env→9148→19300), bt1curw2s
- Post: 8 other PIDs unchanged; 94/94 held still held, 0 re-decided, outbox 69 SENT, 0 dup; NEW 25/40, WATCH 15/15, setup capacity 15

## 12:46Z — PHASE-RESERVED ROUTING_FIX (authorized)
- Pre 12:46:11Z PREMARKET HEAD 1b5ef6f: 121 cand / 222 ev / outbox 78 SENT / NEW 26/40 (W15, S11) / PREMARKET extra 1 (SVRN 12:36) / 103 held; V2 unchanged. File pre_phase_reserve.json
- Commit 5bb9cf4: LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925 (later_phase_reserve PREMARKET 10, REGULAR 3, AH 0 → PM extra ≤5, REG ≥7, AH ≥3; roll-forward automatic); new held reason BUDGET_RESERVED_LATER_PHASE; 2 tests (48 pass x2; one transient flake of the process-restart test on first run)
- Declaration #3 → boundary 20260925T124634Z-notifier-c7d677 ROUTING_FIX, fp 3b5d65a6→5adb6e6d
- Notifier 24332→22900; loop relaunched (bzb6s3v4y); 8 other PIDs unchanged; 103/103 held still held; 0 retroactive rows; outbox 78→78; cursors 222 unchanged
- AH readiness (static): 20:00Z→AFTER_HOURS same window_id; capability AVAILABLE; cadence 300s; stale does not invalidate in AH; notifier phases include AH; reserve 3

## 12:56–13:05Z — TRUE REGULAR-DATA VALIDATION setup
- Pushed 5bb9cf4 (local=remote=5bb9cf4; main 696370e untouched)
- New regular_truth.py: PROCESSING_PHASE (event.phase) vs DATA_PHASE (symbol last_bar_utc, else as_of-1m); REGULAR_WALLCLOCK/DATA_FIRST_SEEN; T0–T6; transition cohort; MATERIAL_UPDATE audit; held-setup cohort; reserve; perf since open
- live_tracks.py mover classes A–I; stale shadow split WATCH/BULLISH/BEARISH
- TEST_FLAKE_UNDER_LOAD (LOW): test_independent_processes_restart_one_component_only failed once 12:45Z (assertion text not captured — only tail kept); passes 8/8 since (2 suite + 6 isolated, 12–17s). Carry as bounded flake; full output now captured on repeats (flake_run_*.txt)
- AH readiness code review: no close stop; ingestion to after_hours_end; evaluators SAME_DAY/SHORT_TERM active in AH
- LOW F3: outcome N/A-same-day + horizons + stale gate keyed on wall-clock phase; 20:00–20:16Z candidates from REGULAR data get NOT_APPLICABLE_SAME_DAY. Record only.

## 13:15–13:21Z — F3 OUTCOME PHASE-BASIS FIX (authorized live fix)
- Pre 13:15:29Z PREMARKET HEAD 5bb9cf4: 134 cand / 255 ev / outbox 85 SENT / NEW 27/40 (PM extra 2) / outcome rows 0 / outcomes pid 18852 v1301712b66e1. pre_f3.json
- Root cause: outcome_tracker used wall-clock first_seen_utc for (a) NOT_APPLICABLE_SAME_DAY (>= close) and (b) pre-open vs since-first-seen model (< open). Horizons (discovery._horizons) + stale gate (discovery) are DISCOVERY, not outcome -> untouched (strategy-material; out of scope)
- Fix 478d6fc: outcome_basis() on first_data_as_of_utc (causal scan horizon; fallback first_seen). Config fp +phase_basis CAUSAL_DATA_PHASE_V1. Tests: pure A/B/C/edge/fallback/ordinary + E2E Case B (fails on old code: N/A; passes new)
- Flake root-caused: lock written before record_start (version hash + git commit lookup) -> test read the first-start row under load. Test-only fix: wait for restart's deployment row. Failed output saved f3_tests_run1.txt; 81/81 x3 after
- Declaration #4 REPORTING_ONLY (not engine DATA_FIX: that table flags detection/classification/candidate_counts) -> boundary 20260925T131932Z-outcomes-d0b191 RULE:CONFIG_FINGERPRINT_CHANGED impacts mfe_mae/win_rate/profitability only
- outcomes 18852->2052; 8 other PIDs unchanged; candidates/events/outbox/held/budget unchanged; outcome rows 0 (no split); pushed 478d6fc; loop relaunched (bceez7nde)

## 13:28–13:31Z — AFL cross-pipeline trace (read-only)
- 0001104659-26-110660 Form 4 AFLAC, owner Japan Post Holdings (CIK 1783464), 2 txns code S. raw acceptanceDateTime 09:00:16 "Z" = NY wall clock (ET-labelled-Z); resolve_acceptance(observed 13:04:09Z) → 13:00:16Z (card correct). text_events ingested 13:04:09 (poll, ~4 min), significance HIGH (information-significance-v1) 13:04:06, intelligence_delivery SENT 13:06:22 msg 59 (telegram-intel-v1 CONCISE IMMEDIATE) = Signal INFO path per 96F contract
- 30d AFL codes: S 39 (2 owners), M 2, F 1, NULL 1 → card "2 distinct insiders sold ... 35 txns ~$33.19m" = rolling window
- Opportunity catalyst: insider_open_market_owners counts ONLY code P → sale gives 0 insider owners; the Form 4 would attach only as "other SEC filing(s): 4" (strength OTHER, if in prev_session..scan_day and accepted ≤ decision)
- V2: live path from_insider_store(classification=OPEN_MARKET_PURCHASE) + config.transaction_code 'P' asserted → S cannot qualify; no BUY/SELL/paper path from intelligence cards. INFO: form4_source.from_rows defaults a MISSING transaction_code key to "P" (parquet/test path only; parquet pre-filtered to P; live store path filters by class) — latent, not reachable live
- "feed-poll currency not tracked": renderer.py:254 — card.freshness is UNKNOWN for all events (freshness.py EDGAR-poll tracker not wired into card construction). Display-only / observability gap; the filing time shown is exact. Not a processing risk.
- Discovery-phase shadow: classification is phase-independent (features@as_of + catalyst@now); phase drives horizons, stale gate, evaluator scope, labels only

## 15:08–15:22Z — V2 → SIGNAL FUNNEL AUDIT (read-only)
- V2 CURRENT tick 193, started 07:08:25Z, V2-PAPER-RC1, strategy e2acf6454789217e, provider ac5e51aa3599d6c9, PAPER, cash 100000, 0 pos/intents/exits/blocks, v2_alert_outbox 0 rows ever
- Source (insider store, 45d lookback since 08-11): 57 code-P rows / 25 issuers; 3 dropped by transaction_date window (CFG x2, CZR late filings) → 54; scope (39 POLLED watchlist) keeps 11 (ABCL 4, ADC 6, INTC 1), drops 43
- Today: 21 filings / 6 symbols ingested (19 Form 4 + 2 8-K); txns in them: A 15, M 2, NULL(Form 3 INITIAL_HOLDING) 7, S 5; code P = 0
- Clusters in scope: ABCL (3 owners Aug 14-18) → SKIPPED_ENTRY_STALE; ADC (2nd owner 09-17, eligible 09-18) → SKIPPED_NO_PRIOR_INTENT (campaign created 09-21); INTC 1 owner. Out of scope clusters: APTV 3 owners, CE 3 owners (Aug, expired)
- Code path: codes.py maps only 'P'→OPEN_MARKET_PURCHASE; missing/unknown→UNCLASSIFIED; ledger mismatches 0; live from_insider_store filters class; from_rows default-P only on parquet/test path
- **HIGH latent defect**: talonx_v2.delivery.OfficialTelegramTransport uses TelegramClient() → DispatchConfig default TELEGRAM_BOT_TOKEN, which is REVOKED (getMe 401). Signal = TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN (@TalonXSignalBot), used by intelligence cards + checked by release_gate. A V2 BUY/SELL would be FAILED (non-retryable). Not fixed: frozen V2 + restart → awaiting approval
- Signal today: 1 IMMEDIATE INFO (AFL, SENT 13:06:22, @TalonXSignalBot); 18 MEDIUM DIGEST PENDING (UNH 15, AAPL, C, MSTR) — digest last SENT 09-15 (27,807 EXPIRED historical; DIGEST_DISABLED); Sentinel today: V2 STARTUP SENT 07:08:30

## 15:44–16:00Z — V2 SIGNAL ROUTING FIX (authorized ROUTING_FIX)
- Pre (v2_pre_fix.json 15:45:36Z): V2 21032→21408 tick 207; campaign V2-PAPER-RC1; strategy e2acf6454789217e; provider ac5e51aa3599d6c9; cash 100000; 0 pos/intents/exits/blocks/outbox; DB sha 891cddac (unchanged since 07:08); getMe: TRADE_EVENT=@TalonXSignalBot, TELEGRAM_BOT_TOKEN=401, OPERATIONS=@TalonXSentinalBot, RESEARCH=@TalonXLabBot
- Commit 0e51701 (pushed): OfficialTelegramTransport → telegram_client_for(TRADE_EVENT), HOLD if disabled (no default client); gate + signal_transport_binding + signal_transport_bot_live (getMe via telegram_bot_identity); preflight FREEZE_SIGNAL_ROUTING_FIX_FILES=(talonx_v2/delivery.py); tests/test_v2_signal_routing_fix.py 13 pass; suites 223+16 pass; 14 failures in the broad v2/task131 sweep are PRE-EXISTING (identical without the fix; md5 fixtures, V1 fp, task114/117 prospective arg tests, dashboard shape)
- Boundary file boundary_v2_signal_routing.json (ROUTING_FIX; notification/alert_delivery only)
- Restart V2 only 15:53:52Z: killed 21032/21408(+helper 18608); relaunched identical argv/env/cwd/log → shim 20216 → real 12840; session.pids.json backed up + v2_companion_pid=20216; startlock rebound (owner token verified, atomic replace)
- Startup gate READY (23 checks incl. the 2 new); provider QUALIFIED ac5e51aa3599d6c9; tick 1 cash 100000
- Post: all stable table hashes SAME, DB sha SAME, fps SAME, alert_outbox 0, Opportunity 9 PIDs unchanged; gate with live env READY 0 failed (binding PASS, bot_live PASS @TalonXSignalBot)
- Note: direct talonx_v2.run restart emits no Sentinel STARTUP card (prospective start owns it); Sentinel route verified via gate
- Dispatcher audit: talonx_signals/dispatcher.py TelegramSenderAdapter has the same default-client pattern but is only reachable via the RETIRED Experimental lane (refuses without --allow-retired; not running) → not patched

## 16:00–16:20Z — OBSERVABILITY FIX + SEC REFRESH PREP + AH TRACKER
- Part C (49e224a, pushed): opportunity_read.component_health: pid dead→DOWN; alive+lock+hb 180-900s→BUSY_LONG_SCAN; alive >900s (or no lock evidence)→STALE_HEARTBEAT; overall/ping treat BUSY as healthy. REPORTING_ONLY (not in any component hash); no component restart; CLI live immediately; dashboard picks it up on its next restart. Tests +5; test_19 expectation DOWN→STALE_HEARTBEAT (alive pid). 3 dashboard-suite failures pre-existing (identical without fix)
- Part B (68784b8, pushed): talonx_opportunity/sec_refresh.py BackgroundSecCache + TALONX_SEC_BACKGROUND_REFRESH_ENABLED (default OFF → plain SecSubmissions, unchanged config fps). 9 tests incl. discovery OFF/ON parity. PREPARED_NOT_ENABLED: live discovery 15904 has no flag, not restarted. TODO next version: add sec_refresh.py to discovery COMPONENT_SOURCES
- AH tracker: ah_truth.py generated from regular_truth.py (TARGET=AFTER_HOURS, T0=20:00Z, T1 20:01, T2 20:16), evening shadow from 20:00Z only; budget LIMIT=75 fixed in both trackers. Armed: bu7jtdqm0 (first wall-clock AH scan), b0qbaw2au (first AH-data scan), b1da627md (first true AH setup + Lab)

## 16:35–16:50Z — SEC REFRESH REDESIGN (still OFF) + AH tracker validated
- First design root cause measured (N=1250, 1:50): 7,790/9,650 refresher requests during active scans; discovery cache-hit wait p99 7.05 s max 21.1 s; queue depth 0-5 (contention, not backlog); yielded 0
- Redesign 6e8dae6 (pushed): idle-gated (no lookup for 2 s; re-checked before every request), oldest-first, refreshable from age >=120 s, exception-safe refresh. N=1250: scans 25 s, 6 bg requests during scans, hit wait max 0.8 s, yielded 83
- Bench OFF→ON heavy p90: 500 164→24, 750 238→24, 1000 306→24, 1250 382→24, 1500 453→24, 2000 594→24; served age max <600 all sizes (2000: 581); 0 steady fallbacks; SEC requests ~8.4k/run ON vs 2-10k OFF
- Capacity model (0.26 s/req, idle-only lane): required/available per 600 s 500 667/2108 SAFE, 1000 1333/2108 SAFE, 1250 1667 TIGHT(+26%), 1500 2000 TIGHT(+5%), 2000 2667 INSUFFICIENT(-21%) → sync fallback preserves contract
- Tests 17 pass; regressions 149 pass. SEC_BACKGROUND_REFRESH = PREPARED_NOT_ENABLED (live discovery 15904 flag unset, not restarted)
- AH tracker replay (AH_T0=13:30, AH_TARGET=REGULAR) reproduces regular_truth exactly (timeline, first-seen 1378/1356, transition 22/60, 443 true setups)
- Studies 16:40: setup SENT n57 1h +0.58 conf 63% inval 14% vs HELD n395 1h +0.68 conf 68% inval 1%; FADE shadow 90/428 would requalify (21%, 23 BULLISH) — up from 7%; flip-back: EDBL BULLISH blocked (GLND no longer); G=0 over 180 movers

## 17:45–17:55Z — OPPORTUNITY_PROMOTION_V1 (SHADOW)
- Start SHA 6e8dae6 → e94e335 (pushed): talonx_opportunity/promotion.py + component dispatch + 25 tests + test_15 scoped exemption with stricter test_15b + DECISION_LOG entry. Suites 160 pass
- Pre-start: 9 OE PIDs as before; Lab 242 SENT; V2 ops outbox 9 rows; max seq 3378; v2_pre_promotion.json
- Started ONLY promotion (`up --only promotion`, mode env unset → SHADOW): pid 144 → 19572; PROMOTION_START_UTC 17:53:59.749Z, START_SEQ 3378; FIRST_START OPERATIONS_ONLY; policy fp 4926c12e5eace04e; promotion_src b6abb15a85a0
- Limitation: running supervisor loop has the old COMPONENTS list → promotion is not auto-respawned today (shadow; acceptable)

## 18:00–18:08Z — PAPER_SIGNAL ACTIVATION (authorized, promotion component only)
- Precheck fix 063d4fa (pushed): promotion.main() loads .env before resolving TRADE_EVENT (was only loaded as a side effect of the outcome path); test added (85 pass)
- PRECHECK_PASS: branch ok; HEAD 063d4fa; origin/main 696370e; one promotion process (144→19572, SHADOW); V2 CURRENT tick 53; Lab 243 SENT, notifier 22620; TRADE_EVENT enabled (dedicated creds), getMe @TalonXSignalBot; no order paths; AH trackers 10424/23436 (+A0 shell)
- Final SHADOW boundary: cursor 3474, 48 evaluations, 6 PROMOTED_SHADOW (IBEX CV ALTG SIGA EZPW ALOY), 1 QUEUED (YDES 60.1), no signal outbox; v2_pre_papersignal.json
- 18:07:30 stop promotion (True); ACTIVATION_UTC 18:07:33Z; `up --only promotion` with TALONX_OPPORTUNITY_PROMOTION_MODE=PAPER_SIGNAL → 24516 → 16348
- Boundary 20260925T180733Z-promotion-d10677 STRATEGY_MATERIAL (RULE:CONFIG_FINGERPRINT_CHANGED; mapping deferred) fps mode SHADOW→PAPER_SIGNAL, promotion_src b6abb15a85a0→bf0dea2167d9
- YDES EXPIRED MODE_SWITCH_NO_CARRYOVER; 6 shadow promotions untouched; signal outbox empty; drain TRADE_EVENT enabled

## 18:42–18:58Z — SENTINEL OPERATOR CONTROL PLANE (DRY_RUN; nothing live changed)
- 063d4fa → 40386fa → 2f1b95a (test-only label change; header fix missed) → 39e5521 (fix applied; green). All pushed; main 696370e
- talonx_ops/operator_control/{__init__,store,gates,commands,scanned,sentinel}.py; dormant gates in ingestion.py (Alpaca batch), yfinance_poll.py (yfinance batch), discovery.py (members), promotion.py (reject+expire); closed FREEZE_OPERATOR_CONTROL_FILES
- Finding: the single existing command listener (DispatchAgent in run_talonx) polls the SIGNAL bot (TRADE_EVENT), not Sentinel → separate SentinelCommandPoller on OPERATIONS creds, off unless TALONX_SENTINEL_COMMANDS_ENABLED=1
- Tests 28 new; regressions 265 pass; test_telegram_listener.py 24 /ping failures PRE-EXISTING on clean HEAD
- Local DRY_RUN validation on live stores: /help,/scanned (5475 seen, 5653 evaluated, 1782 candidates, 598 setups-any-time, 12 paper signals + 6 shadow), lists, CSV 5653 rows; /exclude add TSLA → PENDING in an isolated temp DB; gates identity; ingestion fetched_symbols 5653 unchanged; all PIDs unchanged; no live operator_control.db

- 20:12Z SKIP #4 confirmed: the 20:05Z AFTER_HOURS scan ran 300.11s and ended at 20:10:00, so the 20:10 slot has no scan row. skip_impact for 20:10–20:15 is armed (b315kk2ty). One >=280 watch (blotaf357) and one general watcher to 20:30Z (bxe16fkou) are running. A3/A4 (b0qbaw2au) and A6/A7 (b1da627md) are still running. AH-reserve decision (a/b) is still pending with the user; no change applied.
- 20:15Z skip #4 impact: extra 300s latency; 45 candidates / 20 setups first seen on the 20:15 scan (as_of 19:58); class C=29, D=0; delayed setups were all Lab BUDGET_EXHAUSTED_TOTAL; no Signal impact (promotion is REGULAR-only).
- 20:25Z A3/A4: the first AH bar was visible at 20:16:00 (entitlement 960s), ingested 20:16:25, and first scanned in the 20:20 scan (first candidate FOXA). A6/A7: the first true AH setup was HP GAP_DOWN (causal bar 20:02), HELD as BUDGET_EXHAUSTED_TOTAL at 75/75, so no Lab send; AH reserve 0 (consumed by REGULAR-data sends at 20:01). DEFECT_setup_blocked_with_valid_capacity = []. The 20:20 scan ran 289.62s and ended 20:24:50, so the 20:25 slot was not skipped. 0 promotions since 20:00.
- 20:35Z SKIP #5: the 20:30 scan ran 326.95s (longest today) and ended 20:35:27, so the 20:35 slot was skipped. skip_impact 20:35–20:40 armed.
- 20:41Z skip #5 impact: 300s extra latency; 10 candidates / 1 setup (AMPL BEARISH 73.7) first seen on the 20:40 scan (as_of 20:23); C=5, D=0; AMPL had no Lab decision yet (budget 75/75 anyway); no Signal impact. The 20:40 scan took 56s.
- 20:50Z SKIP #6: the 20:45 scan ran 310.5s and ended 20:50:10. skip_impact 20:50–20:55 armed.
- 21:01Z SKIP #7: the 20:55 scan ran 328.31s (new max) and ended 21:00:28, so the 21:00 slot was skipped. Per-skip watchers retired; a single EOD job (eod_final.sh @00:10Z) computes skip impact for every slot >=20:50 plus final tracks/studies/evidence. The full-day report draft is at docs/research/evidence/2026-09-25_continuous_live_validation.md.
- 00:13Z EOD closure: 7 skips final (none after 21:00); true-AH Lab surfacings 0 (49 budget-held); G=0 of 245; all closure checks PASS; bare 'prospective status' false v2_process_dead (legacy default paths, P3-4). EOD_VERDICT EOD_CLOSED_CLEAN_WITH_FINDINGS.
