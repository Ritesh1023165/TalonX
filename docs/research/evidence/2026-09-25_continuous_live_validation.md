# Continuous Opportunity Engine: full-day live validation, 2026-09-25

- **Session:** 2026-09-25 (Thursday, XNYS), OVERNIGHT → PREMARKET → REGULAR → AFTER_HOURS, one continuous process set.
- **Branch:** `feature/continuous-opportunity-engine`. `main` is untouched at `696370e`.
- **Execution:** paper only, with no broker path.
- **Evidence:** this report plus the machine-readable files in [`2026-09-25_continuous_live_validation/`](2026-09-25_continuous_live_validation/).
- **Snapshot time:** §§1–17 reflect the stores at about 21:00Z; §7 and §6.2 carry final totals. §18, *EOD closure*, holds the end-of-session numbers (00:10Z).

| | |
|---|---|
| Pipeline | **PASS**: 9+1 components, one window, all phase transitions without a restart, cursor lag 0, 0 tick errors, 0 provider-incomplete scans |
| Detection | **PASS_WITH_FINDINGS**: 2,002 candidates / 713 setups; missed-mover class G (data present, not detected) **= 0** all day |
| Paper Signal (promotion) | **PASS**: 36 PAPER_OPPORTUNITY alerts via @TalonXSignalBot, 0 duplicates / failures / cross-sends / broker calls. Signal quality is **unproven** (see §5.3) |
| AFTER_HOURS | **DISCOVERY PASS / NOTIFICATION FAIL**: true-AH candidates and setups found; A7 = **BLOCKED_BY_NOTIFICATION_POLICY** (reserve defect, §6.2) |
| Scalability | **DEGRADED**: 7 skipped discovery slots (final; none after 21:00Z); heavy scans 290–328 s; root cause is synchronous SEC cache refresh (fix prepared, NOT enabled) |
| V2 | **HEALTHY / CURRENT**, frozen, campaign untouched; one authorized ROUTING_FIX (V2 Signal transport) |
| Sentinel control plane | Built, tested and pushed; **DRY_RUN**; not activated |

---

## 1. Executive summary

**Proven:**
- The Opportunity Engine ran all four session phases in one live window on the frozen CONTINUOUS_RESEARCH_V1 strategy, fail-closed on stale data and with a boundary for every deployment.
- It detected pre-market, regular-session and genuine after-hours movers from the SIP feed, including the 15-minute entitlement delay.
- It notified Lab (research) within a closed-list budget.
- From 18:07Z it promoted a REGULAR-only, BULLISH-only subset to paper Signal alerts, without replay and without any BUY/SELL or order semantics.

**Not proven:**
- That any of it makes money. The paper-Signal cohort is 36 alerts over under two hours: a mean of −0.17 % at +30 min, and 13 of 33 mature alerts confirmed. That is noise-level and must not be read as an edge.

**Defects found (none lost data or state):**
1. **After-hours reserve accounting used processing phase, not data phase.** Three delayed REGULAR-data setups consumed all three after-hours Lab slots at 20:01Z, so no genuine after-hours setup reached Lab.
2. **Discovery overran its 300 s cadence 7 times.** Each overrun delayed discovery by 5 minutes; one delayed a real paper Signal (ELE, 19:10Z slot).
3. **A latent V2 routing defect,** since fixed: the actionable Signal transport used the revoked legacy bot token.

---

## 2. Live architecture validated

| Component | Role | Live boundary history (runtime.db `deployment_events`) |
|---|---|---|
| ingestion | SIP 1-min aggregates, 5,653 eligible symbols | FIRST_START 07:08:59 `6fa1581` (DATA_FIX class) |
| discovery | features → gate → score → classify → lifecycle events | FIRST_START 07:08:59 `6fa1581` (STRATEGY_MATERIAL); **never restarted** |
| evaluator ×4 | INTRADAY / SAME_DAY / SHORT_TERM / LONG_TERM research states | FIRST_START 07:08:59; never restarted |
| notifier | Lab (RESEARCH) budgeted delivery | FIRST_START 07:09; ROUTING_FIX 07:39 (deliver 0→1), 12:34 (`1b5ef6f` 40/25), 12:46 (`5bb9cf4` phase reserve), 14:09 (`96da34d` REGULAR ext 75) |
| outcomes | per-candidate +30 m / +1 h / close / MFE / MAE | FIRST_START; REPORTING_ONLY 13:19 (`478d6fc`, F3 causal phase basis) |
| reporting | reports | FIRST_START; OPERATIONS_ONLY unchanged-restart test 11:43 |
| supervisor | liveness + respawn | FIRST_START 11:42 (`f5a1d92` grace fix), relaunched with each notifier change |
| promotion (new) | paper Signal lane | FIRST_START 17:53:59 SHADOW (`e94e335`); STRATEGY_MATERIAL 18:07:33 PAPER_SIGNAL (`063d4fa`) |

**Invariants observed at the snapshot:**
- Every consumer cursor equals max event seq: 4,333 for notifier, promotion and all 4 evaluators.
- 603 ingestion cycles with 0 failed batches and 1 retried; max cycle 69.7 s; `incomplete_json = []`.
- Scan states: 125 SCANNED, 11 DATA_UNAVAILABLE (OVERNIGHT; not supported by design) and 1 PROVIDER_STALE (first PREMARKET tick, held fail-closed).

