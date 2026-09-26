# Monday 2026-09-28 runbook: SEC live acceptance, provider-control activation, AH reserve confirmation

**Replaces** the weekend's long-lived shell waiters, all of which were stopped on Saturday.
**Conventions:**
- Every command runs from `C:\workspace\TalonX` with `.venv\Scripts\python.exe` (below: `PY`).
- Run engine CLI commands with `TALONX_OPP_ROOT` unset.
- Times are UTC (EDT: PREMARKET from 08:00Z, the SIP delay makes the first REGULAR bar visible at about 13:46Z, close 20:00Z, first after-hours data about 20:16Z).

**State left on Saturday 2026-09-26:**

| Item | State |
|---|---|
| Engine processes | 10 engine components + `sentinel` running, supervised by one loop (`up --deliver --supervise`) |
| Supervisor-loop environment | `TALONX_SEC_BACKGROUND_REFRESH_ENABLED=1`<br>`TALONX_NOTIFY_RESEARCH_ENABLED=1`<br>`TALONX_OPP_NOTIFY_POLICY=LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925`<br>`TALONX_OPPORTUNITY_PROMOTION_MODE=PAPER_SIGNAL`<br>`TALONX_SENTINEL_COMMANDS_ENABLED=1`<br>`OPERATOR_UNIVERSE_MUTATION_MODE=DRY_RUN` |
| SEC background refresh | DEPLOYED; live acceptance **pending** |
| AH reserve fix | ACCEPTED on replay; live confirmation **pending** |
| Sentinel | ENABLED, **DRY_RUN** (no provider mutation) |
| V2 | 2026-09-25 EOD closed (PASS_WITH_FINDINGS); healthy, $100,000, 0 positions |
| Pending version-bound OPERATIONS_ONLY declarations (F-P2) | discovery, 4 evaluators, notifier, outcomes, promotion, reporting |
| Ingestion | **not** declared: its own source changed (the dormant operator gate), so it classifies normally |

## 1. MONDAY MORNING (before 08:00Z)

1. **Preflight and V2.** Use the release environment from `docs/OPERATIONS.md`, i.e. `TALONX_V2_DB_PATH`, `TALONX_V2_STATUS_PATH` and `TALONX_NOTIFY_DB_PATH` pointing at the `v2_release_rc1*` files.
   - Run `PY -m talonx_ops.prospective status`.
   - Expect: HEALTHY / CURRENT, cash 100000, no critical flags.
   - `eod` must **not** be `OVERDUE_EOD_CLOSE`. If it is, run the bounded close for the session it names: `close --session-dir <dir> --force --no-shutdown`, with the release environment set.
   - Note: `status` without the release environment reads the legacy `v2_lane.db` and shows a false `v2_process_dead`.
2. **Engine health.** Run `PY -m talonx_opportunity status`. Expect:
   - overall HEALTHY
   - `promotion` mode=PAPER_SIGNAL (see the **decision** in §6)
   - `sentinel` mode=ENABLED universe=DRY_RUN
3. **Boundaries.** Run `PY -m talonx_opportunity deployments --window 2026-09-28` and check for no unexpected STRATEGY_MATERIAL rows.
4. **Poller health.** Run `PY -c "from talonx_ops.prospective.telegram_owner import logical_poller_report as r; print(r().to_dict())"`.
   - Expect `EXPECTED_DISTINCT_POLLERS`: SIGNAL 1, SENTINEL 1.
5. **Sentinel.** Send `/status` in the Sentinel chat and expect the compact status reply.

## 2. MONDAY REGULAR: SEC live acceptance

1. Run after about **16:00Z**, which covers the 13:45–15:30Z heavy-scan period:
   `PY docs\research\evidence\2026-09-26_p0_package1\tools\live_acceptance.py 2026-09-28 > results\p0_package1_2026-09-26\live_acceptance_1600.json`
2. **Warm-up scans 1–2** (cold cache) are reported separately; they may be heavy.
3. **Steady-state criteria (every one must pass):**
   - heavy-scan p90 < 120 s
   - 0 skipped 300 s slots
   - cache-hit wait p99 < 2 s
   - max served age < 600 s
   - SEC rate < 5/s
   - no provider-incomplete
   - notifier cursor lag 0
4. **Category G:** run the full-day missed-mover audit (`docs\research\evidence\2026-09-25_continuous_live_validation\tools\live_tracks.py` with `TRACK_NOW` unset during the session). Category G must be 0.
5. **Parity:** optional repeat of `docs\research\evidence\2026-09-26_p0_package1\tools\sec_parity.py`; expect 0 mismatches.
6. **Verdict:**
   - `VERDICT: ACCEPTED` → record SEC_REFRESH = ACCEPTED in the P0-1 acceptance doc.
   - Otherwise roll back:
     1. Stop the supervisor loop (its two PIDs only).
     2. Relaunch the loop **without** `TALONX_SEC_BACKGROUND_REFRESH_ENABLED`.
     3. `PY -m talonx_opportunity declare-change discovery --class DATA_FIX --reason "rollback SEC background refresh"`.
     4. `PY -m talonx_opportunity restart discovery`.

