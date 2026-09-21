# Task 81 §5 — IEX readiness-churn diagnosis (2026-08-28 Task 80 session)

Session: `piv_2026-08-28_092814_1f17993c`, feed `IEX_PAPER_PIV`,
`stale_seconds = 120`. Evidence used (all preserved, local, read-only):
`results/task80_live_20260828/runtime/{piv_events.jsonl, freshness_report.json,
quant_funnel_report.json, session_readiness_state.json}` and the
`results/task80_cleanup/...` sanitized report.

## Headline

The readiness churn (532 `DATA_NOT_READY`, 515 `STALE_DATA`, 514
`DATA_RECOVERED`) is a **faithful reflection of genuine Alpaca-IEX 1-minute
bar sparsity for mid-liquidity NASDAQ-100 constituents**, not a runtime
bookkeeping or freshness defect. The event accounting reconciles exactly and
matches the independently-written `freshness_report.json`. No threshold was
relaxed, no bar fabricated, and the earlier "IEX sparsity" explanation was
**re-derived from the 2026-08-28 evidence**, not assumed.

## Separation of the six dimensions the task asks to distinguish

| Dimension | Where | 2026-08-28 finding |
|---|---|---|
| Feed **coverage** (per-symbol fresh-bar count) | `freshness_report.json` `coverage_ratio` / `fresh_bar_count` | Bimodal: mega-caps 0.99–1.00 (`fresh_bar_count` 357–360); mid-liquidity 0.58–0.75 (REGN 92, VRTX 119, COST 139, HON 143). Median 0.913. |
| **Stale responses** | `_check_stale` → `STALE_DATA` | 515 events == Σ `stale_episode_count` across the 35 symbols (exact). |
| **Polling / bar timestamps** | `process_tick` `_last_bar_ts` (source `t`) vs `_last_seen_wall` (receipt wall-clock) | Source-`t` used only for the `bar.timestamp <= last` de-dup; receipt wall-clock drives staleness. See "Evidence limitation" below. |
| **Readiness transitions** | `_finalize_readiness` (opening 09:30–10:00 ET completeness, once/session) vs `_check_stale` (current freshness, once/episode) | Two orthogonal `DATA_NOT_READY` sources. 532 = **515** (`INSUFFICIENT_RECENT_IEX_PRINTS` / `EXCLUDED_FROM_DECISION_PATH`, one per stale episode) + **17** (`MISSING_REQUIRED_OPENING_MINUTES` / `missing_minutes=N`, one per non-READY symbol at 10:00 ET; 18 READY + 17 NOT_READY = 35). Exact. |
| **Provider failures** | `record_provider_fetch_result` (HTTP-level only) | Provider ended `HEALTHY`. The 3 `BROKER_ERROR` rows are 1 Alpaca DNS failure during periodic reconciliation (failed closed), 1 concurrent `MARKET_DATA_FETCH_FAILED`, 1 `STALE_DATA_UNRESOLVED_AT_SESSION_END` for COST. None indicate a feed-wide outage — consistent with `freshness.py`'s design note that "many symbols stale at once" is **not** inferred as provider-down. |
| **Notification de-duplication** | `_stale_flagged` (runner) + `observe_stale` / `observe_fresh` `newly_stale` / `recovered` flags (freshness) | One `STALE_DATA` + one `DATA_NOT_READY` per episode entry; one `DATA_RECOVERED` per genuine recovery. `DATA_RECOVERED` (514) = `STALE_DATA` (515) − 1 (COST never recovered → `DATA_GAP` at session end). Exact. |

## Representative repeated episode (VRTX / HON / COST, first ~30 min)

`RECOVERED → +~121–127 s → STALE → +~60–180 s → RECOVERED`, repeating.
The `RECOVERED→STALE` gap sitting at ~`stale_seconds` is the *definition*
of the condition, not a flap bug: a symbol that prints roughly every
~150–170 s on IEX (COST `fresh_bar_count` 139 over ~6 h ≈ one bar / 2.6 min)
necessarily crosses the 120 s line once per inter-bar interval. `_stale_flagged`
correctly emits exactly one event pair per crossing.

The apparent "doubled `DATA_NOT_READY` with no `RECOVERED` between" (e.g.
COST 13:58:53 then 14:00:57) is the stale-episode event followed by the
**once-only 10:00 ET opening-minutes** event — two dimensions, both correct.

## Confirmed: no bookkeeping defect

- Event counts reconcile to the last unit (see table).
- `freshness_report.json` `stale_episode_count` (Σ = 515) is written by an
  independent code path (`FreshnessTracker`) and matches the `STALE_DATA`
  event count from the runner's `_stale_flagged` path.
- Infra exclusions are already kept strictly separate from strategy
  rejections: a `STALE`/`DATA_NOT_READY` symbol is removed from
  `decision_eligible` (`session_runner.py:386-388`) so its bar never reaches
  `DecisionEngine.on_bars`, and therefore can never become one of the 5,721
  `LOW_VOLATILITY` / `LOW_CONFLUENCE` / `LOW_RISK_REWARD` strategy rejections
  in `quant_funnel_report.json`.

Regression tests locking these invariants:
`tests/test_task81_iex_readiness_bookkeeping.py` (4 cases) — a re-delivered
same/older-timestamp bar neither resets staleness nor re-emits recovery;
distinct gaps produce distinct episodes; the finalization vs freshness
`DATA_NOT_READY` dimensions are independent and each de-duped; a stale
symbol's bar is never forwarded to the strategy. Existing
`tests/test_task71s_r1_live_iex_semantics.py` already locks "sparse
intervals do not generate notification storms" and "recovery events occur
exactly once per transition".

## Evidence limitation / unresolved question

Freshness is measured from `_last_seen_wall` (wall-clock at the tick that
first *received* a bar new-to-us), not from the bar's own market timestamp.
A bar whose source `t` is newer than the last one we saw but still old in
market terms (an IEX delayed / back-filled print) would reset the staleness
clock. **The preserved evidence contains no per-bar source timestamps and no
raw `bars/latest` response log** (the cleanup report notes the dedicated PIV
runner stdout/stderr logs were not found), so whether receipt-time ever
diverged materially from source-bar market time on 2026-08-28 **cannot be
confirmed or excluded from local evidence**.

Required evidence to close it: a session run — or a captured raw
`bars/latest` log — recording each bar's source `t` alongside its receipt
wall-time for the mid-liquidity subset (REGN, VRTX, COST, HON, GILD, ISRG),
optionally cross-checked against Alpaca's historical IEX 1-minute archive via
the existing `talonx_piv/gap_forensics.py` (as was done for the 2026-08-26
session). External / historical data acquisition requires separate approval.

## Isolation-engineering impact

**Does not block** the Original/PIV isolation task: reconciliation, recovery,
session-binding and reporting safety are independent of feed cadence. It
**should be resolved before** any market-session pilot whose thesis depends
on the mid-liquidity names being decision-eligible, since ~40–50 stale
episodes/symbol/day on those names materially reduces their in-session
decision coverage.