---

## 3. PREMARKET findings
- **08:04Z:** OVERNIGHT → PREMARKET. The first tick was PROVIDER_STALE, since no bar is visible before 08:15Z because of the SIP delay. It was held and retried.
- **08:30:48Z:** first data-bearing scan: 1,291 data-ready and 23 alert-worthy.
- **Cadence:** 900 s in PREMARKET, 43 scans, p50 48 s, max 101 s. No overruns.
- **Budget:** the original 25-surfacing budget was exhausted by 11:45Z. The owner authorized 40/25 at 12:34, then the phase-reserved policy at 12:46 (PREMARKET extra ≤ 5, REGULAR ≥ 7, AFTER_HOURS ≥ 3). No held event was replayed.
- **Stale-invalidation finding (MEDIUM, strategy-material, deferred):**
  - 11 thin names were invalidated as "price went stale" in PREMARKET and cannot re-surface in the same window.
  - By end of day, 46 identities had been stale-closed; 26 would requalify now (11 BULLISH, 5 BEARISH).
- **Score calibration:** PREMARKET setup outcomes are poorly ordered by score (n = 23). The 90+ bucket (n = 3) had a median −24 % at +30 m, and 80–90 (n = 2) −16 %. The samples are tiny; see P2.

## 4. REGULAR findings
- **Scans:** 75 REGULAR scans; p50 71.6 s, p90 284.9 s, max 320.8 s. 15 took ≥ 240 s, 10 ≥ 280 s and 3 ≥ 300 s.
- **Data vs wall-clock phase:** the first scan on REGULAR data was 13:50Z; the first REGULAR bar was visible at 13:46Z. This was measured with a PROCESSING_PHASE vs DATA_PHASE split.
- **F3 fix (13:19Z):** outcome same-day / pre-open basis now uses causal data time.
- **Setup quality by score (REGULAR, mature rows):**

  | Score | n | ret30 med | ret1h med | confirmed |
  |---|---|---|---|---|
  | 60–70 | 490 | +0.42 % | +0.58 % | 68 % |
  | 70–80 | 153 | +0.31 % | +0.41 % | 69 % |
  | 80–90 | 42 | +0.50 % | +0.56 % | 71 % |
  | 90+ | 5 | +2.39 % | +2.40 % | 100 % |

  The 90+ bucket is small. The rest is roughly flat, so score barely separates.
- **FCFS ordering flaw (P1):** 570 cases where a weaker setup was sent before a stronger one that was then held. Example: SRZN 61.5 sent at 13:51, KITT 96.4 held at 13:56.
- **Causal simulation:** a score-ranked, rate-limited selector (FCFS@3/5 min) would pick 144 of a 632-setup pool, with ret1h median +0.54 % and 71 % confirmed. This is a simulation, not a deployed result.

## 5. PAPER_SIGNAL activation and results

### 5.1 Activation
- 17:53:59Z: SHADOW start. It recorded 6 PROMOTED_SHADOW, sent nothing and queued YDES.
- 18:07:33Z: owner-authorized PAPER_SIGNAL for the promotion component only. Boundary `20260925T180733Z-promotion-d10677` is STRATEGY_MATERIAL by fingerprint rule.
- YDES was EXPIRED `MODE_SWITCH_NO_CARRYOVER` (fix `89d5422`), so no shadow row was ever sent.
- Contract: REGULAR-only, BULLISH-only, 3 per 5 minutes, 30-minute expiry, score-ordered queue, re-validated at release. Destination is TRADE_EVENT (@TalonXSignalBot), event type `PAPER_OPPORTUNITY`. No BUY/SELL or order semantics.

### 5.2 Pipeline correctness

| Metric | Value |
|---|---|
| TOTAL_SIGNAL_SENT | **36** (outbox `TRADE_EVENT / PAPER_OPPORTUNITY / SENT` = 36) |
| UNIQUE_SYMBOLS | 36 |
| FIRST_SIGNAL | PRLB 18:14:34Z |
| LAST_SIGNAL | KDP 19:56:11Z |
| RATE_LIMIT_HOLDS | 10 released late (queue wait 236–622 s); 3 expired while queued after revalidation (TOYO, SND, AGNT: `REJECTED_WHILE_QUEUED/STALE`) |
| DUPLICATES | 0 |
| SEND_FAILURES | 0 (0 rows with attempts > 1; no `last_error`) |
| LAB_CROSS_SEND | 0 (Lab outbox: 275 rows, all RESEARCH) |
| V2_CROSS_SEND | 0 (V2 outbox today: 1 OPERATIONS STARTUP only) |
| BROKER_CALLS | 0 (no order path exists in the component) |
| After 20:00Z | 0 promotions; 33 evaluations rejected `PHASE` (REGULAR-only contract held) |

### 5.3 Signal quality (not a profitability claim)
Returns are measured from the reference price of the causal (15-minute delayed) bar, long direction.

| Horizon | n | mean | median | positive |
|---|---|---|---|---|
| +15 m | 36 | −0.08 % | −0.02 % | 17 |
| +30 m | 33 | −0.17 % | −0.13 % | 11 |
| +1 h | 18 | +0.45 % | +0.06 % | 9 |
| to 20:00 close | 36 | −0.13 % | −0.31 % | 15 |
| MFE | 36 | +1.08 % | +0.56 % | — |
| MAE | 36 | −0.93 % | −0.79 % | — |

