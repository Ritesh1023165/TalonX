# Tomorrow: V2 Session 04 plus the pre-market research canary (Thursday 2026-09-24)

| Lane | What runs |
|---|---|
| **V2** | Continues **frozen** on its 39 symbols, with the same commands as every prospective day. It is untouched by the research lane. |
| **PREMARKET RESEARCH** | A **separate process**, the broad universe of about 5,655 names, **research alerts only**. No paper trading, and never a V2 TRADE_EVENT. |

**Do not start anything before 00:00Z** (session directories are keyed by UTC date). **Nothing here starts automatically.**

**Timeline** (XNYS calendar; 2026-09-24 is EDT):

| Time | Event |
|---|---|
| 04:00 ET = 08:00Z = 09:00 UK | Pre-market opens |
| 04:15 ET = 08:15Z = 09:15 UK | First research scan (the 15-min SIP delay means nothing is visible earlier) |
| 09:30 ET = 13:30Z = 14:30 UK | Regular open; last pre-market scan before this, then post-open tracking |
| 16:00 ET = 20:00Z = 21:00 UK | Regular close; outcome tracking finishes about 20:17Z |

---

## 0. Which code runs where

This work is on branch `feature/premarket-broad-opportunity-engine` (PR, **not merged**).

- **If the PR is merged before the morning:**
  - V2 runs from `main`. Preflight accepts the post-freeze Session-03 hardening files and the `talonx_premarket/` package through closed allowlists, and `repo_head_matches_release` stays READY.
  - The research engine also runs from the `main` checkout (§2A).
- **If it is not merged:**
  - V2 runs from `main` exactly as today. **Do not check out the feature branch in `C:\workspace\TalonX`.**
  - The research engine runs from a separate worktree (§2B) and reads the main checkout's `.env` in place, never copying it.

## 1. V2 (unchanged procedure, about 08:00 UK)

```powershell
cd C:\workspace\TalonX
git status --short          # only untracked runtime files; HEAD = main
$env:TALONX_V2_CAMPAIGN_ID='V2-PAPER-RC1'
$env:TALONX_V2_DB_PATH='v2_release_rc1.db'
$env:TALONX_V2_STATUS_PATH='v2_release_rc1_status.json'
$env:TALONX_V2_STARTING_CASH_USD='100000'
$env:TALONX_V2_ALLOCATION_USD='10000'
$env:TALONX_V2_EXECUTION_MODE='PAPER'
$env:TALONX_NOTIFY_DB_PATH='v2_release_rc1_notifications.db'
.venv\Scripts\python.exe -m talonx_v2.release_gate --verify-campaign
.venv\Scripts\python.exe -m talonx_v2.release_gate
.venv\Scripts\python.exe -m talonx_ops.prospective start --release --expected-sha a56ec8c --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45 --execution-scope resolved-active-watchlist --deliver --transport telegram
```

Expect `READY`, strategy `e2acf6454789217e`, provider `ac5e51aa3599d6c9`, and `lab_off` PASS.

**With the PR merged, `start` prints:**
```
INTELLIGENCE DELIVERY: configured=OFF runtime_requested_by_start=ON effective=ON
```
Intelligence `[INFO]` cards will be sent (the existing intended behaviour, now visible). To keep them off for the day, set `$env:TALONX_INTEL_DELIVER_CARDS='0'` before `start`; the line then reads `effective=OFF`.

Close as usual after 20:00Z: `.venv\Scripts\python.exe -m talonx_ops.prospective close`. With the PR merged, `eod.json` will contain `shutdown.shutdown_notice` (the bounded SHUTDOWN drain).

## 2. Pre-market research canary (start between 07:30Z and 08:10Z, 08:30–09:10 UK)

Use a **new PowerShell window**. Do **not** reuse the V2 window, and do **not** set `TALONX_NOTIFY_RESEARCH_ENABLED` in the V2 window.

### 2A. From main (PR merged)

```powershell
cd C:\workspace\TalonX
.venv\Scripts\python.exe -m talonx_premarket universe            # rebuild today's universe (~5.6k eligible)
.venv\Scripts\python.exe -m talonx_premarket run --v2-scope-log results\prospective_2026-09-24\logs\v2_companion.log
```

### 2B. From a separate worktree (PR not merged)

```powershell
cd C:\workspace
git -C TalonX fetch origin
git -C TalonX worktree add ..\TalonX-premarket origin/feature/premarket-broad-opportunity-engine
cd C:\workspace\TalonX-premarket
C:\workspace\TalonX\.venv\Scripts\python.exe -m talonx_premarket --env-file C:\workspace\TalonX\.env universe
C:\workspace\TalonX\.venv\Scripts\python.exe -m talonx_premarket --env-file C:\workspace\TalonX\.env run --v2-scope-log C:\workspace\TalonX\results\prospective_2026-09-24\logs\v2_companion.log
```

**Check the first status block the process prints:**
- `"config_fingerprint": "62ba413daf85e674"` (frozen PREMARKET_RESEARCH_V1);
- `"universe_eligible"` about 5,600, and `"v2_scope_size": 39` (if 0, the scope-log path is wrong: labels only, no other effect);
- `"delivery_mode": {"deliver_flag": false, ...}`. **This is the default canary: every alert is recorded, nothing is sent.**

The process sleeps until 08:15Z, scans every 15 min in EARLY and every 5 min in CORE/NEAR_OPEN, then tracks outcomes until about 20:17Z and exits.