## 3. MONDAY PROVIDER CONTROL (only after SEC passes, and only with explicit owner authorisation)

**Pre-checks:**
- `/exclude list` and `/universe list` in Sentinel. Any leftover PENDING intent would become effective on ACTIVE, so clear it first.
- Choose a liquid, non-V2-scope test symbol (not one of the 39 V2 names). Example: `/exclude add SNAP P0-2B proof`.

**Boundaries.** `OPERATOR_UNIVERSE_MUTATION_MODE` is **not** in any component's config fingerprint (finding F-W2), so declare every restart explicitly **before** it. A fresh declaration supersedes the pending OPERATIONS_ONLY one (the latest wins).
```
PY -m talonx_opportunity declare-change ingestion --class DATA_FIX --reason "ACTIVE operator universe gate (Alpaca batch)"
PY -m talonx_opportunity declare-change discovery --class DATA_FIX --reason "ACTIVE operator universe gate (members)"
PY -m talonx_opportunity declare-change promotion --class OPERATIONS_ONLY --reason "ACTIVE operator exclusion gate"
```

**Restart set.**
1. Relaunch the supervisor loop with `OPERATOR_UNIVERSE_MUTATION_MODE=ACTIVE`, plus the same other environment as above.
2. Then `restart ingestion`, `restart discovery` and `restart promotion`.
3. **yfinance (Original):** `run_talonx.py` is owned by the ops supervisor (`talonx_ops.supervisor run`). It picks up ACTIVE only when Original is restarted with that environment. That is a V2-adjacent stack restart, so do it only in a pre-open window, or run the Alpaca proof alone first and defer the yfinance proof.

**Proof sequence:**
1. `/exclude add <SYM>` returns ACTIVE.
2. The next ingestion cycle's Alpaca batches omit `<SYM>` (`market.db` `ingestion_state.symbols` drops by 1; `aggregates` for `<SYM>` stop advancing).
3. The yfinance batch omits `<SYM>`, if Original was restarted.
4. No new `candidate_events` for `<SYM>`, and no promotion evaluation other than `OPERATOR_EXCLUDED`.
5. `/exclude remove <SYM>`: the symbol reappears from the next cycle, with **no** events for the excluded interval (no replay).
6. Optional: `/universe add <SAFE_SYM>`. It is fetched from the next cycle, with no history backfill.

**Rollback:** relaunch the loop with `OPERATOR_UNIVERSE_MUTATION_MODE=DRY_RUN`, declare the same components, and restart them. Operator intent stays in `operator_control.db`.

## 4. MONDAY AFTER_HOURS: AH reserve live confirmation (20:00Z–00:00Z)
1. Poll the notifier detail with `PY -m talonx_opportunity status --json` (`notifier.detail.after_hours_reserve`), or run `live_acceptance.py 2026-09-28` after about 21:30Z.
2. **Accept if all of the following hold:**
   - `REGULAR_DATA_AFTER_CLOSE_COUNTED_NEW == 0`, i.e. REGULAR-data setups processed after 20:00 never consume the reserve.
   - The first true AH setup surfacing (data as-of ≥ 20:01Z) is SELECTED while `AH_RESERVED_REMAINING > 0`. `AH_RESERVED_USED_BY_TRUE_AH` increments by exactly 1 per true AH surfacing, up to 3.
   - A Lab SENT row exists for it (`opportunity_research_notifications.db`), and no event from before the boundary was replayed.
3. **If no true AH setup appears,** record "no AH candidate" (not a failure) and re-check on the next session.

## 5. End of day
- The V2 prospective close runs as normal (release environment; the close deadline is the close + 90 min).
- Write the full-day evidence under `docs/research/evidence/`.

## 6. Open decisions for the owner
- **Promotion PAPER_SIGNAL scope:** the 2026-09-25 authorisation covered "the remainder of REGULAR" that day. The component was left running in PAPER_SIGNAL (the status quo) and will send paper Signals on Monday's REGULAR session.
  - To switch to SHADOW before 13:30Z:
    1. Relaunch the supervisor loop with `TALONX_OPPORTUNITY_PROMOTION_MODE=SHADOW`.
    2. `restart promotion` (a mode change records a STRATEGY_MATERIAL boundary by the fingerprint rule; no replay).