- Confirmed 13, failed confirmation 20, pending 3. Lifecycle end state: all 36 are still BULLISH_SETUP (0 invalidated).
- AIB (+7.3 % at 1 h, MFE +12.7 %) dominates the +1 h mean.
- **Verdict:** 36 alerts in one afternoon is far too small to judge. The +30 m distribution is centred slightly below zero. No edge is claimed.

### 5.4 Latency quality

| Leg | p50 | p90 | max |
|---|---|---|---|
| causal bar → Signal sent | 1,269 s (~21 min) | 1,377 s | 1,719 s |
| of which SIP entitlement delay | ~900–960 s | | |
| scan compute (scan start → end) | 64 s | 291 s | 308 s |
| scan end → sent (rate-limit queue dominated) | 22 s | 293 s | 630 s |

- ELE was delayed a further 300 s by the 19:10Z skipped slot (§7).

## 6. AFTER_HOURS findings

### 6.1 A0–A7 timeline

| Step | Time (UTC) | Evidence |
|---|---|---|
| A0 wall-clock AFTER_HOURS | 20:00:00 | Scan 20:00:00.06 phase AFTER_HOURS, same window_id, no restart. Its data as-of was 19:44 (REGULAR data) |
| A1 first AH bar complete | 20:01:00 | bar 20:00–20:01 |
| A2 visible through SIP delay | 20:16:00 | entitlement 960 s |
| A3 first persisted AH bar | 20:16:25 | ingestion as_of 20:01 |
| A4 first scan with DATA_PHASE=AFTER_HOURS | 20:20:00 | data as-of 20:03, 289.6 s. Scans at 20:00, 20:05 and 20:15 ran on REGULAR data; 20:10 was skipped |
| A5 first true AH candidate | 20:20:00 | **FOXA** GAP_DOWN (bearish), first score 79.19, gap −2.10 %, first data as-of 20:03 |
| — first AH-data setup event | 20:20:00 | **CXW** BEARISH 94.47, −6.49 %, as-of 20:03. MATERIAL_UPDATE of a never-surfaced REGULAR candidate, so held `NOT_SURFACED_PARENT` (by design, not budget) |
| A6 first true AH setup eligible to surface | 20:20:00 | **HP** GAP_DOWN UPGRADE → BEARISH, score 69.45, move −3.14 %, causal bar 20:02, no catalyst |
| A7 first AH Lab send | — | **BLOCKED_BY_NOTIFICATION_POLICY.** HP held `BUDGET_EXHAUSTED_TOTAL` ("75/75 new surfacings used"). This is not a discovery failure |

**By about 21:00Z:**
- 138 events on after-hours data, 36 new after-hours-data candidates and 48 setup events.
- 44 after-hours-data setup events were held: 22 `BUDGET_EXHAUSTED_TOTAL` and 22 `NOT_SURFACED_PARENT`.
- 0 true after-hours surfacings reached Lab.
- Lab's after-hours SELECTED rows were all the 3 reserve-consuming REGULAR-data UPGRADEs plus 11 non-counting MATERIAL_UPDATE / INVALIDATED follow-ups of already-surfaced candidates.

**Evening phase semantics:**
- 33 of 33 compared cases differ on horizon and INTRADAY eligibility between processing phase and data phase.
- Classification is phase-independent (features at as-of plus catalyst).
- Promotion correctly rejected on phase.

### 6.2 AH reserve defect

| Item | Finding |
|---|---|
| AH_RESERVE_ROOT_CAUSE | `talonx_opportunity/notifier.py:165` looks up `later_phase_reserve` by `ev["phase"]`, which is the **processing** (wall-clock) phase. After 20:00Z every event is "AFTER_HOURS", so the REGULAR reserve of 3 no longer applies. Events whose data is still REGULAR (as-of ≤ 19:59, visible until ~20:16 because of the SIP delay) can therefore spend the 3 slots kept for true after-hours data. |
| AFFECTED_SLOTS | 3 of 3: VEON (BULLISH 72.86, +3.01 %), CERT (70.94, +3.09 %), DRVN (70.76, +3.20 %). All UPGRADE, data as-of 19:44Z, decided 20:01:07Z |
| TRUE_AH_SETUPS_HELD | **49** `BUDGET_EXHAUSTED_TOTAL` true after-hours-data setup events by session end (first: HP 20:20), plus 68 `NOT_SURFACED_PARENT` (by design) |
| DATA_LOSS | none. Every event is persisted with its decision and reason |
| STATE_LOSS | none. Candidates, lifecycle and outcome tracking are unaffected |
| DISCOVERY_IMPACT | none. Detection, classification and candidate counts are unaffected |
| NOTIFICATION_IMPACT | 0 of 3 intended after-hours Lab surfacings went to after-hours-data setups. Lab after-hours coverage for genuine after-hours movers was 0 |
| Live fix | **not applied** (owner decision: no live fix tonight) |