**Monitor:** `.venv\Scripts\python.exe -m talonx_premarket status` shows the heartbeat, last scan funnel (UNIVERSE / DATA_READY / HARD_REJECTED / SCORED / WATCH / BULLISH_SETUP / BEARISH_SETUP), alerts, `duration_s` and request counts.

**Stop:** create `results\premarket_research\2026-09-24\stop.flag` (in the directory the engine runs from), or press Ctrl+C. This is safe at any time: the lane holds no positions.
- The flag is checked before every scan and during outcome tracking. It is **never deleted automatically**.
- While a same-session `stop.flag` exists, `run` **refuses to start** (exit code 3). To restart deliberately, rename it (for example to `stop.flag.0915`).
- A flag from another session date is in a different directory and has no effect.

**Restart** (for example after a crash or reboot): run the same `run` command again. The session DB is reused: candidates, the cap, invalidated identities and update timing are restored, and no duplicate NEW alert is produced. The data watermark is rebuilt from 04:00 ET, and each start is recorded in the `runs` table.

**Status fields** (`status`; add `--date 2026-09-24` from another day):
- **Process:** SESSION, PID, STATE, HEARTBEAT_AGE_S, CONFIG_FP, UNIVERSE / ELIGIBLE, CURRENT_PHASE, LAST_SCAN / NEXT_SCAN / SCAN_DURATION_S, DATA_AS_OF, EFFECTIVE_SIP_DELAY.
- **Provider:** PROVIDER_REQUESTS / ERRORS / FAILED_BATCHES / **PROVIDER_COMPLETE** / DATA_GAPS / LAST_SUCCESSFUL_PROVIDER_FETCH, CATALYST_UNKNOWN.
- **Funnel:** DATA_READY … BEARISH_SETUP, PROVIDER_INCOMPLETE.
- **Alerts and delivery:** NEW_ALERTS_USED (x/25), SUPPRESSED_BY_CAP, DELIVERY_MODE, DELIVERY_STATES.
- **Outcomes and runs:** OUTCOMES, RUNS_THIS_SESSION.

**Healthy looks like:** HEARTBEAT_AGE_S < 60 while waiting for a scan (< 660 during post-open tracking, which updates every 10 min), PROVIDER_COMPLETE True, DATA_GAPS 0, and a scan duration well under 300 s. If PROVIDER_COMPLETE is False, affected symbols are **held** (no alerts, no invalidations) and re-fetched automatically on the next scan; check PROVIDER_ERRORS.

**Evidence:** `python -m talonx_premarket report --date 2026-09-24` writes `evidence/canary_evidence.json` and `evidence/CANARY_EVIDENCE.md` inside the session directory. They contain the scan timeline with provider completeness, the funnel, every alert with its routing and delivery state, suppressed candidates, outcomes, errors and runs.

## 3. Optional: live Telegram research delivery (explicit, operator-only)

Research delivery is **OFF**, and currently **cannot** be enabled by accident. The configured `TALONX_NOTIFY_RESEARCH_CHAT_ID` equals the primary chat, so `resolve_destination_config(RESEARCH)` refuses it.

To enable it for the canary:
1. Use a separate Telegram chat for TalonX Lab. It must not be the Signal/primary chat.
2. Put that chat ID into `TALONX_NOTIFY_RESEARCH_CHAT_ID` in `.env`, and keep `TALONX_NOTIFY_RESEARCH_ENABLED=0` there.
3. Start the engine with the flag scoped to this one process:
   ```powershell
   $env:TALONX_NOTIFY_RESEARCH_ENABLED = "1"
   .venv\Scripts\python.exe -m talonx_premarket run --deliver --v2-scope-log results\prospective_2026-09-24\logs\v2_companion.log
   ```
4. The status block must show `"research_destination_enabled": true`. If it's false, it prints the reason, and alerts are enqueued to the research outbox only, never sent.

Messages start with `[PREMARKET RESEARCH]` and end with `Research alert only. Not a V2 trade event. Paper execution not started.` There are at most 25 new candidates per session (highest score first), and each undelivered alert expires after 30 min.

## 4. Readiness (tonight)

| Check | Result |
|---|---|
| Broad universe loads | PASS: 14,373 total, 5,655 eligible |
| Provider supports pre-market data | PASS: SIP 1-min from 04:00 ET, verified; 15-min delay |
| Scan finishes inside cadence | PASS: replay scans 7–14 s with a warm SEC cache; live incremental path ~25 s; cold first scan ~51–136 s; cadence is ≥ 300 s |
| Provider partial failure | PASS after the PR19 hardening: per-symbol watermarks, batch retry, hold on unknown data (PR19_HARDENING_REVIEW.md) |
| Rate limits respected | PASS: client limiter at 180/min (provider 200/min); SEC ≤ ~5 req/s |
| Candidate funnel nonzero on replay | PASS: see SHADOW_REPLAY_2026-09-23.md |
| Research routing isolated | PASS (tests); live delivery off, and not enableable until a distinct chat is configured |
| Dedup | PASS (tests plus replay) |
| Post-open tracker | PASS (tests plus replay outcomes) |
| V2 unchanged | PASS: strategy `e2acf6454789217e`, provider `ac5e51aa3599d6c9`, 39-name scope, V2-PAPER-RC1 untouched |

## 5. After the session

Keep `results\premarket_research\2026-09-24\` (`premarket_research.db`, `status.json`) as canary evidence. Compare alerts against the V2/Intelligence session output using the same classification as SHADOW_REPLAY_2026-09-23.md. Do **not** change weights or thresholds based on the day's outcomes; any change is a new config version with a new fingerprint.
