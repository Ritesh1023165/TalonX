# Review-alert thinning + V2 passive (owner decisions 2026-11-20)

**Status:** implemented and tested on branch `feature/thin-review-alerts-v2-passive` (child of
`feature/continuous-opportunity-engine`). **Not yet deployed** to the live stack, **not pushed**.

Deployment needs, after the owner reviews this:
- a control-file change;
- a promotion restart;
- one owner-authorised `--force` ops/V2 restart.

## Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Review alerts to the Signal bot | **Thin out.** Option 1 per-session cap, N = 10. Awareness only; never worded as trade prompts |
| 2 | V2 companion | **Passive record.** "Silence V2 only": no V2 trade alert and no V2-produced ops notification; the companion still drains the shared OPERATIONS outbox for other components |
| 3 | V2 restart | One `--force` restart, after tests pass and the owner has seen the diff |

## Step 1 findings (investigation, before any change)

**Review alerts.**
- Path: `promotion.py` eligibility → score-ordered queue → `_release` (3 per 5 min, 30-min expiry; inside policy
  fingerprint `4926c12e5eace04e`) → `RESEARCH_OPPORTUNITY` outbox → `_drain_signal` → delivery trace → Signal bot.
- Volume: 60.3 per session (median 59, range 15–129) over 24 sessions (1,448 alerts).
- No same-symbol repeats within a session. About 60% arrive in the first two hours.

**V2 reached Telegram three ways:**
1. Its own BUY/SELL alerts to the **Signal bot**: `--deliver --transport telegram`.
   - Two were **sent after the 2026-11-01 closeout**: ABCL "PLANNED BUY … ACTIONABLE" (2026-11-14 01:17Z) and
     "BUY FILLED" (2026-11-17 01:16Z).
   - An open paper ABCL position would have sent a SELL at its planned 2026-12-01 exit.
2. V2-produced ops alerts: 144 `DEGRADED_HEALTH` since 2026-10-04, about **24 per day since 2026-11-14**
   (`SOURCE_OR_PRICING_DEGRADED`). The underlying data issue is not investigated here.
3. The shared OPERATIONS drain (other components' messages), which is kept.

**Not V2 paths:** the V2 forward-study loop ended on 2026-10-31 as registered (not rerun). Original's stack
(`run_talonx.py`, quant, brain, dispatch, paper) does not import `talonx_v2` or read the active profile.

**Wording that could read as a trade prompt:** review alert "Scope … No entry, exit or holding rule", "not a buy
instruction", the "RESEARCH OPPORTUNITY" fallback header, and the V2 "BUY / ACTIONABLE / Planned exit" cards. The Lab
bot ("NEW SETUP / BULLISH / BEARISH", about 200 per day) is out of scope and flagged for a separate decision.

## Changes

| File | Change |
|---|---|
| `talonx_opportunity/promotion.py` | `signal_thinning()` reads the control file's `thinning` block (fail-safe default 10). In `_release`, past the cap a promotion is recorded `PROMOTED_SHADOW / THINNED_SESSION_CAP`, never enqueued. Cap = `PROMOTED_SIGNAL` count per `window_id` (durable across restarts). Template **`RESEARCH_REVIEW_AWARENESS_V4`** wording. Status and config fingerprints report `signal_thinning`. Policy fingerprint unchanged |
| `talonx_v2/passive.py` (new) | `V2_PASSIVE = True`; `suppress_outbox()` retires unsent V2 alerts as `EXPIRED / SUPPRESSED_V2_PASSIVE` (terminal) |
| `talonx_v2/service.py` | Passive: no `deliver_outbox`, no `scan_v2_operational_events`, no V2 `DEGRADED_HEALTH`; the shared OPERATIONS drain is kept; status `delivery_enabled=False`, `v2_passive=True`. Strategy fingerprint `e2acf6454789217e` unchanged (service.py is not a fingerprinted file) |
| `talonx_ops/opportunity_read.py` | Cockpit: configured vs loaded cap, `thinned_session_cap` count; V2 lane label says PASSIVE (lane key kept) |
| `docs/research/NOTIFICATION_POLICY.md` | New §0 (dated owner decisions); §5 marked superseded |

**Untouched:**
- PDM store `pdm.db` (sha256 prefix `294461bb1a92d83f`, before and after).
- The PDM protocol and locked files: `verify_integrity` OK, fingerprint `c812a3e65e4018a5`.
- The decision-rules pre-registration and every research result.

## Tests

**New:**

| File | Tests | Covers |
|---|---|---|
| `test_review_alert_thinning.py` | 11 | Cap, order, restart, per-window, decisions identical, fail-safe, cockpit |
| `test_review_alert_awareness_wording.py` | 9 | No trade-prompt words in any render; the label is visible first |
| `test_v2_passive.py` | 9 | Cannot send; terminal suppression; SENT untouched; no V2 ops; shared drain kept; status; fingerprint; negative control |

**Updated (intended behaviour changes only):**
- V3 → V4 wording assertions in `test_review_alert_compact_template.py` and `test_review_alert_expandable_template.py`.
- `test_ri2_notification_routing.py::test_14` proves the shared drain with another component's row.
- 8 V2 delivery tests now request the `v2_delivery_dormant_path` fixture (`tests/conftest.py`), so they exercise the
  retained-but-disabled delivery machinery with passive switched off for that test only.

**Full suite, Python 3.12.10:**

| | Passed | Failed | Skipped | Deselected |
|---|---|---|---|---|
| Before (`9c59fe6`) | 6,171 | 35 | 16 | 24 |
| After | 6,199 | 36 | 16 | 24 |

- The 35 failures are the same set in both runs (pre-existing).
- The extra one is `test_task117_single_writer_lock.py::test_two_real_concurrent_starts_yield_exactly_one_owner`, a
  real two-process timing test. It passes 5 of 5 in isolation, and no lock code was changed.
- **Deselected identically in both runs (24):** `test_backtest_cost_sensitivity.py` and 11 multi-trade backtest tests
  (`test_backtest_sample_data.py`, `test_package5_intraday_causality.py`). Their shared backtest fixture does not
  finish in reasonable time; this was known before this change. `pytest-timeout` is not installed.
- **Worktree caveat:** tests that need gitignored `results/` data fail in a worktree for both runs alike.
  `test_14` was additionally verified with the Form 4 parquet present.

## Replay (read-only, no live run)

`replay_session.py` → `REPLAY_2026-11-18.md`. On a typical session, **59 → 10 alerts**; the 10 kept were released
14:50–15:16Z. The same file shows the V3 → V4 wording on the session's first real alert.

## Deployment (pending owner OK)

1. Fast-forward `feature/continuous-opportunity-engine` to this commit (live checkout).
2. Add the `thinning` block to `results/opportunity/control/promotion_signal_delivery.json` (backup first). Record a
   promotion change declaration, then `python -m talonx_opportunity restart promotion`.
   - The deployment record will classify it per existing rules: a promotion source change not declared `UI_ONLY` is
     recorded conservatively.
3. One owner-authorised `prospective start --force` restart of the ops/V2 stack (same args/env as 2026-10-16), loading
   passive V2. The release gate is NO_GO since f78fb34 for `.gitattributes`, plus `talonx_v2/service.py`.
4. **Verify:**
   - `v2_passive=true` in the V2 status;
   - no V2 rows sent;
   - the first session's review alerts capped at 10 and in V4 wording;
   - the cockpit shows the cap.