**Next-version acceptance criteria:**
1. Reserve consumption is keyed on the event's causal **data phase**, `phase_at(data_as_of − 1 min)`, not the processing phase.
2. A REGULAR-data event processed after 20:00Z must not consume the after-hours reserve; it competes only for REGULAR capacity.
3. A true after-hours-data event may consume the after-hours reserve.
4. No replay of held events at deployment; the boundary comes first.
5. Deterministic transition tests: PREMARKET→REGULAR and REGULAR→AFTER_HOURS with events straddling the boundary in both processing and data time.
6. Delayed-provider-data tests: a 15–16-minute SIP delay, so the first 3–4 post-transition scans carry previous-phase data.
7. The same keying is applied to any other phase-keyed budget share (PREMARKET extra).

## 7. Skipped-scan ledger (300 s-cadence phases)

| Slot | Phase | Prev scan | Prev duration | Next scan | Extra latency | Candidates delayed | Setups delayed | C (would have qualified) | PAPER_SIGNAL delayed | Lab impact | G after |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 16:50 | REGULAR | 16:45:00–16:50:20 | 320.8 s | 16:55 | 300 s | 23 | 12 | 16 | 0 (SHADOW not started) | 0 lost: all C held `BUDGET_RESERVED_LATER_PHASE` anyway | 0 |
| 17:30 | REGULAR | 17:25:00–17:30:05 | 305.6 s | 17:35 | 300 s | 21 | 6 | 17 | 0 (pre-PAPER_SIGNAL) | 0 lost (reserved) | 0 |
| 19:10 | REGULAR | 19:05:00–19:10:08 | 308.4 s | 19:15 | 300 s | 10 | 2 | 5 | **1: ELE** (sent 19:16:38; C at slot) | 0 lost (reserved) | 0 |
| 20:10 | AFTER_HOURS | 20:05:00–20:10:00 | 300.1 s | 20:15 | 300 s | 45 | 20 | 29 | 0 (REGULAR-only) | 0 lost (75/75) | 0 |
| 20:35 | AFTER_HOURS | 20:30:00–20:35:27 | 327.0 s | 20:40 | 300 s | 10 | 1 (AMPL) | 5 | 0 | 0 lost (75/75) | 0 |
| 20:50 | AFTER_HOURS | 20:45:00–20:50:10 | 310.5 s | 20:55 | 300 s | 2 | 1 (ADCT) | 3 | 0 | 0 lost (75/75) | 0 |
| 21:00 | AFTER_HOURS | 20:55:00–21:00:28 | 328.3 s | 21:05 | 300 s | 3 | 1 (POWW) | 2 | 0 | 0 lost (75/75) | 0 |

- Every skip has cause `PREV_SCAN_OVERRAN`. Every one has **0 data loss and 0 state loss**: the next scan evaluates the full window-to-date aggregate, and class D (unknown) = 0 in every impact file.
- Classes A–D in the impact files: A = not observable yet, B = observable below threshold, C = would have qualified at the skipped slot, D = unknown.
- **Final totals:** 7 skips (none after 21:00Z), 114 candidates and 43 setups first seen 300 s late (77 class C), **1 paper Signal delayed** (ELE), max scan 328.31 s, category G = 0, data loss 0, state loss 0.
- The overruns cluster in the first hour after the close: 4 of the 12 slots from 20:00 to 20:55, then 0 of 36 from 21:05 to 23:55. REGULAR had 3 of 78.

## 8. SEC scalability findings

**SEC_REFRESH_STATUS = PREPARED_NOT_ENABLED.** `TALONX_SEC_BACKGROUND_REFRESH_ENABLED` is unset in the live discovery process, which has not been restarted since 07:08:59.

- **Root cause of heavy scans.**
  - Discovery refreshes each candidate's SEC submissions synchronously when the 600 s cache entry expires, at about 0.26 s per request, single lane.
  - Heavy scans coincide with mass expiry. The offline bench reproduces live: OFF heavy p90 is 306 s at 1,000 symbols, against a live REGULAR p90 of 285 s and max 327 s.
- **First design** (`68784b8`): starved discovery. At N = 1,250:
  - 7,790 of 9,650 refresher requests ran during active scans.
  - Discovery cache-hit wait was p99 7.05 s, max 21.1 s (unfair lock contention).
  - The refresher yielded 0 times.
- **Redesign** (`6e8dae6`):
  - Idle-gated: it runs only after no lookup for 2 s, re-checked before every request.
  - Oldest-first; entries become refreshable from 120 s of age; single lane; exception-safe (the previous copy is restored on failure).
  - At N = 1,250: scans 25 s, 6 background requests during scans, hit wait max 0.8 s, yielded 83 times.
- **Benchmark, heavy-scan p90 OFF → ON:**

  | Symbols | 500 | 750 | 1,000 | 1,250 | 1,500 | 2,000 |
  |---|---|---|---|---|---|---|
  | OFF | 164 s | 238 s | 306 s | 382 s | 453 s | 594 s |
  | ON | 24 s | 24 s | 24 s | 24 s | 24 s | 24 s |

- **Freshness parity:** max served age < 600 s at every size (2,000: 581 s), and 0 steady-state sync fallbacks.
- **Classification parity:** OFF/ON discovery parity tests pass on identical inputs (17 tests).
- **Failure tests:** refresh exception keeps the prior copy; yielding under load; start/stop idempotent.
- **Single-lane capacity** (requests per 600 s, required / available):

  | Symbols | Required / available | Verdict |
  |---|---|---|
  | 500 | 667 / 2,108 | SAFE |
  | 1,000 | 1,333 / 2,108 | SAFE |
  | 1,250 | 1,667 | TIGHT |
  | 1,500 | 2,000 | TIGHT |
  | 2,000 | 2,667 | INSUFFICIENT; the synchronous fallback preserves the contract |

- **Live evidence for the fix:** 7 skipped slots; 1 paper Signal delayed 300 s; heavy-scan compute is up to 291 s (p90) of the Signal latency budget.

**Next-version enablement plan:**
1. **A.** Add `talonx_opportunity/sec_refresh.py` to discovery `COMPONENT_SOURCES`, so the version hash covers it.
2. **B.** Set `TALONX_SEC_BACKGROUND_REFRESH_ENABLED=1` in the discovery process environment only.
3. **C.** Declare a `DATA_FIX` boundary for discovery with the reason "SEC catalyst cache served by an idle-gated background refresher; classification contract unchanged". The config fingerprint gains the refresh key only when ON.
4. **D.** Restart **discovery only**. No other component PID may change.
5. **E. Cold start:** the first 1–2 scans are heavy while the cache warms, since the refresher needs idle gaps. Expect p90 < 120 s from about the third scan.
6. **F. Live acceptance:**
   - heavy-scan p90 < 120 s
   - 0 skipped slots after warm-up
   - discovery cache-hit wait < 2 s
   - 0 served entries ≥ 600 s
   - SEC request rate < 5/s
   - category G = 0
   - candidate parity against a same-data shadow comparison (OFF replay of the same scans)
7. **G. Rollback:** unset the flag, declare DATA_FIX, restart discovery only. The plain `SecSubmissions` path is byte-identical to today's.

## 9. Notifier findings
- **Lab totals** at ~21:00Z: 275 SENT, all RESEARCH (294 at session end; see §18). Decisions:

  | Decision | Count |
  |---|---|
  | SELECTED | 275 |
  | NOT_SURFACED_PARENT | 1,454 |
  | BUDGET_EXHAUSTED_WATCH | 1,825 |
  | BUDGET_RESERVED_LATER_PHASE | 588 |
  | BUDGET_EXHAUSTED_TOTAL | 191 |

- **Budget:** exhausted at 75/75 at 20:01Z. The after-hours reserve defect is in §6.2.
- **FCFS ordering (P1):** see §4.
- **MATERIAL_UPDATE fatigue:** 166 of 275 sends were MATERIAL_UPDATE; 52 of them were LOW-information and suppressible. Top repeaters were INLF and APUS with 19 each.
- **Sent vs held, all mature rows:**

  | Cohort | n | ret30 median | confirmed |
  |---|---|---|---|
  | SENT | 75 | +0.62 % | 61 % |
  | HELD | 1,793 | −0.13 % | 41 % |

  The held cohort is WATCH-dominated. Among REGULAR setups after the extension, sent (n = 35, ret1h median +0.78 %) and held (n = 514, +0.56 %) are similar. Holding cost little on average.

## 10. Lifecycle findings (shadows, evidence only)

| Rule | Closed | Would requalify now | Outcome of original identity (ret30 med) |
|---|---|---|---|
| stale ("price went stale") | 46 | 26 (10 W / 11 BULL / 5 BEAR) | −0.36 % (41 % confirmed) |
| fade ("gap faded below 1 %") | 824 | 178 (119 W / 32 BULL / 27 BEAR) | −0.56 % (23 % confirmed) |
| flip ("gap flipped direction") | 20 | 3 | −3.81 % (70 % invalidated) |

- Stale closure is the clearest loss: resumed names such as AESI and MFG requalify as BULLISH_SETUP.
- Fade closure mostly removes names that stay dead: 646 of 824 no longer qualify.
- Flip closure is protective: the original identities were mostly invalidated with large adverse moves.

## 11. Missed-mover coverage
At 20:55:51Z there were 243 actionable movers of at least 5 %, judged causally against TalonX's own SIP aggregates.

| Class | Meaning | n |
|---|---|---|
| A | detected and sent | 27 |
| B | detected, held by notification policy | 171 |
| C | detected, not notification-eligible | 0 |
| D | rejected by scoring / entry rule (mostly thin: < 3 % activity) | 12 |
| E | blocked by stale invalidation | 13 |
| F | provider data unavailable | 0 |
| **G** | **data available but not detected (defect)** | **0** |
| H | closed by another lifecycle rule, worthy now | 20 |
| I | other | 0 |

G was 0 at every checkpoint: 16:51 (190 movers), 17:36 (208), 19:16 (228) and 20:55 (243). The end-of-session pass is in §18.

## 12. V2 status
- Frozen strategy `e2acf6454789217e`, provider `ac5e51aa3599d6c9` (V2_RELEASE_PRICE_CONTRACT@1), campaign V2-PAPER-RC1, $100,000 / $10,000.
- 0 positions, 0 intents, 0 trades. HEALTHY / CURRENT (heartbeat ~12 s).
- **ROUTING_FIX `0e51701` (authorized, 15:53Z):** `OfficialTelegramTransport` now resolves the TRADE_EVENT (@TalonXSignalBot) destination.
  - Previously it used the revoked legacy `TELEGRAM_BOT_TOKEN` (401), so a V2 BUY/SELL alert would have FAILED.
  - It HOLDs when the destination is disabled, with no legacy fallback.
  - The release gate gained `signal_transport_binding` and `signal_transport_bot_live`.
  - V2-only restart; the campaign DB SHA-256 (`891cddac…`) and every stable table hash were unchanged.
- V2 alert outbox today: 0 actionable rows (1 Sentinel STARTUP). No code-P insider cluster in scope today.

## 13. Sentinel control-plane status
- `talonx_ops/operator_control/` provides `/help`, `/universe`, `/exclude` and `/scanned` (with CSV) on the Sentinel (OPERATIONS) bot. It is pushed at `39e5521`.
- **Mode:** DRY_RUN. Gates are an exact identity; the live fetch universe was unchanged at 5,653; no `operator_control.db` exists; no poller is running.
- **Tests:** 28 new. Local DRY_RUN validation ran against the live stores read-only.
- **CONTROL_PLANE_ACTIVATION_READY = NO (prepared).** Blockers:
  1. The prospective single-poller health check (`talonx_ops/prospective/telegram_owner.py`) must recognise the registered Sentinel poller. Today a second getUpdates owner raises `multiple_telegram_pollers`.
  2. Real-Telegram DRY_RUN verification has not been done: `/help`, `/help exclude`, `/help universe`, `/scanned`, `/scanned file`, `/exclude status`, `/universe status`.
  3. Owner authorization for ACTIVE mode after EOD closure.
- **Exact restart set for ACTIVE:**
  - Start `python -m talonx_ops.operator_control.sentinel` with `TALONX_SENTINEL_COMMANDS_ENABLED=1`.
  - With `OPERATOR_UNIVERSE_MUTATION_MODE=ACTIVE`, restart:
    - Opportunity **ingestion** (Alpaca batch gate)
    - **discovery** (members gate)
    - **promotion** (exclude gate)
    - **run_talonx** (yfinance batch gate in `talonx_ingest/market_data/yfinance_poll.py`)
  - Each gets a declared boundary. Evaluators, notifier, outcomes, reporting and V2 are not restarted.
- **Activation proof:**
  1. Exclude one liquid non-V2 symbol.
  2. Prove it is absent from the next yfinance and Alpaca batches.
  3. Prove there is no discovery event and no promotion for it.
  4. Restore it and prove it reappears without replay of any missed interval.
- **ROLLBACK:** set `OPERATOR_UNIVERSE_MUTATION_MODE=DRY_RUN` (unrecognised values also fail safe to DRY_RUN) and restart the same four components. Stop the Sentinel poller. `operator_control.db` is retained as intent history.

## 14. Next-version backlog (ranked)

| # | Item | Problem / evidence | Component | Strategy-material? | Restart | Tests | Live acceptance | Depends on |
|---|---|---|---|---|---|---|---|---|
| **P0-1** | SEC background refresh enablement | 7 skips, heavy p90 285 s, ELE +300 s (§7, §8) | discovery | No (DATA_FIX; classification parity) | discovery only | existing 17 + parity replay | §8 F | — |
| **P0-2** | AH reserve keyed on DATA_PHASE | 3 of 3 AH slots consumed by REGULAR data; A7 blocked (§6.2) | notifier | No (ROUTING_FIX, notification only) | notifier only | transition + delayed-data (§6.2) | the first true after-hours setup within capacity is sent; 0 REGULAR-data consumption after 20:00 | — |
| **P0-3** | Sentinel health check + poller activation | single-poller check would flag the Sentinel poller (§13) | talonx_ops prospective + operator_control | No (OPERATIONS_ONLY) | new poller process | health-check unit test; real-Telegram DRY_RUN | 7 commands answered; no `multiple_telegram_pollers` | — |
| **P0-4** | Provider-mutation activation proof | ACTIVE never exercised live | ingestion, discovery, promotion, run_talonx | Universe change is DATA_FIX per component | the 4 in §13 | existing 28 + live proof | exclude / restore proof with no replay | P0-3 |
| **P0-5** | Promotion supervisor/status hardening | promotion is not in `supervise.COMPONENTS` (`talonx_opportunity/supervise.py:21`), so it is started by hand and never respawned; absent from status and dashboard | supervise.py, opportunity_read, dashboard | No (OPERATIONS_ONLY) | supervisor + dashboard | respawn test; status row | promotion shown UP / BUSY; killed → respawned, no replay | — |
| P1-1 | Ranked, rate-limited notifier | FCFS: 570 weaker-before-stronger; KITT 96.4 held behind SRZN 61.5 | notifier | notification-only (ROUTING_FIX) but a policy change: pre-register | notifier | causal-sim replay | score p50 of sent ≥ held; rate cap honoured | P0-2 |
| P1-2 | Low-information update suppression | 52 of 166 MU sends LOW; INLF / APUS 19 each | notifier | notification-only | notifier | fatigue fixture | MU LOW sends → 0; no HIGH suppressed | — |
| P1-3 | Stale as a temporary state | 46 stale-closed, 26 requalify (AESI, MFG) | discovery lifecycle | **Yes** (CONTINUOUS_RESEARCH_V2) | discovery | resume / requalify tests | E class → ~0; no stale flapping | pre-registration |
| P2-1 | Phase-aware score calibration | PREMARKET 80+ setups negative (n = 5); REGULAR buckets flat | discovery scoring | **Yes** | discovery | offline calibration study | multi-day out-of-sample only | ≥ 5 sessions of data |
| P2-2 | Open-burst feature calibration | 669 UPGRADE burst; 96 crossed the $500k gate, 432 crossed score 60 | discovery features | **Yes** | discovery | burst decomposition | lower burst share without G > 0 | P2-1 |
| P2-3 | Fade re-entry | 824 fade-closed, 178 requalify | discovery lifecycle | **Yes** | discovery | shadow first | shadow-requalified cohort outcome ≥ fresh cohort | P1-3 |
| P2-4 | Flip-back identity handling | 20 flips, 3 requalify; original identities mostly invalidated | discovery lifecycle | **Yes** | discovery | identity tests | no duplicate identities | P2-3 |
| P3-1 | Legacy cleanup | retired Experimental dispatcher keeps a default-client pattern (not reachable) | talonx_signals | No | none | — | — | — |
| P3-2 | Telegram / CONTROL cleanup | legacy `TELEGRAM_BOT_TOKEN` is revoked but still the DispatchConfig default; 24 pre-existing `/ping` listener test failures | talonx_dispatch | No | run_talonx | listener suite green | — | — |
| P3-4 | Prospective status default paths | bare `prospective status` reads legacy `v2_lane.db` / `v2_service_status.json`, giving a false `v2_process_dead` (§18.4) | talonx_ops/prospective/paths.py | No | none (CLI) | path-resolution test | status without env overrides reports the release session | — |
| P3-3 | Stale config / dead fallback cleanup | `declared=0` display flag on the fingerprint rule path; outcome-card freshness UNKNOWN | runtime.py (all hashes), renderer | No (REPORTING_ONLY) | all (runtime.py is in every hash), so batch it with a planned restart | — | — | planned full restart |

**PROMOTION_HARDENING_ITEMS** (prepared, not implemented):
1. Add promotion to the supervisor `COMPONENTS` list with the same startup grace.
2. Add a promotion row to `opportunity_read` status and the `:8787` dashboard (mode, queue depth, last release, rate-window use).
3. Classify a mode switch (SHADOW ↔ PAPER_SIGNAL) as ROUTING_FIX via a closed declaration. Today it is recorded as STRATEGY_MATERIAL because the rule maps any fingerprint change that way.
4. Keep the no-carry-over rule at mode switch and the cursor-at-start (no replay) boundary.
5. Freeze the v1 contract (REGULAR-only, BULLISH-only, 3 per 5 minutes, 30-minute expiry) in a policy fingerprint test.
6. Keep the broker path absent, with an AST/import guard test so the component cannot import an order client.

## 15. Known limitations
- Outcomes use the reference price of the causal delayed bar, not a simulated fill at send time (~21 minutes later).
- The paper-Signal cohort is n = 36 over under 2 hours: no statistical power.
- AH evidence covers one evening. AH liquidity is thin, and 351 names were stale for more than 45 minutes at 20:55.
- Missed-mover judgement uses TalonX's own SIP aggregates, so movers invisible to SIP are out of scope.
- `skip_impact` re-scores with the actual event's catalyst label (the SEC set can only grow within 5 minutes).
- SQLite lock waits and per-tick evaluator/notifier durations are not instrumented; cursor lag and heartbeat are the proxies.

## 16. Exact SHAs and boundaries
- Session start `6fa1581`. Pushed during the day, in order:
  `f5a1d92`, `1b5ef6f`, `5bb9cf4`, `478d6fc`, `96da34d`, `e169edd`, `0e51701`, `49e224a`, `68784b8`, `6e8dae6`, `e94e335`, `89d5422`, `063d4fa`, `40386fa`, `2f1b95a`, `39e5521` (HEAD before this report).
- `main` is `696370e` (untouched).
- Engine boundaries are listed in §2 and in `evidence/eod_evidence.json` → `deployments` (22 rows).
- V2 boundary: `boundary_v2_signal_routing.json` (ROUTING_FIX, 15:53Z).
- Promotion: `20260925T175359…` FIRST_START SHADOW; `20260925T180733Z-promotion-d10677` PAPER_SIGNAL.
- **Process note:** `2f1b95a` was pushed with a failing test (a test label changed without the code). It was fixed in `39e5521`, and later commits were gated on a green suite.

## 17. What was NOT changed live
- **Discovery:** scoring, gates, lifecycle rules, horizons and cadence. The discovery process ran from 07:08:59 without a restart.
- **Evaluators:** research-state rules.
- **V2:** strategy, provider, campaign, cash and ledger. The only V2 change was transport routing.
- **SEC background refresh:** never enabled.
- **After-hours reserve:** not fixed live (owner decision).
- **Sentinel operator control:** no poller, no ACTIVE mode, no universe mutation.
- **Replay:** no held or earlier event was ever replayed, at any boundary.
- **Execution:** no real-money execution and no broker orders. No BUY/SELL semantics in Lab or promotion.
- **Isolation:** no Lab ↔ Signal ↔ Sentinel cross-routing; research never emitted a V2 TRADE_EVENT.
- **Providers:** no paid provider or subscription added.
- **Secrets:** no bot token printed or committed.

## 18. EOD closure (00:10–00:13Z, 2026-09-26)

After-hours ended at 00:00Z. The last after-hours-data scan was 23:55Z (as-of ~23:44). Final evidence is in `eod_evidence_final.json`, `missed_movers_final.json` (pinned to 23:59:30Z, window 2026-09-25), `outcome_studies_final.json` and `skip_2100.json`.

### 18.1 Final after-hours numbers
- **After-hours scans:** 44; p50 36.2 s, p90 289.6 s, max 328.3 s. 4 skips, all between 20:00 and 21:00.
- **After-hours-data volume:** 355 events, 99 new candidates, 140 setup events.
- **True after-hours setups held:** 117 in total.
  - 49 held `BUDGET_EXHAUSTED_TOTAL`.
  - 68 held `NOT_SURFACED_PARENT` (by design).
- **True after-hours Lab surfacings:** **0**. A7 stays BLOCKED_BY_NOTIFICATION_POLICY for the whole evening.
- **Lab after hours:** 33 SELECTED in total. Only 3 counted as new surfacings: VEON, CERT and DRVN, the REGULAR-data reserve consumers.
- **F3 cross-check:** outcome rows `NOT_APPLICABLE_SAME_DAY` = 99 = the after-hours-data new candidates. The causal-data-phase outcome basis behaved exactly as designed; no REGULAR-data candidate was marked N/A.

### 18.2 Final missed-mover pass (23:59:30Z)

| A | B | C | D | E | F | **G** | H | I | Total |
|---|---|---|---|---|---|---|---|---|---|
| 27 | 174 | 16 | 7 | 5 | 0 | **0** | 16 | 0 | 245 |

Compared with 20:55: C appears (16) and E/H shrink, because after-hours re-scoring moved closed identities from "worthy now" to "not worthy now". G stayed 0 all day.

### 18.3 Final outcome study: shifts from the 17:30 checkpoint
- **Sent vs held (all):** unchanged within noise. SENT n = 75, ret30 median +0.62 %, 61 % confirmed. HELD n = 1,990, −0.13 %, 39 %.
- **Paper-Signal cohort:** unchanged since 20:00 (outcomes are REGULAR-close based). 13 confirmed, 20 failed, 3 pending.
- **Lifecycle shadows ("would requalify now"):**

  | Rule | 20:55 | 00:10 |
  |---|---|---|
  | stale | 26 | 10 of 46 |
  | fade | 178 | 74 of 881 |
  | flip | 3 | 5 of 29 |

  The drop reflects the end-of-evening thin after-hours tape, not new evidence against re-entry. **No meaningful shift; small samples; no conclusion changed.**
- **Fatigue:** 294 Lab sends; MU LOW 66 (52 at 20:55).

### 18.4 Closure checks

| Check | Result |
|---|---|
| All expected components healthy | **PASS**. 10 engine components RUNNING, heartbeats < 4 s. Supervisor loop, run_talonx, ops supervisor, dashboard, intelligence poller and V2 companion are each exactly one shim/real pair |
| No unexpected positions/orders | **PASS**. V2 positions 0, trades 0, pending intents 0; no broker path in the engine |
| V2 state current | **PASS**. HEALTHY / CURRENT, tick 199, cash $100,000, campaign V2-PAPER-RC1, contract `ac5e51aa3599d6c9`, 0 critical flags (release paths) |
| Promotion stopped after REGULAR | **PASS**. 0 promotions after 20:00; 236 evaluations rejected (PHASE 50, WATCH 152, BEARISH 34) |
| AH discovery completed | **PASS**. Last AH-data scan 23:55Z |
| No duplicate watchers | **PASS**. No validation script running; all trackers exited |
| No pending Signal outbox failures | **PASS**. Promotion outbox 36/36 SENT, 0 retries, 0 errors. V2 alert outbox 0. V2 ops outbox 1 SENT |
| No Lab cross-send | **PASS**. Lab 294/294 RESEARCH; promotion 36/36 TRADE_EVENT; 0 BUY/SELL |
| No provider-incomplete | **PASS**. Max 0 across 173 scans; 756 ingestion cycles, 0 failed batches |
| No cursor lag | **PASS**. All 6 consumers at seq 4,550 |
| Runtime DBs consistent | **PASS**. `PRAGMA quick_check` ok on all 12 engine DBs and `v2_release_rc1.db` |

**New finding (LOW, operations):** a bare `python -m talonx_ops.prospective status` defaults to the legacy `v2_lane.db` / `v2_service_status.json` (09-15, $300k). It reports a false `v2_process_dead`. With `TALONX_V2_DB_PATH` / `TALONX_V2_STATUS_PATH` pointed at the release files it reports HEALTHY with 0 flags. This is backlog item P3-4.

**Not run:** the V2 prospective EOD close (`eod: NOT_DUE_YET` at 00:12Z). It belongs to the V2 release procedure and is left for the operator.

### EOD_VERDICT: **EOD_CLOSED_CLEAN_WITH_FINDINGS**
Findings: the AH reserve defect (P0-2), the discovery overrun / SEC refresh (P0-1), and the prospective-status default paths (P3-4).

## 19. Follow-up (2026-09-26)
- Items P0-1 (SEC background refresh) and P0-2 (AH reserve on DATA_PHASE) were implemented and deployed on 2026-09-26 (non-trading day). See [2026-09-26_p0_package1_acceptance.md](2026-09-26_p0_package1_acceptance.md).
- **Erratum:** 2026-09-25 was a **Friday** (not Thursday, as the header states).
- The V2 end-of-day close for this session was not run (finding F-P3 in the follow-up).
