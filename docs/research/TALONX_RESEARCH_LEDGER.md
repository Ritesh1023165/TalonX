# TalonX Research Ledger

Persistent record of research-track validation tasks run against the TalonX trading-strategy research
project on branch `research/talonx-strategy-validation`. Each entry is append-only — prior entries are
never edited or removed. If a later task revises an earlier conclusion, that is recorded as a new dated
note under the *original* entry (see format below), not by rewriting history.

Entries for Tasks 1–14 (below) were backfilled by Task 23 (2026-08-20) from existing on-disk artifacts and
git history — see each entry's own **Evidence** section for exact sourcing. Where a value could not be
independently recovered from an artifact, it is marked `NOT_RECOVERED_FROM_ARTIFACT` rather than invented.
Task numbering follows the actual names found in artifacts/commits; where an artifact used a name that
doesn't match a clean sequential number (e.g. "Task 6" sitting chronologically between Task 4 and Task 7B),
that name is preserved as found rather than renumbered. Two tasks (9 and 12) have no primary artifact
recoverable anywhere in this repository or its git history — their entries are reconstructed solely from
verbatim-quoted retrospective citations in later tasks' own summaries, flagged accordingly. Live/paper-
trading and observability work (2026-08-18) is grouped in its own section between Task 12 and Task 13, since
its internal numbering is ambiguous in the source material; it is explicitly *operational* validation, not
*profitability* validation, and should not be read as evidence for or against any research-track conclusion.

Entries for Task 15 onward were written contemporaneously as each task ran; their full detail also lives in
their own `results/task15_*` through `results/task22_*` artifact directories.

---

## Task 1.1 — Downloader Partial-Failure Exit-Code Semantics

### Objective
Ensure `scripts/download_historical_1m.py` returns a correct process exit code when downloading multiple
symbols with mixed outcomes, so calling automation can detect a genuine failure.

### Hypothesis / Expected Behaviour
All-success → exit 0. Any-failure (including partial-batch failure) → exit non-zero. A pre-fix version used
`len(failed_symbols) == len(symbols)` (only exiting non-zero if *every* symbol failed), which would
incorrectly return 0 when some symbols failed and others succeeded.

### Inputs
N/A (unit-level, no market data/dataset dependency).

### Work Performed
Rewrote the exit-code condition in `main()` to flag failure per-symbol rather than requiring total failure.

### Validation
`tests/test_download_historical_1m.py`:
- `test_all_success_exits_zero` (line 346) — all symbols succeed → `exit_code == 0`.
- `test_partial_failure_still_processes_remaining_symbols_but_exits_nonzero` (line 361) — one symbol empty,
  others succeed → `exit_code != 0`; test comment explicitly notes the OLD condition "would have exited 0
  here."
- `test_all_failure_exits_nonzero` (line 391) — all symbols fail → `exit_code != 0`.

### Results
Confirmed by test: exit code is 1 iff **any** symbol is EMPTY or FAILED (see Task 2.2 below for the full
status taxonomy this later grew into); PARTIAL never alone forces a non-zero exit; all-success is 0.

### Defects / Anomalies
The pre-fix `all-failed-only` condition was itself the defect being fixed.

### Changes Made
`scripts/download_historical_1m.py`: `main()`'s exit-code logic — see final form at line 480:
`hard_failures = [r for r in results if r.status in ("EMPTY", "FAILED")]; return 1 if hard_failures else 0`.

### Conclusion
Exit-code contract corrected and pinned by test.

### Limitations
None beyond ordinary unit-test coverage limits.

### Decision
Fixed and adopted.

### Next Step
Task 2.2 later generalized "failure" into an explicit FULL/PARTIAL/EMPTY/FAILED status taxonomy, re-
affirming this same contract under the richer classification.

### Evidence
`scripts/download_historical_1m.py` (exit-code logic, line 480); `tests/test_download_historical_1m.py`
(`test_all_success_exits_zero`, `test_partial_failure_still_processes_remaining_symbols_but_exits_nonzero`,
`test_all_failure_exits_nonzero`, and the later `test_task_1_1_exit_code_contract_still_holds_with_the_new_
status_field` at line 616, which explicitly re-confirms this task's original contract survived the Task 2.2
refactor).

---

## Task 2 — Real yfinance 1-Minute Smoke Test

### Objective
Confirm the downloader can pull genuine 1-minute OHLCV data end-to-end from a real provider (yfinance) and
that the resulting CSVs are usable by `talonx_backtest`.

### Hypothesis / Expected Behaviour
Provider history for 1-minute granularity would likely be narrower than any nominally-requested range (a
known yfinance limitation, ~30 trailing days for 1-minute data).

### Inputs
Symbols: AAPL, AMD, META, NVDA, TSLA (5 of the eventual 10-symbol universe). Requested/actual period:
2026-08-10 08:00 UTC → 2026-08-14 23:59 UTC (actual matched requested here). `git_commit=
755cae7c3039e4bf074fb6f00a3ab5b1bea4858b`, `strategy_version=a660d03ff462`, `config_hash=19654e22ffd5`,
`run_timestamp=2026-08-16T20:51:09Z`.

### Work Performed
Downloaded and backtested (cost-free, zero trades expected given the tiny window) the 5-symbol set.

### Validation
`backtest_data_quality.json` — no critical corruption, `unexpected_intra_session_gap_bars: 0` for all 5
symbols in this specific run (this run predates the weekend-gap bug being *discovered*, per the
`8f7e43e` commit's own timeline — see Task 2.1).

### Results
23,918 bars processed, 41 signals generated, 0 published, 0 trades (window too short for a full lifecycle).
Rejections: `LOW_VOLATILITY` 22,116, `LOW_CONFLUENCE` 28, `OPENING_BLACKOUT` 13. Per-symbol row/gap counts:
AAPL 4,795 rows (1,925 missing, all expected); AMD 4,782 (1,938 missing, all expected); META 4,741 (1,979
missing, all expected); NVDA 4,800 (1,920 missing, all expected); TSLA 4,800 (1,920 missing, all expected).

The task prompt's recalled example — "AAPL ~5,754 bars, 2026-08-07 08:00 UTC through 2026-08-14 23:59 UTC" —
does **not** match this artifact's window (2026-08-10→08-14, AAPL 4,795 rows) but **exactly matches** Task 3
(`results/task3_aapl_baseline/`, single-symbol AAPL run, period 2026-08-07 08:00 UTC → 2026-08-14 23:59
UTC, `bars_processed: 5754`) — the recalled figures belong to Task 3, not this 5-symbol Task 2 smoke test.
Recorded here to correct the mapping rather than force a false match.

### Defects / Anomalies
None specific to this run (the weekend-gap bug it narrowly missed triggering is documented under Task 2.1).

### Changes Made
None — validation run only.

### Conclusion
Confirmed the yfinance provider path produces usable 1-minute data end-to-end. Provider history was in fact
narrower than a nominal year-long request would be (consistent with yfinance's documented ~30-day 1-minute
limit — this 5-day window was well within that limit and returned FULL).

### Limitations
5-day window insufficient to exercise the full trade lifecycle (0 trades). Does not test yfinance's
documented 1-minute history ceiling directly (window chosen was already short).

### Decision
Provider path validated; proceed to fix data-quality gaps found during subsequent smoke testing (Task 2.1).

### Next Step
Task 2.1 (weekend-gap misclassification, found on a similar but distinct smoke run one day later).

### Evidence
`reports/yfinance_recent_run/` — `backtest_summary.json`/`.txt`, `backtest_data_quality.json`,
`backtest_equity_curve.csv`, `backtest_rejected_signals.csv`, `backtest_results.html`, `backtest_trades.csv`/
`.json`. Not present on disk currently (deleted by commit `d747cd9`, "Empty reports/ and results/ before the
infrastructure audit"); recovered via `git show 63a4630:reports/yfinance_recent_run/<file>` (the commit that
added it, before the later wipe). `reports/` is `.gitignore`d going forward, so this artifact will not
reappear via a normal `git log` file listing.

---

## Task 2.1 — Weekend-Gap Misclassification

### Objective
Fix a data-quality false-positive: the missing-bar gap classifier flagged weekend closures as "unexpected"
intra-session gaps.

### Hypothesis / Expected Behaviour
`talonx_quant.session.get_session()` classifies purely by time-of-day with no notion of calendar date, so a
weekend's 09:30–16:00 ET window is indistinguishable from a real trading day's to that function alone — the
gap classifier needed an explicit weekend check.

### Inputs
N/A (deterministic logic fix, confirmed against real downloaded data).

### Work Performed
Root cause: the gap-classification loop (introduced by commit `6803e61`) checked only
`get_session(cursor) == "regular"` to decide whether a missing bar was "unexpected." Fix (commit `8f7e43e`,
"feat(backtest): add reproducible historical validation pipeline", 2026-08-17 22:21:58 +0100): added
`_is_weekend(timestamp)` (`talonx_backtest/data.py`, uses `ZoneInfo("America/New_York")`, returns True for
Sat/Sun by ET calendar date) and changed the loop condition to
`get_session(cursor) == "regular" and not _is_weekend(cursor)`.

**Explicitly documented, deliberate scope limit** (quoted from the code comment,
`talonx_backtest/data.py:48-54`): *"Deliberately does NOT cover exchange holidays (Thanksgiving, Christmas,
etc.) -- this repository has no trading-calendar/holiday source of truth to consult (no calendar library is
installed or referenced anywhere in the codebase; checked before writing this). A gap spanning a holiday
will still be misclassified as an unexpected intra-session gap until a real calendar is added."* This is
the explicit decision to defer holiday-calendar work — recorded in the fix's own code comment, not in a
separate planning document.

### Validation
`tests/test_backtest_data_gaps.py` (8 tests total): weekend-specific —
`test_weekend_gap_between_friday_and_monday_is_fully_expected` (line 88),
`test_a_genuine_intraday_gap_is_still_detected` (line 102),
`test_weekend_gap_plus_a_genuine_monday_gap_are_both_classified_correctly` (line 115),
`test_weekend_gap_matches_the_exact_780_bar_smoke_test_finding` (line 131) — pins the exact real-data
finding: *"a single weekend inside a downloaded range used to add 390 (Sat) + 390 (Sun) = 780 false-positive
unexpected gap bars"*, asserts `report.unexpected_intra_session_gap_bars == 0  # was 780 before this fix`.

### Results
Live confirmation of the pre-fix bug: `results/smoke_test_cli_check/backtest_data_quality.json`
(`run_timestamp=2026-08-17T04:40:02Z`, ~18 hours before the `8f7e43e` fix) shows **exactly 780**
`unexpected_intra_session_gap_bars` for all 5 symbols tested (AAPL, AMZN, META, MSFT, NVDA) — matching the
test's pinned number exactly, confirming the bug was found and reproduced from real downloaded data, not
invented.

### Defects / Anomalies
The 780-bar-per-weekend false-positive was the defect. It did not affect any strategy signal/gate decision
(purely a data-quality *reporting* metric, `unexpected_intra_session_gap_bars`) — no trade/signal output was
ever wrong because of this bug.

### Changes Made
`talonx_backtest/data.py`: added `_is_weekend()`, updated the gap-classification loop condition (38
insertions, 11 deletions in commit `8f7e43e`).

### Conclusion
Fixed; weekend closures no longer inflate the unexpected-gap count. Exchange holidays remain a known,
explicitly-documented residual false-positive source.

### Limitations
Holiday gaps are still misclassified as unexpected — deliberately deferred, not fixed, due to no
trading-calendar library being present in the repository.

### Decision
Fixed and adopted; holiday-calendar work explicitly deferred.

### Next Step
Task 2.2 (downloader status semantics) landed in the same commit window; Task 3/4 baselines proceeded on
the corrected gap classifier.

### Evidence
`talonx_backtest/data.py` (`_is_weekend`, gap-classification loop); commit `8f7e43e` diff;
`tests/test_backtest_data_gaps.py` (8/8 tests, weekend-specific tests quoted above);
`results/smoke_test_cli_check/backtest_data_quality.json` (780-bar pre-fix evidence,
`run_timestamp=2026-08-17T04:40:02Z`).

**Chronology note** (verified directly, not just from the commit log): `results/smoke_test_cli_check/` and
`results/task3_aapl_baseline/` both record the identical `git_commit=d747cd9c18fd3320740071e7a947cb754e8d9ae4`
in their reproducibility metadata, over the *same* AAPL window (2026-08-07→2026-08-14) — yet
`smoke_test_cli_check` (run 04:40:02 UTC) shows `unexpected_intra_session_gap_bars: 780` while
`task3_aapl_baseline` (run 05:32:01 UTC, ~52 minutes later) shows `0` for the identical symbol/window
(directly re-verified from both `backtest_data_quality.json` files, not merely inferred). Since the fix's
formal commit (`8f7e43e`) was not made until `22:21:58 UTC` that same day, this proves the weekend-gap fix
was already live in the (uncommitted, dirty) working tree by `05:32:01 UTC` — Task 3's run genuinely
exercised the fixed code, ~17 hours before it was formally committed. This is why this entry is presented
before Task 3/4 despite the formal commit landing later: the code's behavior, not the commit timestamp, is
what the artifacts prove.

---

## Task 2.2 — Downloader Status Semantics (FULL/PARTIAL/EMPTY/FAILED)

### Objective
Replace the downloader's binary success/fail outcome with four explicit, distinct statuses so a caller can
tell "got less data than asked for but it's real" (PARTIAL) apart from "got nothing" (EMPTY) or "the request
itself errored" (FAILED).

### Hypothesis / Expected Behaviour
Collapsing "provider call failed" and "provider returned zero bars" into one bucket, and never comparing
what was returned against what was requested, hid real information from both console output and
`download_summary.json`.

### Inputs
N/A (logic/schema change).

### Work Performed
Added `_STATUSES = ("FULL", "PARTIAL", "EMPTY", "FAILED")` and `DownloadResult` dataclass carrying
`status`/`requested_start`/`requested_end`/`actual_start`/`actual_end`/`bars`/`error`/`df`.
`_classify_status()` compares the actual America/New_York calendar-date range of returned bars against the
requested range: FULL if it covers the full requested range, else PARTIAL. A 2026-08-17 timezone/date-
boundary follow-up fix (same commit) changed this comparison from raw UTC dates to America/New_York dates —
extended-hours 1-minute data trading as late as ~19:59 ET can cross UTC midnight during EST, which
previously made a request with an entirely-missing next day misclassify as FULL.

### Validation
`tests/test_download_historical_1m.py`, "TEST 5" `test_mixed_full_partial_failed_across_symbols` (line
525): AAPL FULL, MSFT PARTIAL, NVDA FAILED in one `main()` call → `exit_code != 0` (NVDA's failure alone
forces it); console shows all three status labels; AAPL/MSFT CSVs written, NVDA's is not.
`test_partial_alone_does_not_force_a_nonzero_exit` (line 602): single PARTIAL symbol → `exit_code == 0`.
Per-status unit tests: `test_download_symbol_full_status` (473), `test_download_symbol_partial_status`
(484), `test_download_symbol_empty_status` (494), `test_download_symbol_failed_status` (505),
`test_empty_and_failed_are_not_conflated` (516). Schema test: `test_summary_json_is_written_with_the_
documented_schema` (561). Regression re-check: `test_task_1_1_exit_code_contract_still_holds_with_the_new_
status_field` (616).

### Results
Confirmed: exit code = 1 iff any symbol is EMPTY or FAILED; PARTIAL never alone forces a non-zero exit
(PARTIAL means real, usable data was returned, just less date-range than requested — not a fetch failure);
all-success (including PARTIAL-only runs) = 0.

### Defects / Anomalies
Pre-fix, PARTIAL and FULL/EMPTY/FAILED were not distinguished at all in some code paths, and actual-vs-
requested range was never compared — the two defects this task fixed.

### Changes Made
`scripts/download_historical_1m.py`: `_STATUSES`, `DownloadResult`, `_classify_status()`,
`download_symbol()`, `main()`'s summary/exit-code logic, `download_summary.json` schema (per-symbol
`status`/`actual_start`/`actual_end`/`bars`/`error`).

### Conclusion
Downloader now reports one of 4 distinct, correctly-classified statuses per symbol, with PARTIAL never
treated as a failure and the FULL/PARTIAL boundary computed on the correct (ET) calendar-date basis.

### Limitations
None beyond ordinary unit-test coverage limits.

### Decision
Fixed and adopted; this is the status taxonomy used by every later data-download step in this project,
including the Task 7B long-history pull and Task 22's OOS data pull.

### Next Step
Task 3/4 baselines and eventually Task 7B's full 10-symbol, full-year Alpaca pull all rely on this corrected
downloader.

### Evidence
`scripts/download_historical_1m.py` (`_STATUSES`, `DownloadResult`, `_classify_status`, `main()`);
`tests/test_download_historical_1m.py` (full file, 635 lines, tests listed above).

---

## Task 3 — Controlled AAPL Real-Market Baseline

### Objective
A single-symbol, real-market (yfinance) controlled baseline to confirm end-to-end correctness before
scaling to the full 10-symbol universe.

### Hypothesis / Expected Behaviour
NOT_RECOVERED_FROM_ARTIFACT (no narrative hypothesis statement in the artifact itself).

### Inputs
Symbol: AAPL only. Period: 2026-08-07 08:00:00 UTC → 2026-08-14 23:59:00 UTC. `git_commit=
d747cd9c18fd3320740071e7a947cb754e8d9ae4`, `strategy_version=a660d03ff462`, `config_hash=19654e22ffd5`,
`run_timestamp=2026-08-17T05:32:01Z`.

### Work Performed
Single cost-free backtest, single symbol, ~1-week window.

### Validation
`backtest_data_quality.json`: `is_clean: true`, no critical corruption.

### Results
**5,754 bars processed.** 1 signal generated, 0 published, 0 trades. Data quality: 5,754 rows, 5,286
missing bars, all 5,286 classified as expected session gaps (0 unexpected — post weekend-gap-fix, since
this run's `git_commit` postdates `8f7e43e`). Rejections: `LOW_VOLATILITY` 5,601, `LOW_CONFLUENCE` 1
(5,603-line rejected-signals CSV including header, matching 5,601+1=5,602 data rows). Cost-sensitivity table
run at 4 scenarios (0/5/10/20 bps), all `trades=0`, all metrics null (no trades to measure).

### Defects / Anomalies
None recorded.

### Changes Made
None — validation run only.

### Conclusion
Confirmed clean single-symbol data quality and correct zero-trade behavior over a data-quality-clean but
extremely thin (1 candidate) window — no lifecycle claim possible from this sample.

### Limitations
0 trades — this run validates data/gate plumbing only, not trade-level behavior.

### Decision
Data pipeline validated at single-symbol scale; proceed to full 10-symbol scale.

### Next Step
Task 4: 10-symbol trade-lifecycle discovery.

### Evidence
`results/task3_aapl_baseline/` — `backtest_summary.json`/`.txt`, `backtest_data_quality.json`,
`backtest_trades.csv` (header only), `backtest_equity_curve.csv` (header only), `backtest_cost_sensitivity.
csv`, `backtest_rejected_signals.csv` (5,603 lines).

---

## Task 4 — 10-Symbol Trade-Lifecycle Discovery

### Objective
First full 10-symbol run to exercise and confirm the complete trade lifecycle (entry → exit) end to end, not
just data/gate plumbing.

### Hypothesis / Expected Behaviour
NOT_RECOVERED_FROM_ARTIFACT (no narrative hypothesis statement in the artifact itself).

### Inputs
Symbols: AAPL, AMD, AMZN, GOOGL, META, MSFT, NVDA, PYPL, STX, TSLA. Period: 2026-07-27 08:00:00 UTC →
2026-08-14 23:59:00 UTC. `git_commit=d747cd9c18fd3320740071e7a947cb754e8d9ae4`,
`run_timestamp=2026-08-17T06:00:55Z` (main run); cost-sensitivity re-run (2-symbol subset AAPL+STX)
`run_timestamp=2026-08-17T06:25:27Z`.

### Work Performed
Full 10-symbol, cost-free backtest over a ~3-week window; a second, 2-symbol (AAPL, STX) re-run specifically
to exercise the `--cost-sensitivity` flag (0/5/10/20 bps) against the same trades the full run found.

### Validation
Data-quality report confirmed clean (`is_clean: true`) for all 10 symbols, with per-symbol row/gap counts
recorded (see Results). `small_sample_warning: true` self-flagged by the report generator (3 trades).

### Results
**137,648 bars processed. 826 candidates generated, 3 published, 3 trades executed.** This backtester's
rejection funnel has a single `rejections_by_reason` bucket (there is no separately-reported "candidate-
stage" sub-bucket distinct from the bar-level gate count in this report schema — the 115,658 `LOW_VOLATILITY`
figure is the bar/opportunity-level count, which dwarfs the 826 candidates that survived it):
`LOW_VOLATILITY` 115,658; `LOW_CONFLUENCE` 699; `OPENING_BLACKOUT` 92; `LOW_RISK_REWARD` 9;
`CLOSING_BLACKOUT` 9; `LOSS_LOCKOUT` 8; `HTF_DATA_UNAVAILABLE` 5; `TREND_GATE` 1.

Per-symbol data quality (rows / missing_bars / expected / unexpected gap bars): AAPL 14,386/12,494/12,494/0;
AMD 14,371/12,509/12,509/0; AMZN 14,327/12,553/12,553/0; GOOGL 14,391/12,489/12,489/0; META
14,274/12,606/12,606/0; MSFT 14,362/12,518/12,518/0; NVDA 14,400/12,480/12,480/0; PYPL
10,263/16,617/16,616/**1**; STX 12,474/14,406/14,406/0; TSLA 14,400/12,480/12,480/0 (PYPL is the only symbol
with a genuine unexpected intra-session gap bar — 1, not a data-quality failure).

**3 executed trades, all STOP-outs, all gross_R = net_R = −1.0:**
1. `STX-2026-07-29 15:55:00+00:00` — bearish, entry 757.135, STOP exit 2026-07-29 15:59 (240s hold), mfe_r
   0.218, mae_r −1.206.
2. `STX-2026-07-29 19:59:00+00:00` — bearish, entry 769.910, STOP exit 2026-07-30 08:00 (43,260s hold),
   mfe_r 4.654, mae_r −1.973.
3. `AAPL-2026-08-03 14:01:00+00:00` — bearish, entry 304.720, STOP exit 2026-08-03 14:13 (720s hold), mfe_r
   0.261, mae_r −1.005.

Aggregate: 0/3 wins, total R −3.00, PF 0.0, expectancy −1.00, max DD −3.00R. Equity curve: cumulative R
−1.0 → −2.0 → −3.0 across the three exits in order.

**Cost-sensitivity smoke result** (2-symbol AAPL+STX re-run, same 3 trades): 0bps expectancy −1.000/total R
−3.00; 5bps expectancy −1.2758/total R −3.8274; 10bps expectancy −1.5516/total R −4.6548; 20bps expectancy
−2.1032/total R −6.3097 — win rate and PF stay 0.0/0.0 at every cost level (all 3 trades are losers
regardless of cost).

### Defects / Anomalies
None recorded for this task specifically.

### Changes Made
None — measurement/discovery run only.

### Conclusion
Confirmed the full entry→exit lifecycle executes correctly end to end across all 10 symbols, including a
same-symbol repeat entry (STX twice) and an overnight-held trade (43,260s). Sample (3 trades) is far too
small for any performance claim — this was a lifecycle-correctness discovery task, not a performance study.

### Limitations
3 trades — no statistical claim possible; this task explicitly self-flags `small_sample_warning: true`.

### Decision
Lifecycle confirmed correct; proceed to backtest-engine foundation work (reproducibility, cost sensitivity,
execution_rr/screening_rr distinction, HTF support) before attempting the full-year Task 7B/8 runs.

### Next Step
Interim Backtest Engine Validation (commits `deefce4` through `755cae7`), then Task 7B (long-history
dataset) and Task 8 (frozen 0.25% full-year baseline).

### Evidence
`results/task4_trade_lifecycle/` — `backtest_trades.csv` (3 rows), `backtest_summary.json`/`.txt`,
`backtest_equity_curve.csv`, `backtest_rejected_signals.csv`, `backtest_data_quality.json`,
`backtest_results.html`; `results/task4_trade_lifecycle_cost_sensitivity/` — same trades plus
`backtest_cost_sensitivity.csv` (4-scenario table). Also `results/smoke_test_cli_check/` — a related
5-symbol (AAPL, AMZN, META, MSFT, NVDA), 0-trade smoke run at `run_timestamp=2026-08-17T04:40:02Z` (the same
run that produced the pre-fix 780-bar weekend-gap evidence used in Task 2.1).

---

## Interim Backtest Engine Validation (between Task 4 and Task 7B/8)

This work was not assigned individual task numbers in any recovered artifact — it is reconstructed here from
git commit history (`git log`) as a single labeled section per this backfill's own instructions, covering
the period between Task 4 (10-symbol lifecycle discovery, commit `d747cd9`) and Task 7B/8 (long-history
dataset + frozen baseline). All commits below are on `research/talonx-strategy-validation`, chronological.

### Objective
Build the `talonx_backtest` engine itself: replay historical 1-minute OHLCV through the exact same
`talonx_quant` strategy/indicator/gate code the live consumer uses (no duplicated formulas), with
correctness guarantees (no look-ahead, deterministic reproducibility) and research-usability features
(cost sensitivity, R:R clarity, reporting) needed before any large-scale historical experiment could be
trusted.

### Inputs
N/A (engine construction, not a data experiment).

### Work Performed (chronological, by commit)

**`deefce4` — "Add historical backtesting/quant-validation engine reusing the frozen live strategy"**
(2026-08-16 15:36:04 +0100, 23 files, +4026/−40 lines). Founding commit. Quoted: *"talonx_backtest replays
historical 1-min OHLCV through the SAME talonx_quant strategy/indicator/gate code the live consumer uses (no
duplicated formulas)... Includes look-ahead-bias tests, a live-vs-backtest signal regression fixture,
same-bar stop/target resolution, slippage/spread, cooldown/throttle/loss-lockout/EOD-flatten simulation,
performance metrics (PF/expectancy/drawdown/Sharpe/MFE-MAE incl. win/loss split)."* Created
`talonx_backtest/{__init__,__main__,analysis,cli,data,engine,execution,metrics,portfolio,reports}.py` and 11
new test files. Also extracted `talonx_quant/consumer.py`'s HTF bar-bucketing into a new shared
`talonx_quant/aggregation.py` (`HtfBarAggregator`) so live and backtest build 15-minute candles via
identical logic — quoted: *"a pure refactor, verified against the full pre-existing test suite with no
behavior change."*

**`6803e61` — "Add UX/research-integrity layer: reproducibility, data-safety, cost sensitivity, docs"**
(2026-08-16 16:47:19 +0100, 19 files, +2658/−53). Quoted: *"Critical data corruption... now hard-aborts the
run via DataValidationError... Missing-bar gaps are now split into expected... vs unexpected... Every
report now carries reproducibility metadata (git commit, strategy/backtester version fingerprints, config
hash, run timestamp), execution assumptions with a prominent cost-free-baseline warning... New
--cost-sensitivity CLI mode runs the same frozen strategy across 0/5/10/20 bps scenarios."* Added
`talonx_backtest/reproducibility.py`, `docs/backtesting.md`. 56 new tests; strategy thresholds/scoring/gates
explicitly untouched.

**`e094336` — "Add trade/execution/EOD-flatten test fixtures, R:R schema clarity, and historical-data
tooling"** (2026-08-16 19:35:25 +0100, 19 files, +3938/−102). Quoted: *"Add Trade.execution_rr (reward:risk
at the actual fill price) and Trade.screening_rr (explicit alias of the existing risk_reward_ratio) so a
trade ledger reader can distinguish 'what R:R the strategy's gate approved' from 'what R:R was actually
available at the fill'... Add scripts/download_historical_1m.py... and scripts/run_historical_regimes.
py."* 86 new/updated tests, including a live yfinance smoke test and a real end-to-end regime-runner
subprocess test.

**`755cae7` — "Add execution_rr, small-sample HTML warning, real cost-sensitivity coverage, and yfinance
chunking fix"** (2026-08-16 21:05:02 +0100, 9 files, +473/−65). Finalized `execution_rr` — quoted: *"Trade
gains execution_rr (reward:risk at the actual fill price, independent of exit_reason) alongside the
existing risk_reward_ratio/screening_rr (the strategy's gate-time R:R, unchanged — confirmed by tracing
talonx_quant.consumer._opportunity_score that this is exactly what feeds the 30%-weighted opportunity
score, never execution_rr)."* Added `reports.is_small_sample()` (threshold 30 trades). yfinance path now
chunks wide date ranges into 7-day sliding windows (Yahoo's 1-minute-granularity request cap). 98 tests
passed, 1 skipped.

**`624dfbe` — "Add live progress reporting for backtest runs"** — `BacktestEngine.run()` gains a
`progress_callback`; CLI gains `--progress-interval`/`--no-progress`. No strategy/scoring changes.

**`22d1d48`/`63a4630`/`a6a8b23`/`90a0d8c`** — pure report-artifact versioning churn (add/remove/re-add
cycles for `results/latest/` and `reports/` as checked-in examples). No code changes.

### Validation
| Concept | Test file | Function count |
|---|---|---|
| No-lookahead | `tests/test_backtest_lookahead.py` | 4 |
| HTF aggregation | `tests/test_backtest_htf_aggregation.py` | 5 |
| Execution (stop-first same-bar, slippage, MFE/MAE, screening_rr/execution_rr) | `tests/test_backtest_execution.py` | 28 |
| Metrics (PF/expectancy/drawdown/Sharpe/MFE-MAE split) | `tests/test_backtest_metrics.py` | 15 |
| Reproducibility (git/strategy/config/dataset hashes) | `tests/test_backtest_reproducibility.py` | 31 |
| **Total** | | **83** |

Key confirmed behaviors, by test name: `test_bullish_same_bar_ambiguity_defaults_to_stop_first` /
`test_bearish_same_bar_ambiguity_defaults_to_stop_first` (stop-first same-bar rule, confirmed default and
configurable); `test_screening_rr_is_copied_verbatim_from_the_published_signal` /
`test_execution_rr_uses_the_real_fill_price_not_the_screening_reference_price` /
`test_execution_rr_is_independent_of_how_the_trade_actually_exited` (screening_rr vs. execution_rr
distinction); `test_mfe_mae_track_the_running_extremes_before_exit` (MFE/MAE); `test_net_pnl_reflects_costs_
while_gross_does_not` (cost model); `test_dataset_hash_matches_load_ohlcv_directorys_own_file_selection_
rule` / `test_strategy_version_changes_when_a_fingerprinted_file_changes` (deterministic fingerprints).

### Results
N/A — infrastructure build, not a data experiment. End state: a working `talonx_backtest` engine with
look-ahead protection, HTF support, deterministic reproducibility fingerprints, cost-sensitivity scenarios,
and a clear screening_rr/execution_rr distinction, ready for the Task 7B/8 full-year run.

### Defects / Anomalies
None recorded as found during this phase (defects found later — Task 13's fill-geometry issue — postdate
this phase entirely).

### Changes Made
See Work Performed above — the entirety of `talonx_backtest/` was built during this phase.

### Conclusion
Engine infrastructure complete and tested (83 focused tests across the 5 core-correctness files alone, plus
56+86+98 additional tests across the reproducibility/data-safety/execution-fixture commits) ahead of the
first full-year run.

### Limitations
N/A — this phase's own scope was infrastructure, not a performance claim.

### Decision
Adopted; proceed to Task 7B (long-history dataset acquisition) and Task 8 (full-year 0.25% baseline).

### Next Step
Task 7B, Task 8.

### Evidence
Commits `deefce4acf4793ee4ce420be8e0c905751a31981`, `6803e615c9725ec0d185988006dda3bed224a369`,
`e0943360b59603dec38c5ce55656b5c2a617464d`, `755cae7c3039e4bf074fb6f00a3ab5b1bea4858b`,
`624dfbe44a19da90f98bda2db85bec66920d58df` (`git show --stat <hash>` for each); resulting code
`talonx_backtest/*.py`, `talonx_quant/aggregation.py`; tests listed above.

---

## Task 6 — Empirical Baseline (short-window smoke test)

### Objective
A short-window (recent ~3 weeks), cost-free, 10-symbol empirical baseline of the frozen strategy, likely to
confirm the engine and gate pipeline behave sanely on a modest data volume before committing to a full-year
run.

### Hypothesis / Expected Behaviour
Not stated in the artifact itself (no narrative summary file, only report-generated disclaimers). The
report is explicitly self-flagged as a small-sample illustration, not a performance claim.

### Inputs
- Symbols: AAPL, AMD, AMZN, GOOGL, META, MSFT, NVDA, PYPL, STX, TSLA
- Period: 2026-07-27 08:00:00 UTC → 2026-08-14 23:59:00 UTC (137,648 bars)
- `git_commit=d747cd9c18fd3320740071e7a947cb754e8d9ae4`, `strategy_version=00b9d52fedad`,
  `config_hash=19654e22ffd5`, `dataset_hash=1cb1977fa043`, `run_timestamp=2026-08-17T20:51:32Z`,
  `working_tree_dirty: true`

### Work Performed
Single cost-free backtest run, no cost sensitivity, no parameter sweep.

### Validation
NOT_RECOVERED_FROM_ARTIFACT (no dedicated test file or validation note found for this specific run beyond
the standard report-generated data-quality section).

### Results
3 trades executed (from 826 signals generated, 3 published). 0 wins / 3 losses. Win rate 0%. Total R
−3.00. Expectancy −1.00 R/trade. Max drawdown −3.00R. Symbol breakdown: STX 2 trades (−2.00R), AAPL 1 trade
(−1.00R). Rejections dominated by `LOW_VOLATILITY` (115,658 of ~116,700 total).

### Defects / Anomalies
None recorded.

### Changes Made
None — measurement only.

### Conclusion
No written conclusion exists in the artifact beyond its own explicit self-caveats (quoted from the report):
`"*** COST-FREE BASELINE ***"` and `"*** SMALL SAMPLE (3 trades) ***"` — "Sharpe, Sortino, and confidence
intervals below are NOT statistically reliable at this trade count... treat them as illustrative only."

### Limitations
3 trades is far too small a sample for any performance claim — explicitly self-flagged by the report
generator itself, not a limitation discovered later.

### Decision
NOT_RECOVERED_FROM_ARTIFACT (no explicit decision/next-step statement found in this report).

### Next Step
Presumed precursor to the full-year baseline (Task 8), based on file naming and directory adjacency, but
this linkage is inferred from context, not stated in either artifact.

### Evidence
`reports/task6_empirical_baseline/` — `task6_baseline_trades.csv`, `task6_baseline_trades.json`,
`task6_baseline_summary.json`, `task6_baseline_summary.txt`, `task6_baseline_equity_curve.csv`,
`task6_baseline_rejected_signals.csv`, `task6_baseline_data_quality.json`, `task6_baseline_results.html`.
(Note: this directory is covered by `.gitignore`'s `reports/` rule and was never committed to git — it
exists only as a local, uncommitted artifact.)

---

## Interim note — `reports/regimes_summary/`

Found empty (zero files) during this backfill. Not git-tracked. Cannot be attributed to any task with
available evidence. Recorded here so a future researcher does not re-investigate it expecting content.

---

## Task 7B — Long-History Dataset (Alpaca SIP)

### Objective
Acquire a full one-year, 10-symbol, 1-minute OHLCV dataset from a higher-quality provider (Alpaca, SIP
consolidated tape) to replace the shorter yfinance-sourced windows used in Tasks 2–6, providing enough
history for a statistically meaningful full-year backtest.

### Hypothesis / Expected Behaviour
NOT_RECOVERED_FROM_ARTIFACT (no standalone Task 7B report/markdown exists on disk — see Evidence).

### Inputs
- Symbols: AAPL, MSFT, NVDA, AMZN, META, AMD, TSLA, GOOGL, PYPL, STX
- Requested range: 2025-08-15 → 2026-08-14
- Provider: Alpaca (per `download_summary.json`, `"provider": "alpaca"`)
- Directory: `data/historical_1m/task7b_alpaca_long_history/`

### Work Performed
Downloaded via `scripts/download_historical_1m.py` (the Task 2.2-corrected downloader) using the Alpaca
provider path.

### Validation
All 10 symbols returned `"status": "FULL"` in `download_summary.json` — the full requested range was
covered for every symbol, per symbol-level actual start/end vs. requested comparison.

### Results
Per-symbol bar counts and actual coverage (from `download_summary.json`):

| Symbol | Bars | Actual start | Actual end |
|---|---:|---|---|
| AAPL | 189,563 | 2025-08-15 08:00 UTC | 2026-08-14 23:59 UTC |
| MSFT | 199,156 | 2025-08-15 08:00 UTC | 2026-08-14 23:59 UTC |
| NVDA | 237,875 | 2025-08-15 08:00 UTC | 2026-08-14 23:59 UTC |
| AMZN | 194,988 | 2025-08-15 08:00 UTC | 2026-08-14 23:59 UTC |
| META | 184,201 | 2025-08-15 08:19 UTC | 2026-08-14 23:59 UTC |
| AMD | 204,714 | 2025-08-15 08:00 UTC | 2026-08-14 23:59 UTC |
| TSLA | 234,652 | 2025-08-15 08:00 UTC | 2026-08-14 23:59 UTC |
| GOOGL | 191,394 | 2025-08-15 08:00 UTC | 2026-08-14 23:59 UTC |
| PYPL | 142,095 | 2025-08-15 08:00 UTC | 2026-08-14 23:59 UTC |
| STX | 124,406 | **2025-08-15 13:03 UTC** | 2026-08-14 23:58 UTC |

STX's later start (13:03 UTC vs. 08:00 UTC for the others) and slightly earlier end (23:58 vs. 23:59)
sets the **common usable period across all 10 symbols** used by every downstream task:
**2025-08-15 13:03 UTC → 2026-08-14 23:58 UTC**, ~1.9M bars total when combined and merge-sorted (confirmed
exactly at 1,901,714 bars in Task 8's own `bars_processed` figure, and reused unchanged in Task 13/13B).
**Dataset hash: `5e5412a960bf`** (`talonx_backtest.reproducibility.get_dataset_hash`, confirmed
independently-reproducible and used as the fixed dataset fingerprint through Task 22).

### Defects / Anomalies
None reported by the downloader (all FULL status, no PARTIAL/EMPTY/FAILED). The general holiday-gap
false-positive caveat documented in Task 2.1 (`talonx_backtest/data.py:48-54`) applies to this dataset like
any other — no calendar library exists in the repo to distinguish a holiday gap from a genuine unexpected
gap, so any exchange holiday inside this year-long window would still be misclassified as an unexpected
intra-session gap by `check_data_quality`'s reporting (a cosmetic data-quality-report issue, not a
correctness issue for the strategy itself, which never consults that classification for gating decisions).

### Changes Made
None — data acquisition only.

### Conclusion
A clean, FULL-status, ~1.9M-bar, 10-symbol, one-year dataset was established and became the fixed input for
every subsequent research task (Task 8 through Task 22) via its dataset hash `5e5412a960bf`.

### Limitations
Holiday-gap classification caveat (see Defects/Anomalies) — deferred, not resolved, consistent with Task
2.1's decision.

### Decision
Adopted as the canonical research dataset; no further download work performed against this universe/range
for the remainder of the research track (Task 22's OOS pull used a **separate**, later, non-overlapping
window and directory specifically to avoid touching this canonical dataset).

### Next Step
Task 8: full-year 0.25% frozen baseline using this dataset.

### Evidence
`data/historical_1m/task7b_alpaca_long_history/download_summary.json` (provider, per-symbol status/bars/
actual range); `data/historical_1m/task7b_alpaca_long_history/*.csv` (10 symbol files); dataset hash
`5e5412a960bf` independently reproduced and cited throughout `results/task13_atr_threshold_experiment/`
onward. No standalone `results/task7b*` or `reports/task7b*` narrative document exists on disk — this entry
is reconstructed entirely from the dataset directory's own `download_summary.json` and its downstream usage
fingerprints.
## Task 8 — Frozen 0.25% Baseline

### Objective
Establish the full-year, cost-free, 10-symbol performance baseline for the frozen strategy at its
production-default `min_atr_pct=0.25%` threshold — the reference point every later ATR-threshold experiment
(Task 12, Task 13) measured against.

### Hypothesis / Expected Behaviour
NOT_RECOVERED_FROM_ARTIFACT (no narrative hypothesis statement found in the report itself; this was a
baseline-establishment run, not a hypothesis test).

### Inputs
- Symbols: AAPL, MSFT, NVDA, AMZN, META, AMD, TSLA, GOOGL, PYPL, STX
- Period: 2025-08-15 13:03:00 UTC → 2026-08-14 23:58:00 UTC (1,901,714 bars)
- `min_atr_pct=0.25%` (the production default per `docs/modules/quant.md:573`'s documented
  `TALONX_QUANT_MIN_ATR_PCT` default; not printed inside the task8 artifact itself, but independently
  confirmed by `results/task13_atr_threshold_experiment/task13_summary.md:3`, which explicitly labels this
  run "the existing 0.25% baseline")
- `git_commit=5f5553836c3f4eceb9f82c447010ab8791d35ce4`, `strategy_version=f200697264ca`,
  `config_hash=19654e22ffd5`, `dataset_hash=5e5412a960bf`, `run_timestamp=2026-08-18T02:58:23Z`,
  `working_tree_dirty: false`

### Work Performed
Single full-year, cost-free backtest at the production-default threshold.

### Validation
NOT_RECOVERED_FROM_ARTIFACT beyond the standard report-generated data-quality section (no dedicated test
file identified for this specific run).

### Results
93 trades executed (5,021 candidates generated, 96 published). **18 wins / 74 losses / 1 breakeven — win
rate 19.3548%.** Average win 3.3754R, average loss −1.0000R. **Total R −13.2436. Profit factor 0.8210.**
Expectancy −0.1424 R/trade. **Max drawdown −20.7617R.** Avg holding 104.92 min, median 10.00 min. Best
trade 9.1582R, worst −1.0000R. Sharpe −0.0684, Sortino −0.3532. 95% CIs: win rate [0.1133, 0.2738], n=93;
expectancy [−0.5653, 0.2805], n=93.

Symbol breakdown (gross_R basis, from `task8_baseline_trades.csv`): STX 53 trades (+3.0388R, 10 wins), AMD
17 trades (−9.1517R, 3 wins), TSLA 9 trades (−4.5619R, 1 win), NVDA 5 trades (+1.7405R, 2 wins), AAPL 3
trades (−3.0000R, 0 wins), PYPL 4 trades (+0.6908R, 2 wins), META 1 trade (−1.0000R, 0 wins), MSFT 1 trade
(−1.0000R, 0 wins). Sums reconcile exactly to 93 trades / 18 wins.

Rejections by reason: `LOW_VOLATILITY` 1,780,567; `LOW_CONFLUENCE` 3,535; `OPENING_BLACKOUT` 930;
`LOW_RISK_REWARD` 155; `LOSS_LOCKOUT` 108; `PREMARKET_LIQUIDITY` 79; `CLOSING_BLACKOUT` 55; `TREND_GATE` 40;
`COOLDOWN` 23.

### Defects / Anomalies
None identified at the time. **Important historical note, confirmed only much later**: Task 13B's
fill-geometry-fix work (2026-08-19/20) verified that **0 of these 93 trades** had invalidated stop
geometry — meaning the execution-geometry defect discovered in Task 13 (which affected 3/181 trades at
0.20% and 6/375 at 0.15%) did not affect this 0.25% baseline at all, and Task 8 therefore never required a
rerun. This confirmation happened during Task 13B, roughly a year of in-story time after Task 8 itself ran
— it was not, and could not have been, known during Task 8.

### Changes Made
None — measurement only.

### Conclusion
Established the reference baseline against which Tasks 9, 11, 12, and 13 were all measured: a negative-
expectancy, sub-1.0-profit-factor result at the strategy's production-default threshold, with STX (57% of
trades) and AMD as the dominant symbols and every mega-cap either absent or losing.

### Limitations
Cost-free, no-slippage. Trade-level R-multiple analysis only.

### Decision
Adopted as the fixed comparison baseline for all subsequent ATR-threshold research.

### Next Step
Task 9 (why STX dominated), then Tasks 10–13 (threshold and telemetry research), all measured against this
baseline.

### Evidence
`reports/task8_long_history_baseline/` — `task8_baseline_trades.csv` (93 rows), `task8_baseline_summary.
json`/`.txt`, `task8_baseline_equity_curve.csv`, `task8_baseline_rejected_signals.csv` (1,785,476 lines),
`task8_baseline_data_quality.json`, `task8_baseline_results.html`. Cross-referenced and confirmed by
`results/task13_atr_threshold_experiment/task13_summary.md` (0.25 baseline column) and
`results/task13b_execution_fix_validation/task13b_summary.md` (0/93 geometry-invalidation confirmation).
(This directory is covered by `.gitignore`'s `reports/` rule and was never committed to git.)

---

## Task 9 — STX Dominance Investigation

### Objective
Explain why STX dominated the 0.25% baseline's trade count and result (57% of trades in Task 8).

### Hypothesis / Expected Behaviour
NOT_RECOVERED_FROM_ARTIFACT — no primary Task 9 artifact exists on disk (see Evidence).

### Inputs
NOT_RECOVERED_FROM_ARTIFACT.

### Work Performed
NOT_RECOVERED_FROM_ARTIFACT — no dedicated `reports/task9*` or `results/task9*` directory, no standalone
Task 9 markdown/JSON, and no git history entry exists anywhere in this repository. Confirmed via `find`,
`git log --all --diff-filter=A`, and `git log --all --grep` searches, none of which located a Task 9
artifact.

### Validation
NOT_RECOVERED_FROM_ARTIFACT.

### Results
NOT_RECOVERED_FROM_ARTIFACT as a primary result. The task's headline conclusion is preserved only via
**later tasks' retrospective references**, quoted here verbatim rather than paraphrased from memory:

- `results/task13_atr_threshold_experiment/task13_summary.md:198`: *"Confluence score is 2 for literally
  every executed trade at every threshold (Task 9's finding persists exactly) — lower thresholds add more
  score-2 opportunities, never a score-3 trade."*

This confirms the task prompt's recalled conclusion — **"STX passed the normalized volatility gate much
more often; it did not have superior confluence"** — is consistent with the one directly-quotable
retrospective reference available (confluence was never the differentiator, at any threshold, for any
symbol), though the ATR/volatility-gate-pass-rate half of that conclusion has no directly quotable primary
source recovered.

### Defects / Anomalies
NOT_RECOVERED_FROM_ARTIFACT.

### Changes Made
NOT_RECOVERED_FROM_ARTIFACT.

### Conclusion
Only recoverable via the Task 13 retrospective quote above. The underlying primary analysis is not present
on disk.

### Limitations
This entire entry is reconstructed from a single downstream citation, not from Task 9's own artifact —
treat with appropriately reduced confidence versus every other entry in this ledger, which cites primary
sources directly.

### Decision
NOT_RECOVERED_FROM_ARTIFACT.

### Next Step
Presumed to feed into Task 10 (telemetry) and Task 11 (ATR distribution analysis), based on narrative
adjacency in later citations, not on direct evidence of a hand-off.

### Evidence
No primary artifact exists. Secondary evidence only: `results/task13_atr_threshold_experiment/
task13_summary.md:198` (quoted above).

---

## Task 10 — Research Telemetry

### Objective
Add opt-in, observational-only per-bar volatility-gate telemetry and per-candidate-signal telemetry to the
backtest engine, without altering any gate/decision logic.

### Hypothesis / Expected Behaviour
Telemetry capture should be purely additive: identical trades/signals/rejections output whether or not the
flag is enabled.

### Inputs
- Symbols: same 10-symbol universe
- Period (this smoke run): 2025-09-15 08:00:00 UTC → 2025-09-25 23:59:00 UTC (63,854 bars)
- `git_commit=5f5553836c3f4eceb9f82c447010ab8791d35ce4`, `strategy_version=f200697264ca`,
  `config_hash=19654e22ffd5`, `dataset_hash=5e5412a960bf`, `run_timestamp=2026-08-18T04:37:52Z`

### Work Performed
Added `research_telemetry` opt-in capture producing two new artifacts per run:
`<prefix>_research_volatility_telemetry.csv` (columns: `timestamp, symbol, price, atr, atr_pct,
volatility_threshold, passes_volatility` — one row per bar with a valid indicator snapshot) and
`<prefix>_research_candidate_telemetry.csv` (columns: `timestamp, symbol, direction, signal_type, session,
price, rsi, macd, macd_signal_line, volume_surge_ratio, confluence_score, risk_reward_ratio,
trend_component` — one row per raw candidate signal, before any gate). This 10-day window run is the
smoke-test artifact confirming the new telemetry fields populate correctly.

### Validation
NOT_RECOVERED_FROM_ARTIFACT as an isolated count for this specific task, but see Task 20/21-era code
docstring in `talonx_backtest/engine.py` (`research_telemetry` parameter docstring) which references
"tests/test_backtest_research_telemetry.py's parity test" confirming identical output with the flag on vs.
off — that test file exists in the current repo (`tests/test_backtest_research_telemetry.py`) though its
exact test count at Task 10's original time is not separately recoverable.

### Results
This smoke run: 60 candidates generated, 1 published, **1 trade executed** — `NVDA-2025-09-22 16:36:00+00:00`,
bearish, entry 183.095, stop 183.9012, target 175.1, STOP exit, gross_R=net_R=−1.0000, holding 1,080 sec.
0 wins / 1 loss, Total R −1.0000, max DD −1.0000. Rejections: `LOW_VOLATILITY` 61,114 (dominant), plus
`LOW_CONFLUENCE` 43, `OPENING_BLACKOUT` 14, `LOW_RISK_REWARD` 1, `PREMARKET_LIQUIDITY` 1. Sample volatility-
telemetry row confirms the 0.25% ATR threshold field populates correctly: `2025-09-15 09:59:00+00:00,NVDA,
173.37,0.14312936907709642,0.08255717198886567,0.25,False`.

### Defects / Anomalies
None recorded for this task specifically.

### Changes Made
`talonx_backtest/engine.py`: added `research_telemetry` flag and the two telemetry CSV outputs (backtester-
only scope — this is explicitly documented in the current codebase as not touching any live/paper module).

### Conclusion
Telemetry capture works and is additive/non-disruptive, per the purpose stated. This is infrastructure, not
a strategy-performance finding.

### Limitations
Backtester-only scope — no live-pipeline observability implication should be drawn from this task (that is
a separate, later body of work; see the Live/Observability section of this ledger).

### Decision
Adopted; used as the data source for Task 11's ATR-window analysis.

### Next Step
Task 11: apply this telemetry across three chronological windows to analyze ATR pass-rate distribution.

### Evidence
`reports/task10_research_telemetry/` — `task10_trades.csv`, `task10_trades.json`, `task10_summary.json`/
`.txt`, `task10_equity_curve.csv`, `task10_rejected_signals.csv`, `task10_data_quality.json`,
`task10_results.html`, `task10_research_volatility_telemetry.csv`, `task10_research_candidate_telemetry.
csv`; code `talonx_backtest/engine.py` (`research_telemetry` parameter); test
`tests/test_backtest_research_telemetry.py` (exists in current repo). (This directory is covered by
`.gitignore`'s `reports/` rule and was never committed to git.)

---

## Task 11 — ATR Distribution / Pass-Rate Analysis (3 chronological windows)

### Objective
Use Task 10's telemetry across multiple chronological windows to characterize the ATR-gate pass-rate
distribution and its relationship to candidate/trade volume, including a per-symbol breakdown.

### Hypothesis / Expected Behaviour
NOT_RECOVERED_FROM_ARTIFACT (no narrative hypothesis statement found in the recovered artifacts).

### Inputs
Three separate ~10-day windows, all at the same fingerprint (`git_commit=
5f5553836c3f4eceb9f82c447010ab8791d35ce4`, `strategy_version=f200697264ca`, `config_hash=19654e22ffd5`,
`dataset_hash=5e5412a960bf`):
- **Window A**: 2025-11-10 09:00 UTC → 2025-11-21 00:00 UTC (69,209 bars), run_timestamp 2026-08-18T04:51:10Z
- **Window B**: 2026-02-09 09:00 UTC → 2026-02-20 00:00 UTC (60,000 bars), run_timestamp 2026-08-18T04:58:31Z
- **Window C**: 2026-06-08 08:00 UTC → 2026-06-18 23:59 UTC (72,603 bars), run_timestamp 2026-08-18T05:07:32Z

### Work Performed
Three telemetry-enabled backtest runs at different points in the calendar year (Nov 2025 / Feb 2026 / Jun
2026), producing the same volatility/candidate telemetry CSVs as Task 10, one set per window.

### Validation
NOT_RECOVERED_FROM_ARTIFACT beyond the standard report-generated data-quality section for each window.

### Results
**Window A** (Nov 2025): 281 candidates, 5 published, **5 trades**: 3 wins / 2 losses, win rate 60.0%.
Total R 5.7893, PF 3.8946, expectancy 1.1579. Trades: TSLA-2025-11-17 (STOP, −1.0R), AMD-2025-11-19 17:04
(TARGET, +1.8060R), AMD-2025-11-19 21:21 (STOP, −1.0R), NVDA-2025-11-20 (TARGET, +1.6010R), STX-2025-11-20
23:12 (DATA_END exit, +4.3823R).

**Window B** (Feb 2026): 153 candidates, **0 published, 0 trades**. Quoted from the report: *"No trades
were executed -- see `rejections` for the gate funnel (no fabricated metrics below)."*

**Window C** (Jun 2026): 276 candidates, 2 published, **2 trades**: 0 wins / 2 losses, win rate 0%. Total R
−2.0000, PF 0.0000, expectancy −1.0000. Trades: AMD-2026-06-10 19:56 (STOP, −1.0R), STX-2026-06-11 16:02
(STOP, −1.0R).

**The specific claims "STX had the highest median ATR/pass rate across all evaluated windows" and "pass
rate → candidate count correlation ≈0.947" could NOT be independently recovered** — no aggregate summary
document synthesizing the three windows' telemetry into these specific statistics was found on disk. The
raw per-bar volatility telemetry CSVs (which would contain the underlying data needed to compute such a
correlation) exist for all three windows, but the aggregate analysis itself is **NOT_RECOVERED_FROM_
ARTIFACT** — mark this specific figure as unverified pending discovery of the original analysis document, or
as requiring fresh computation from the raw telemetry CSVs if ever needed again (which this backfill task
does not authorize).

### Defects / Anomalies
None recorded in the per-window reports.

### Changes Made
None — measurement only.

### Conclusion
Directly supported by artifacts: ATR-gate pass rate and resulting trade volume vary substantially by
calendar window (0 trades in Feb 2026 vs. 5 in Nov 2025 vs. 2 in Jun 2026, from a similar ~10-day/~60-70K-bar
sample size each) — regime dependence in candidate generation is real and visible. The specific STX-
dominance and 0.947-correlation claims are plausible extensions of this pattern but are **not independently
verified** from the artifacts recovered for this backfill.

### Limitations
3 short (~10-day) windows is a small sample for characterizing year-round ATR-gate behavior. Whichever
document originally computed the STX/correlation conclusion is not present on disk for this backfill to
cite directly.

### Decision
NOT_RECOVERED_FROM_ARTIFACT (no explicit decision statement found).

### Next Step
Presumed to feed into Task 12's threshold grid, based on narrative adjacency.

### Evidence
`reports/task11_window_a/`, `reports/task11_window_b/`, `reports/task11_window_c/` — each with
`task11_trades.csv/json`, `task11_summary.json/.txt`, `task11_equity_curve.csv`,
`task11_rejected_signals.csv`, `task11_data_quality.json`, `task11_results.html`,
`task11_research_volatility_telemetry.csv`, `task11_research_candidate_telemetry.csv`. (These directories
are covered by `.gitignore`'s `reports/` rule and were never committed to git.)

---

## Task 12 — Post-Hoc ATR Threshold Grid

### Objective
Test a grid of `min_atr_pct` levels to characterize how gate strictness affects symbol accessibility
(particularly mega-caps), independent of whether any level is actually profitable.

### Hypothesis / Expected Behaviour
NOT_RECOVERED_FROM_ARTIFACT — no primary Task 12 artifact exists on disk (see Evidence).

### Inputs
NOT_RECOVERED_FROM_ARTIFACT.

### Work Performed
NOT_RECOVERED_FROM_ARTIFACT — no dedicated `reports/task12*` or `results/task12*` directory, no standalone
Task 12 markdown/JSON, and no git history entry exists anywhere in this repository. Confirmed via the same
`find`/`git log --all --diff-filter=A`/`git log --all --grep` search methodology used for Task 9, with the
same negative result.

### Validation
NOT_RECOVERED_FROM_ARTIFACT.

### Results
NOT_RECOVERED_FROM_ARTIFACT as a primary result. Preserved only via later tasks' retrospective references,
quoted verbatim:

- `results/task13_atr_threshold_experiment/task13_summary.md:197`: *"Mega-cap accessibility improves
  exactly as Task 12 predicted (bar-level volatility rejections drop 5.6–12.0% across mega-caps, trade
  counts go from 0–5 to 6–29), but *every* mega-cap that trades loses money at every threshold —
  accessibility does not translate to successful qualification for profit."*
- `reports/live_session_2026-08-18_pre_sleep_analysis/pre_sleep_summary.md:145` (from Agent research,
  quoted): *"...loosely consistent with (not proof of) Task 12's prediction that 0.15% broadens
  accessibility... `LOW_CONFLUENCE` is the dominant downstream filter... both consistent with every prior
  finding from Tasks 9–12."*

These two independent downstream citations corroborate each other and confirm the task prompt's recalled
conclusion: **"0.25% structurally favors high-normalized-volatility names; mega-cap accessibility improves
around ~0.15–0.20%; but Task 12 did NOT establish profitability."** The explicit "improves around
~0.15-0.20%" numeric range and the specific tested threshold GRID (which exact levels beyond 0.25/0.20/0.15
were tested, if any) could not be independently recovered — only the qualitative direction and the
0.20%/0.15% endpoints (which Task 13 itself tested) are corroborated.

### Defects / Anomalies
NOT_RECOVERED_FROM_ARTIFACT.

### Changes Made
NOT_RECOVERED_FROM_ARTIFACT.

### Conclusion
Accessibility-improves-but-profitability-not-established, corroborated by two independent downstream
citations (Task 13's summary and a live-session analysis report), but the primary Task 12 artifact itself
is not present on disk.

### Limitations
This entire entry is reconstructed from downstream citations, not from Task 12's own artifact — treat with
appropriately reduced confidence versus every other entry in this ledger.

### Decision
NOT_RECOVERED_FROM_ARTIFACT.

### Next Step
Directly fed into Task 13 (which tested the 0.20%/0.15% thresholds Task 12's accessibility finding pointed
to, and confirmed the "accessibility without profitability" pattern held for every mega-cap at every
threshold tested).

### Evidence
No primary artifact exists. Secondary evidence only: `results/task13_atr_threshold_experiment/
task13_summary.md:197` and `reports/live_session_2026-08-18_pre_sleep_analysis/pre_sleep_summary.md:145`
(both quoted above).
## Live / Observability Work (ambiguous numbering — grouped chronologically)

This section covers the live/paper-trading and pipeline-observability work that ran alongside the backtest
research track above, on 2026-08-18. It has no consistent task numbering in the recovered artifacts (most
of it landed in a single commit plus a set of untracked `reports/live_session_2026-08-18*` investigation
reports). Grouped here as its own labeled section per this backfill's own instructions.

**Operational validation is not profitability validation** — everything in this section concerns whether the
live pipeline runs correctly, not whether the strategy is profitable. None of these findings should be read
as evidence for or against any of the backtest-research conclusions above or below.

**Primary commit**: `068269387e063df2c5e1be3ff3653955801f7bb4`, "feat(research): harden live pipeline and
add research observability" (Ritesh Talwadekar, 2026-08-18 23:47:33 +0100), 23 files changed. This single
commit delivered fixes D1–D9 below, plus Task 10's backtest research telemetry. The later watchlist-
telemetry/rejection-granularity refinements (see "EOD-fix task" below) remain uncommitted/untracked.

### D1 — Temporary 0.15% process-scoped experiment

**Objective**: observe live opportunity flow at a looser ATR gate without any source-code change.
**Mechanism**: `TALONX_QUANT_MIN_ATR_PCT=0.15` environment-variable override at process launch (production
default remains 0.25% in `talonx_quant/config.py:297`); confirmed live via direct `/proc/<pid>/environ`
read and `psutil.Process().environ()` — worker PIDs 21328 (initial launch, `2026-08-18T05:49:16Z`) and
15112 (post-fix continuation, `2026-08-18T14:12:23Z`). Explicitly distinct from the backtest-research
0.20%/0.15% threshold sweep (Tasks 11–13) — this was a live, process-scoped, single-parameter override, with
`FIXES_APPLIED.md` explicitly confirming zero other parameter changes.
**Result**: 12 candidates observed across parts of one trading day (8 pre-sleep + 4 post-restart), 2
published, spanning 8 of 39 tracked symbols. Classified **`INSUFFICIENT_LIVE_SAMPLE`** — quoted: *"No
profitability claim made. 12 candidates across parts of one trading day is not enough to characterize
opportunity-flow breadth at 0.15% vs the 0.25% baseline."* Baseline (0.25%) reversion later confirmed via a
fresh interpreter with the env var popped (`BASELINE_0_25_CONFIRMED`).
**Evidence**: `reports/live_session_2026-08-18/session_manifest.json`,
`reports/live_session_2026-08-18_post_fix/session_manifest.json`,
`reports/live_session_2026-08-18_post_fix/FIXES_APPLIED.md`,
`reports/live_session_2026-08-18_eod_analysis/eod_summary.md` §20.

### D2/D6/D9 — yfinance provider limitations, premarket arbitration, session=closed gate

- **yfinance has no genuine bid/ask.** `talonx_ingest/market_data/yfinance_poll.py` only ever emits `BAR`
  events (never `QUOTE`), so `talonx_quant/consumer.py`'s `_latest_quotes` cache (populated only from real
  `QUOTE` events) stays empty on yfinance. New rejection reason `PREMARKET_PROVIDER_UNSUPPORTED`
  (distinguished from `PREMARKET_LIQUIDITY`, which means a quote *was* available but genuinely too
  thin/stale/wide) — quoted: *"the gate already failed closed correctly on yfinance ... the real gap was
  mislabeling."* No pass/fail behavior changed, only the label.
- **Normal vs. premarket stream arbitration**: `YFinancePoller.stream()` used to keep republishing stale
  `fast_info` prices during the premarket window, racing `PreMarketPoller`'s genuine premarket bars on the
  same Redis channel. Fix suppresses `YFinancePoller`'s *publication* (not fetching, to preserve volume-
  tracking continuity) during the premarket window; `PreMarketPoller` becomes sole authoritative source.
  Test: `tests/test_yfinance_premarket_arbitration.py` (3/3 passing). Not exercised live this run (run
  window never crossed 04:00–09:30 ET).
- **session="closed" rejection**: previously had no dedicated gate — a closed-session candidate could reach
  evaluation/scoring/publication on equal footing with a regular-session one. New `US_MARKET_SESSION_CLOSED`
  rejection, distinct from the unrelated `UK_SESSION_CLOSED` operator-schedule gate. Live count: **0** —
  investigated and explained (quoted): *"the last candidate-producing event ... was the ABCL
  CLOSING_BLACKOUT rejection at 2026-08-18T20:00:37Z ... zero candidates were formed at all [after that] —
  every bar ... failed the LOW_VOLATILITY bar-level gate before a candidate signal object ever existed, so
  the session gate simply never received live traffic to reject."* Classified `CLOSED_SESSION_FIX_
  CONFIRMED_WORKING` (code+test) / `NOT_EXERCISED_LIVE` (no live traffic). 3 confirming tests in
  `tests/test_quant_consumer.py`.

### D3 — Telegram `/ping` Markdown parsing failure

**Bug**: `TelegramClient.send()` hardcoded `parse_mode=Markdown` for every reply, including `/ping`'s
session-state text, which could embed a lone underscore (e.g. `pre_market`) that legacy Telegram Markdown
reads as an unterminated italic marker, causing Telegram to reject the entire message
(`"Can't parse entities: can't find end of the entity starting at byte offset 1202"`). Documented as
**Incident 001** (`reports/live_session_2026-08-18/incidents/incident_001/incident_summary.md`), failures
logged at 08:30:48Z, 09:36:35Z, 11:47:36Z UTC (all `session=pre_market`). A process restart at 11:51:36Z did
**not** fix it (`RESTART_DID_NOT_RECOVER_TELEGRAM` — the bug is content-deterministic, not process-state).
**Fix**: `TelegramClient.send()` gained an optional `parse_mode` param; `_handle_ping()` now sends with
`parse_mode=None` (plain text) via a new `_reply(text, plain=True)` helper. Verified post-fix via
reconstructed message inspection (no literal Telegram round-trip performed for this specific verification).
**Also flagged**: the Telegram bot token was accidentally exposed in plaintext during log inspection
(httpx logs full URLs at INFO); rotation recommended, not performed.
**Tests**: `tests/test_telegram_ping_safety.py` (14 tests, new file), `tests/test_telegram_listener.py`
(37 tests total, some updated for this and other D-fixes).

### D8 — Redis fail-close/reconnect

**Bug** (quoted from the module's own docstring): *"the original version left `_client=None` PERMANENTLY for
the rest of the process's lifetime after either an initial connect() failure or a runtime publish/
incr_metric exception -- there was no retry anywhere, so a Redis outage lasting even a few seconds ...
silently disabled the live event bus for the process's entire remaining lifetime, with no recovery even once
Redis came back."*
**Fix**: `RedisEventPublisher` now runs a background, bounded, jittered-backoff reconnect loop
(`_start_reconnect_loop`/`_reconnect_loop`, idempotent) triggered by both initial-connect failure and
runtime connection-level exceptions (narrowly `RedisConnectionError`/`RedisTimeoutError` only). New
in-process counters `publish_failures`/`reconnect_attempts`/`reconnect_successes`, plus Redis-backed metrics
on successful reconnect.
**Tests**: `tests/test_ingest_events_publisher_reconnect.py` (9 tests, new file).
**Live status**: `REDIS_HEALTHY_NOT_RECONNECT_TESTED` — 11 clean "Connected to Redis" lines at startup, zero
errors, reconnect logic never exercised (network never actually dropped during this run).

### Process/pipeline health, contradicted-vs-actionable, UTC metric-day, provider counters, lifecycle/watchlist telemetry

All implemented in `talonx_dispatch/telegram_listener.py`'s `/ping` handler (D2/D3/D4 sub-items in the
primary commit, plus later untracked EOD-fix-task additions):
- **Process vs. pipeline health**: replaced a hardcoded "🟢 Server Status: Active / Healthy" with separate
  `Process: RUNNING` and `Pipeline: {HEALTHY|DEGRADED|UNKNOWN}` lines, the latter derived from existing
  market-feed-freshness telemetry.
- **Contradicted vs. actionable**: `core_actionable` (sum of `action_bullish`+`action_bearish`) reported
  separately from `core_contradicted` (`action_contradicted`) — quoted code comment: *"action_contradicted
  is quant/brain DISAGREEING -- the opposite of actionable, not a third kind of actionable alert."*
- **UTC metric-day labeling**: `/ping` now states `Metrics day: {date} (UTC)` explicitly — quoted:
  *"which silently disagrees with 'today' in UK-local time for about an hour after UTC midnight (00:00-01:00
  BST) each day"* was the bug this labels around (metric keys are `metrics:{YYYY-MM-DD}:{stage}:{counter}`).
- **Provider/publish/reconnect counters**: `provider_requests_failed`, `provider_retries`,
  `provider_rate_limited`, `market_redis_publish_failures`, `market_redis_reconnect_successes` all surfaced
  in `/ping`.
- **Brain/Core lifecycle telemetry**: `quant.published` → `brain.received` → `brain.reports_generated` →
  `core.signals_received`/`core.reports_received` → `core.action_bullish`/`action_bearish`/
  `action_contradicted` → `dispatch.received` → `dispatch.muted_*` → `dispatch.pushed_telegram`, end to end.
- **Watchlist telemetry**: `_watchlist_size()` reads the real active-symbol count from
  `dispatch_agent.watchlist_store`, replacing a previously hardcoded "unknown" string (later, untracked
  EOD-fix-task addition).
- **Bar-level vs. candidate-level rejection granularity**: split `_rejected_candidates_today_count()` into a
  tuple — quoted finding: *"/ping's single 'Rejected candidates today' number was 97.8% bar-level noise
  (14331 of 14516 in the raw day total)."*

### Laptop-sleep incident — classified `HOST_SLEEP_ONLY`

Written incident analysis: `reports/live_session_2026-08-18_pre_sleep_analysis/pre_sleep_summary.md` (20
sections). Worker PID 15112 (launched 14:12:23Z): active 14:13:05Z→14:32:14Z (~19.2 min), **host-sleep
interruption 14:32:18Z→18:04:48Z (~3.53h)**, active again 18:04:48Z→18:17:22Z (~12.6 min), deliberate
shutdown 18:17:45Z. Classified `HOST_SLEEP_ONLY` on the basis of three simultaneous failure signatures at
both gap boundaries (Telegram `getUpdates` timeout, a burst of ~95–109 yfinance `'currentTradingPeriod'`/
"possibly delisted" errors across ~35 symbols simultaneously, and a Telegram `ConnectError`) — consistent
with the OS suspending, not killing, every process (all PIDs, including the Redis container, survived
unchanged, and logging resumed cleanly with no exception at the resume boundary). No dedicated crash-
watchdog mechanism or `HOST_SLEEP_ONLY` constant exists in the codebase — this is a report-only
classification label based on log-pattern analysis, not a code-level flag. Restart to a fresh worker (PID
22932) was performed by explicit user request to eliminate stale-connection-state uncertainty, not because
anything was found broken. A second accidental plaintext Telegram-token exposure was also flagged during
this incident's log review (rotation recommended, not performed).

**NOT FOUND**: no reference to a "native crash 2026-08-13" exists anywhere in this repository's code,
docs, or reports — that appears to be an external reference (e.g. a separate memory note) not present in
this codebase.

### Later healthy, uninterrupted EOD run

Restarted worker (PID 22932), **2026-08-18T18:17:55Z – 21:47:08Z, 3h29m13s, entirely continuous with no
host sleep** — quoted: *"HEALTHY. No application errors, no worker crashes, no Redis/Telegram failures, no
unhandled exceptions anywhere in the 3h29m segment."* Gap-scan of the log found no interruption over 121
seconds (three trivial 121s quiet intervals only). Activity: 4 candidates (2 `LOW_CONFLUENCE`, 2
`CLOSING_BLACKOUT`), 0 published. CPU median 3.9% (max 35.4%); RSS grew +59.3MB (+6.85%) non-monotonically
over the session, classified `STABLE`. Focused test run covering all touched modules:
`tests/test_telegram_listener.py tests/test_telegram_ping_safety.py tests/test_quant_consumer.py
tests/test_yfinance_poller.py tests/test_yfinance_premarket_arbitration.py
tests/test_ingest_events_publisher.py tests/test_ingest_events_publisher_reconnect.py` → **257 passed**.
Full suite (1,500+ tests) explicitly not run.

(No `reports/eod_2026-08-11*` folder exists in the current working tree — not found during this backfill.)

### Remaining observability gaps

From `reports/live_session_2026-08-18_eod_analysis/eod_summary.md` §17 (the explicit itemized list; this
lives in an untracked report, not `docs/`):

| Gap | Status |
|---|---|
| Watchlist size unknown | Fixed during the EOD-fix task |
| `/ping`'s "Rejected candidates" mixed bar/candidate granularity | Fixed during the EOD-fix task |
| Feed errors unknown | `VALID_OBSERVABILITY_GAP` — *"No existing counter; out of narrow-fix scope."* |
| Brain reports generated unknown | `VALID_OBSERVABILITY_GAP` — *"fallback-report paths generate a report without incrementing [`llm_calls`], would silently undercount"* |
| Core research reports received unknown | `VALID_OBSERVABILITY_GAP` — *"`core_correlated` genuinely conflates two event types at the source; no existing counter to reuse"* |

Overall readiness label for this session: `READY_FOR_TASK_13_WITH_OBSERVABILITY_GAPS`. `docs/roadmap.md`
separately notes (as of this backfill) that structured JSON logging covers only new long-term code paths,
not a retrofit of ~15 pre-existing intraday log call sites (deliberately deferred); the Streamlit dashboard
has no authentication; and the 1-minute buffer allow-list/bar-buffer persistence has no symbol-eviction
logic.

### Focused test counts (this section's modules)

| Test file | `def test_` count |
|---|---:|
| `tests/test_telegram_ping_safety.py` | 14 |
| `tests/test_telegram_listener.py` | 37 |
| `tests/test_ingest_events_publisher_reconnect.py` | 9 |
| `tests/test_ingest_events_publisher.py` | 7 |
| `tests/test_yfinance_premarket_arbitration.py` | 3 |
| `tests/test_yfinance_poller.py` | 27 |
| `tests/test_quant_consumer.py` | 155 |
| `tests/test_brain_consumer.py` | 49 |
| `tests/test_core_consumer.py` | 28 |

### Evidence
`talonx_dispatch/telegram_client.py`, `talonx_dispatch/telegram_listener.py`, `talonx_quant/consumer.py`,
`talonx_ingest/events/publisher.py`, `talonx_ingest/market_data/yfinance_poll.py` (all modified in commit
`0682693`); `reports/live_session_2026-08-18/` (incl. `incidents/incident_001/`),
`reports/live_session_2026-08-18_post_fix/`, `reports/live_session_2026-08-18_pre_sleep_analysis/`,
`reports/live_session_2026-08-18_eod_analysis/` (all untracked, `.gitignore`d, exist only locally); test
files listed above. `git status --short` at the time of this backfill shows only `docs/research/`, `logs/`,
`research/` as untracked top-level paths — every `reports/live_session_2026-08-18*` directory is fully
untracked (0 files under `git ls-files reports/`).
## Task 13 — ATR Threshold Experiment

### Objective
Determine whether lowering the strategy's `min_atr_pct` volatility gate from the 0.25% research baseline
(Task 8) to 0.20% or 0.15% produces a better-performing, broader-participation trade population, using a
full-year, 10-symbol, zero-cost backtest.

### Hypothesis / Expected Behaviour
A looser (lower) ATR% gate should admit more candidates, including mega-cap symbols that rarely clear
0.25%, and was expected (per Task 12's threshold-grid finding) to structurally improve mega-cap
accessibility — but accessibility was not assumed to imply profitability.

### Inputs
- Dataset: `data/historical_1m/task7b_alpaca_long_history/`, hash `5e5412a960bf`
- Symbols: AAPL, MSFT, NVDA, AMZN, META, AMD, TSLA, GOOGL, PYPL, STX
- Range: 2025-08-15 13:03 UTC → 2026-08-14 23:58 UTC (1,901,714 bars/run)
- Checkpoint commit: `0682693` (`research/talonx-strategy-validation`)
- `strategy_version=88529b8a3fa1` for both new runs; 0.25% baseline (Task 8) reused unmodified, not rerun —
  verified byte-identical for the 5 functions the backtester actually imports from `consumer.py`
  (`_fails_min_volatility`, `_opportunity_score`, `_partition`, `_trend_gate_applicable`, `_GATE_NAMES`)
  despite a differing whole-file `strategy_version` hash

### Work Performed
Two new full-year backtests at `min_atr_pct=0.20%` and `0.15%`, zero transaction cost, compared against the
existing 0.25% baseline. Funnel/rejection-reason analysis, symbol concentration analysis, an incremental-
population analysis (matching trades by symbol+direction+signal_timestamp across the three thresholds to
isolate what each further loosening step actually adds), exit-path/R:R analysis, long/short split, monthly
and 4-window subperiod stability, drawdown/risk analysis, and a fixed-seed (42) 10,000-resample bootstrap CI
on expectancy.

### Validation
- No duplicate/out-of-order/NaN/Inf data, no future timestamps, no look-ahead (entry always ≥ signal time)
- Funnel fully reconciles (evaluated = published + candidate-level rejections, exactly, all three runs)
- Equity curve reconciles with the trade ledger exactly
- All 10 symbols present with clean data quality at every threshold

### Results
| Metric | 0.25 (baseline) | 0.20 | 0.15 |
|---|---|---|---|
| Trades | 93 | 181 | 375 |
| Win rate | 19.35% | 22.65% | 18.40% |
| Total R | −13.24 | +41.79¹ | +42.73¹ |
| Expectancy | −0.1424 | +0.2309 | +0.1139 |
| Profit factor | 0.821 | 1.302 | 1.141 |
| Max drawdown | −20.76 | −25.11 | −41.75 |

¹ Includes the defect described below: +3.0R (0.20) / +6.0R (0.15) of this total came from mislabeled trades.

Incremental populations (central finding): the 90 trades newly unlocked by 0.25→0.20 were genuinely
higher-quality than the 0.25 core (PF 1.80, expectancy +0.589) — but the further 205 trades unlocked by
0.20→0.15 were **net losing** (PF 0.95, expectancy −0.040), a non-monotonic "quality elbow." Bootstrap 95%
CI (seed 42, n=10,000) on expectancy included zero at all three thresholds (0.25: [−0.532, +0.313]; 0.20:
[−0.236, +0.814]; 0.15: [−0.228, +0.503]) — none statistically distinguishable from zero. Mega-cap
accessibility improved as Task 12 predicted, but every mega-cap that traded still lost money at every
threshold. Confluence score was exactly 2 for every executed trade at every threshold. STX/AMD remained the
dominant profit drivers; trade-count concentration eased (top-1 share 57%→41%) but R-concentration did not
(STX = 102% of 0.15%'s total positive R). Max drawdown worsened monotonically as threshold lowered
(−20.76→−25.11→−41.75) even as total R improved.

### Defects / Anomalies
**Discovered a pre-existing execution-geometry defect** (not introduced by this experiment): a small number
of trades had their stop level land on the wrong side of the actual fill price, because the engine computed
stop/target from the signal bar's *close* but filled at the next bar's *open*, and `execution.py`'s risk
calculation via `abs()` silently tolerated the mismatch. Always manifested as `exit_reason=STOP` with
`net_R=+1.0` exactly. Rate: 0.25 → 0/93 (0%); 0.20 → 3/181 (1.66%, +3.0R); 0.15 → 6/375 (1.60%, +6.0R). Per
user decision, the task proceeded with the contaminated data, with every affected metric flagged.

### Changes Made
None — this was a research/measurement task; the defect was documented for a follow-on fix, not corrected
in place.

### Conclusion
Neither 0.20% nor 0.15% cleared a bar for confident promotion at the time: the improvement was real in this
historical draw but not statistically distinguishable from zero, partly inflated by the known defect, and
not monotonic across the two thresholds (0.25→0.20 clean, 0.20→0.15 net-losing). 0.25→0.20's incremental
result was strong enough that outright dismissal of both new thresholds would also have been premature.

### Limitations
Does not prove 0.15%/0.20% are better thresholds (CIs include zero); does not prove monotonic improvement;
does not prove mega-cap accessibility is exploitable; zero-cost/no-slippage baseline only, no cost
sensitivity run; trade-level R-multiple analysis only, no portfolio/position-sizing/concurrent-exposure
modeling. Several symbols (AMZN, GOOGL, MSFT, META) had single-digit-to-low-double-digit trade counts even
at 0.15% — their per-symbol PF/win-rate figures are explicitly flagged as unreliable.

### Decision
**`RUN_FURTHER_CONTROLLED_VALIDATION_BEFORE_DECISION`**

### Next Step
Fix the stop/target-side engine defect first, then rerun 0.20% alone (the stronger, more evenly-distributed
candidate of the two) with the corrected engine, before any cost-sensitivity work. → became Task 13B.

### Evidence
`results/task13_atr_threshold_experiment/task13_summary.md`, `task13_summary.json`,
`task13_bootstrap_ci.csv`, `task13_concentration.csv`, `task13_drawdown_quality.csv`, `task13_elasticity.csv`,
`task13_exit_path_analysis.csv`, `task13_incremental_trades.csv`, `task13_long_vs_short.csv`,
`task13_megacap_accessibility.csv`, `task13_monthly_comparison.csv`, `task13_rejection_comparison.csv`,
`task13_rr_analysis.csv`, `task13_run_manifests.json`, `task13_sanity_checks.json`,
`task13_subperiod_comparison.csv`, `task13_symbol_comparison.csv`, `task13_threshold_comparison.csv`,
`task13_trade_overlap_summary.json`; raw run outputs `results/task13_atr_015/`, `results/task13_atr_020/`.

---

## Task 13B — Execution Geometry Fix

### Objective
Fix the stop/target-side execution defect Task 13 discovered, then rerun 0.20%/0.15% from the corrected,
identical source state to get a clean read on whether the positive result survives without artifact
contamination.

### Hypothesis / Expected Behaviour
Re-anchoring stop/target geometry to the real fill price (only when the pre-existing geometry has already
been invalidated by that fill) should eliminate the always-`net_R=+1.0`-mislabeled-STOP pattern without
otherwise disturbing unaffected trades.

### Inputs
- Same dataset/symbols/range as Task 13, hash `5e5412a960bf`
- `git_commit=2a5e8855ecf0c337db755577909c74923cb6c2c1`, `strategy_version=88529b8a3fa1` (unchanged from
  Task 13 — `engine.py` is not part of that fingerprint, confirming zero strategy drift from the fix)
- Runtime: 0.20% fixed = 23,674.3s (~6h35m); 0.15% fixed = 17,789.2s (~4h56m); 0.25% not rerun (see below)

### Work Performed
**Root cause**: `BacktestEngine` computed each trade's stop/target from the signal bar's **close** (at
`_revalidate`, throttle-flush time), but the actual fill happens at the **next bar's open** — a deliberate,
documented one-bar entry-lag convention. `execution.py`'s risk calculation, `risk = abs(entry_price_raw -
stop_price)`, silently tolerated the case where a real price gap between those two bars left the
pre-computed stop on the wrong side of the actual fill.

**Fix chosen**: recompute geometry anchored to the real fill price, using the exact same
`calculate_trade_geometry` function `_revalidate` already calls — but only when the pre-existing stop/target
has already been invalidated by the fill price. New `BacktestEngine._finalize_fill_geometry`, wired into
`_process_symbol_bar` immediately before `open_position` (`talonx_backtest/engine.py`, +67/−8 lines).
`screening_rr` is never overwritten by the fix — it remains the strategy's gate-time R:R by explicit project
contract; only `execution_rr` reflects the real fill geometry.

Verified the fix reproduces all 6 originally-flagged trades' identical broken pattern before the fix, then
confirms all 9 total changed trades (3 at 0.20%, 6 at 0.15%) are correctly re-geometrized after.

Verified the 0.25% baseline did **not** need a rerun: confirmed 0/93 Task 8 trades had invalidated stop
geometry — since the fix is a strict no-op whenever geometry is already valid, the fixed engine reproduces
Task 8 byte-identically.

### Validation
9 new focused tests in `tests/test_backtest_fill_geometry.py` (LONG/SHORT gap-through-stop recompute +
invariant check, normal fills left untouched both directions, severe-gap rejection via
`GEOMETRY_INVALIDATED_AT_FILL`, missing-stop/target passthrough, `screening_rr` never overwritten, an
end-to-end check that no `STOP` exit can produce `net_R=+1.0`) — **9/9 passed**. Plus a targeted (not full
suite) run of `test_backtest_execution.py`, `test_backtest_engine_state.py`, `test_backtest_regression.py`,
`test_backtest_lookahead.py`, `test_backtest_metrics.py`, `test_backtest_research_telemetry.py`,
`test_backtest_reproducibility.py`, `test_backtest_htf_aggregation.py`, `test_backtest_timezone.py` — 131
passed, 0 failed, 0 regressions. Full pytest suite explicitly **not** run, per policy.

### Results
| | 0.20 original | 0.20 fixed | 0.15 original | 0.15 fixed |
|---|---|---|---|---|
| Trades | 181 | 181 | 375 | 375 |
| Win rate | 22.65% | 22.10% | 18.40% | 17.60% |
| Total R | +41.79 | **+75.98** | +42.73 | **+76.21** |
| Expectancy | +0.231 | +0.420 | +0.114 | +0.203 |
| Profit factor | 1.30 | **1.54** | 1.14 | 1.25 |
| Max drawdown | −25.11 | −20.00 | −41.75 | −34.83 |

No trades were added or removed by the fix at either threshold — all 9 affected trades were re-geometrized,
none rejected outright. Incremental-population re-check: 0.25→0.20's new-trade set improved from PF 1.80
(artifact-contaminated) to **PF 2.29** (fixed) — stronger evidence the increment is genuinely high quality.
0.20→0.15's new-trade set stayed essentially unchanged and still net-losing (PF 0.95 both before and after)
— **the non-monotonic elbow between 0.20 and 0.15 is confirmed, not an artifact of the defect.** Recomputed
bootstrap 95% CI: 0.20's interval moved substantially away from zero ([−0.141, +1.110], point estimate
nearly doubled to +0.420) though still technically includes zero.

### Defects / Anomalies
None found specific to this fix beyond the one being corrected. The pre-existing `published − executed` gap
(5 at 0.20, 20 at 0.15, from `has_open()`/overlap-blocking behavior) is unchanged and was explicitly out of
scope. Zero new `GEOMETRY_INVALIDATED_AT_FILL` rejections occurred in either historical run — the fix's
fail-closed reject path was never exercised on real data, only its recompute path was.

### Changes Made
`talonx_backtest/engine.py`: new `BacktestEngine._finalize_fill_geometry` method (+67/−8 lines).
`tests/test_backtest_fill_geometry.py` (new file): 9 focused tests.

### Conclusion
**`TASK13_CONCLUSION_CONFIRMED`** — Task 13's central finding (0.25→0.20 increment is high quality, the
further 0.20→0.15 increment is not, neither threshold's edge is statistically distinguishable from zero)
survives the fix intact and is strengthened for the 0.20 case specifically.

### Limitations
Statistical significance still cannot be claimed (CIs still include zero at all three thresholds). This
task did not run cost sensitivity (explicitly deferred).

### Decision
Fix validated and adopted; proceed to independent trade-level audit of the changed trades before trusting
the corrected numbers for cost-sensitivity work.

### Next Step
Cost-sensitivity analysis on 0.20% only, using the now execution-clean data — but first, an independent
audit of the 9 changed trades against raw bars. → became Task 13C, then Task 14.

### Evidence
`results/task13b_execution_fix_validation/task13b_summary.md`, `task13b_before_after.csv`,
`task13b_bootstrap_ci.csv`, `task13b_changed_trades.csv`, `task13b_concentration.csv`,
`task13b_incremental_trades.csv`, `task13b_monthly_comparison.csv`, `task13b_run_manifests.json`,
`task13b_subperiod_comparison.csv`, `task13b_summary.json`, `task13b_symbol_comparison.csv`,
`task13b_threshold_comparison.csv`; corrected run outputs `results/task13b_atr_020_fixed/`,
`results/task13b_atr_015_fixed/`; code `talonx_backtest/engine.py`; tests
`tests/test_backtest_fill_geometry.py` (9/9 passing).

---

## Task 13C — Execution Realism Audit

### Objective
Independently validate the 9 Task 13B trades changed by the fill-geometry fix directly against raw 1-minute
bars, before trusting the corrected numbers for expensive cost-sensitivity work.

### Hypothesis / Expected Behaviour
The fix should be geometrically self-consistent and free of look-ahead; the specific outlier trades (STX
+30.27R, PYPL +7.92R/+4.30R) needed direct verification that fills, exits, and R calculations were real and
achievable from the historical tape, not artifacts of the fix or of the underlying (known-sparse)
after-hours data.

### Inputs
Same dataset/hash (`5e5412a960bf`), same commit (`2a5e885`); the 9-row
`results/task13b_execution_fix_validation/task13b_changed_trades.csv` (6 unique trades at one or both
thresholds) plus direct reads of `data/historical_1m/task7b_alpaca_long_history/{SYMBOL}.csv`.

### Work Performed
For each of the 6 unique trades: extracted signal/entry/exit bar OHLC directly from raw data (not just the
generated trade CSV), independently verified the LONG/SHORT geometry invariant, independently reconstructed
ATR-based stop/target using `1.5×ATR` and reproduced the S1/R1 structural pivot targets from the prior
completed session's H/L/C by hand, walked every bar from entry to exit to confirm target-hit sequencing and
that stop was never crossed first, independently recomputed realized R from raw fill/exit prices, and did a
deep dive on the most extreme case (STX bearish, signal 2026-03-24 22:40 UTC, entry 22:47 UTC, +30.27R).

### Validation
Independent recomputation of stop distance (`entry ± 1.5×ATR`) and pivot targets matched the stored ledger
values to floating-point precision (e.g. STX prior-session pivot: H425.18/L395.1866/C404.00 → S1=391.0644,
exact match). R reconciliation matched stored `net_R` to ~1e-5 relative (explained by CSV display-precision
rounding). Ran only the focused `tests/test_backtest_fill_geometry.py` (9/9 passing) — no full suite, no
replay.

### Results
All 6 trades' fixed geometry independently confirmed valid (target < entry < stop or stop < entry < target
as appropriate). The STX +30.27R entry timing (7 minutes after signal) was traced to a genuine data gap —
no STX bars exist for 22:41–22:46 in the raw CSV, not a code-skip or look-ahead artifact; both bracketing
bars were thin single-print prints (117 and 1,300 shares) in the after-hours `closed` session. Target/stop
were not crossed on the visible tape before entry. All target hits were confirmed as the true first
crossing on a full bar-by-bar walk; none of the 9 changed trades actually exercised the `stop_first`
same-bar ambiguity rule. All 6 changed trades were found to cluster in the thin, single-print after-hours
`closed` session (0/9 rows were regular-session trades).

### Defects / Anomalies
No engine defects found. Flagged (not a defect, an execution-realism **caveat**): the after-hours session
this changed-trade population clusters in is structurally thin (62% of STX `closed`-session bars are flat
single prints vs. 1.7% in regular hours; median closed-session volume 285 vs. 5,948 regular) — real-world
slippage/fill-size risk on these single-print fills cannot be proven or disproven from 1-minute OHLCV alone.

### Changes Made
None — audit only.

### Conclusion
**`EXECUTION_FIX_VALIDATED_WITH_CAVEATS`** — the fix is correct and narrowly scoped exactly as documented;
all 9 changed trades independently reconstruct correctly from raw bars with no look-ahead. The caveat is
entirely about the underlying after-hours liquidity the whole changed-trade population sits in, not about
any defect in the fix.

### Limitations
Cannot prove or disprove real-world fill executability at size from 1-minute OHLCV data alone — this is an
inherent limitation of the data source, stated explicitly, not resolved by this or any later task.

### Decision
Proceed to Task 14 (0.20% cost sensitivity) with a note to review after-hours-session trades separately from
regular-session ones.

### Next Step
Task 14: full-year 0/5/10/20bps cost-sensitivity replays at 0.20%.

### Evidence
`results/task13b_execution_fix_validation/task13b_changed_trades.csv`; raw data
`data/historical_1m/task7b_alpaca_long_history/STX.csv`, `PYPL.csv`; focused test run
`tests/test_backtest_fill_geometry.py` (9/9 passing); full audit detail was delivered as an Artifact in-
conversation (not persisted to `results/` as a task-numbered directory — this task predates the
`research/scripts/` + `results/task*` convention established from Task 15 onward).

---

## Task 14 — Cost Sensitivity + After-Hours Attribution

### Objective
Evaluate whether the corrected 0.20% result survives realistic transaction costs, and quantify how
dependent the result is on the thin after-hours trades Task 13C identified.

### Hypothesis / Expected Behaviour
Given Task 13C's after-hours caveat, expected after-hours trades might disproportionately drive both the
edge and its cost sensitivity — tested directly rather than assumed.

### Inputs
- Same dataset/hash (`5e5412a960bf`), symbols, and range as Task 13/13B
- `git_commit=2a5e8855ecf0c337db755577909c74923cb6c2c1`, `strategy_version=88529b8a3fa1` reconfirmed;
  `config_hash=ec525d379860` for the 0bps execution config, independently reproduced and matched the Task
  13B reference exactly — 0bps result **reused, not rerun**
- 5bps/10bps/20bps: three independent full-year replays (`--entry-slippage-bps X --exit-slippage-bps X
  --spread-bps X`, mirroring `talonx_backtest.analysis.cost_sensitivity_scenarios`'s own per-scenario
  mapping), run in parallel in the background

### Work Performed
Full-year replays at 5/10/20bps; per-scenario sanity checks (dataset hash, effective ATR threshold, no
look-ahead, no invalid-STOP+1R artifact, geometry invariant, ledger reconciliation); headline cost
comparison; trade-set divergence check across all cost-pair comparisons; symbol-level cost sensitivity
(STX/AMD/PYPL highlighted); session attribution (REGULAR/PREMARKET/16:00-auction-boundary/POST_MARKET_
CLOSED, explicitly *not* conflating the 16:00 ET closing-auction print with genuine thin post-market
liquidity); after-hours liquidity characteristics; large-winner concentration (top-1/3/5); a dedicated deep
dive reconstructing the STX +30.27R trade's cost sensitivity specifically; exit-path cost sensitivity;
long/short split; monthly and 4-window subperiod analysis; cost elasticity (linear vs. nonlinear check); a
fixed-seed (42, n=10,000) bootstrap CI per cost scenario.

### Validation
All sanity checks passed at every scenario. An unanticipated discovery mid-task: found and traced a single
STX trade (`STX-2026-07-30 22:29`) whose net_R swung from −1.0 (0bps) to −28.08 (5bps) — hand-verified the
exact cost arithmetic against `execution.py`'s documented formula to the cent, confirming it was mechanically
correct (not a bug), driven by a razor-thin ATR-based risk denominator (0.0055% of price) — flagged for
dedicated follow-up (became Task 15).

### Results
| | 0bps | 5bps | 10bps | 20bps |
|---|---|---|---|---|
| Trades | 181 | 181 | 181 | 181 |
| Total R | **+75.98** | **−21.41** | **−118.80** | **−313.58** |
| Expectancy | +0.420 | −0.118 | −0.656 | −1.732 |
| Profit factor | 1.545 | 0.903 | 0.608 | 0.331 |

After-hours entries were 14.9% of trades but 34.7% of 0bps total R — disproportionate, but excluding them
entirely did not rescue the strategy: regular-session-only trades also went net-negative starting at 5bps
(+49.62 → −10.27). The STX +30.27R trade itself proved cost-**robust** (30.27 → 28.46 at 20bps, only ~6%
relative decline) — its risk denominator was normal-sized (0.32% of price), unlike the newly-discovered
STX 7/30 outlier. Bootstrap 95% CI: only 20bps was statistically distinct from zero (and negative);
0/5/10bps all straddled zero, including the original 0bps "edge."

### Defects / Anomalies
No engine defects. The STX 7/30 outlier (see Work Performed) was confirmed as a legitimate, if extreme,
consequence of the frozen ATR-based risk-sizing formula interacting with a real price gap — not a bug.

### Changes Made
None — measurement only.

### Conclusion
**`EDGE_ERASED_BY_REALISTIC_COSTS`** — total R, expectancy, and PF were all sub-breakeven at every tested
non-zero cost level; the 0bps result itself was never statistically distinct from zero. Not a broad-based
linear cost drag: 3 of 9 traded symbols (STX/AMD/PYPL) carried the entire positive-edge story, and a
razor-thin ATR-based risk denominator turned ordinary flat-bps costs into R-multiple blowouts on a specific
trade cluster.

### Limitations
What these replays prove: given the frozen strategy's ATR-based risk sizing exactly as coded, flat 5–20bps
costs erase the reported edge, unevenly. What they cannot prove: whether the after-hours single-print fills
were executable at size, or whether a risk-sizing floor would have prevented the thin-risk pathology from
ever being taken.

### Decision
`EDGE_ERASED_BY_REALISTIC_COSTS`. Recommended next: a risk-sizing floor/sanity **audit** (diagnostic only,
no strategy change).

### Next Step
Task 15: quantify how often the frozen ATR-stop formula produces a risk distance under some threshold, and
whether that predicts the cost-fragility found here.

### Evidence
`results/task14_cost_sensitivity/` (task14_summary.md/json + 15 CSVs), `results/task14_cost_005/`,
`results/task14_cost_010/`, `results/task14_cost_020/` (raw replay outputs),
`results/task13b_atr_020_fixed/` (reused 0bps reference).

---

## Task 15 — Risk-Distance & Cost-to-Risk Diagnostic Audit

**Date:** 2026-08-20
**Objective:** Determine whether the 0.20% strategy's cost fragility (Task 14) comes from (A) broadly tiny
stop/risk distances across most trades, or (B) a small pathological tail of near-zero-risk-denominator
trades.
**Hypothesis:** Going in, favored (B) based on Task 14's single-trade discovery, but not yet quantified
across the full population.

**Dataset/hash:** `data/historical_1m/task7b_alpaca_long_history/`, hash `5e5412a960bf` (reproduced
independently, matched).
**Fingerprints:** `git_commit 2a5e8855ecf0c337db755577909c74923cb6c2c1`, `strategy_version 88529b8a3fa1`. No
replay performed — built entirely from existing Task 13B (0bps) + Task 14 (5/10/20bps) trade ledgers.

**Tests performed:** Per-trade `risk_pct` and `cost_to_risk` (exact, from ledger `gross_pnl`/`net_pnl`, no
approximation) across all 181 trades; fixed-bucket distributions; independent re-derivation of the "fragile
cluster" (not assumed from Task 14); hand reconstruction of the most extreme trade
(`STX-2026-07-30 22:29:00+00:00`) against raw bars; a geometry-based root-cause classification
(SMALL_ATR / FILL_NEAR_STOP / BOTH / OTHER) using thresholds fixed *before* inspecting profitability;
descriptive-only cutoff diagnostics; Pearson/Spearman correlations.

**Results:**
- `risk_pct`: min 0.0055%, P1 0.149%, median 0.383% — the minimum is 27x smaller than P1, an isolated
  extreme, not a graded tail.
- Fragile cluster @5bps: `cost_to_risk≥0.5` → 17 trades (independently reproduces Task 14's own 17-trade
  figure via a different method). `≥1.0` → 2 trades, both STX, both after-hours.
- Root cause: `intended_risk_from_entry_pct` (1.5×ATR/price) **never drops below 0.30%** across all 181
  trades — ATR is never the driver. All 17 fragile trades are `FILL_NEAR_STOP` (stale, signal-anchored stop
  that the fill gapped toward without crossing); zero are `SMALL_ATR`.
- Counterintuitive: the 17-trade FILL_NEAR_STOP cluster is net *positive* through 5bps (+7.34R — contains 4
  large winners alongside 13 losers). The 164-trade "normal" population is what drives the initial 0→5bps
  sign flip on its own (-28.76R), because the whole book's median cost-to-risk is already 0.39 at 5bps.
- `cost_to_risk_5bps` vs. deterioration: r=1.000 — flagged explicitly as a **mathematical identity**, not an
  empirical finding.

**Defects/anomalies:** None found in engine correctness (no NaN/Inf, no look-ahead, no invalid-STOP+1R
artifact, geometry invariant holds, ledgers reconcile). The FILL_NEAR_STOP mechanism is an intentional,
documented scope boundary of the Task 13B fix (it only repairs geometrically *invalid* fills), not a defect.

**Conclusions:** Neither pure "broad" nor pure "tail" explanation fits alone — both effects are real and
simultaneously necessary. **Classification: `STRATEGY_RISK_MODEL_ISSUE`** (not an engine defect, not a pure
market-data artifact).

**Limitations:** Diagnostic only, no strategy or replay changes; cutoff diagnostics are descriptive slices,
not valid backtests; the `cost_to_risk` vs. deterioration correlation is tautological and must not be read as
an empirical discovery.

**Decision:** `MIXED_CAUSES`

**Next experiment (recommended, not started):** a diagnostic-only comparison of two candidate revalidation
rules — (1) erosion-ratio floor at fill time, (2) risk-to-transaction-cost floor — scored only against the
17-trade FILL_NEAR_STOP cluster, before any change is proposed to production defaults. → carried out as
Task 16 below.

---

## Task 16 — Entry Risk Preservation & Cost Viability Audit

**Date:** 2026-08-20
**Objective:** Determine whether an entry-time risk-sanity mechanism could address the pathological
fill-near-stop cases found in Task 15, and whether doing so would materially improve broader cost
robustness.
**Hypothesis:** Given Task 15's finding that the 164-trade "normal" population is independently cost-fragile,
expected that fixing only the pathological tail would not restore durable edge at realistic cost levels.

**Dataset/hash:** same as Task 15 — `5e5412a960bf`, reused, no replay. `git_commit
2a5e8855ecf0c337db755577909c74923cb6c2c1` reconfirmed.

**Tests performed:** `risk_preservation_ratio = actual_fill_risk / intended_risk` (= Task 15's `erosion_ratio`,
renamed per this task's terminology; `fill_price` = `entry_price` in this engine — see `execution.py`'s
`OpenPosition`/`Trade` model) and `risk_erosion_ratio = 1 - preservation`, both re-derived and cross-checked
against Task 15's own `erosion_ratio` column. Fixed-bucket distributions; cross-tab of preservation ratio vs.
`cost_to_risk_5bps`; two hypothetical, NOT-implemented exclusion rules (Rule A: preservation floor at
10/25/50/75%; Rule B: cost-to-risk ceiling at 0.25/0.5/1.0/2.0R) evaluated as descriptive slices only; a
mandatory broad-edge check on the best-case tail exclusions; symbol/session decomposition; fill-movement
analysis (signal→fill price move and delay) with correlation to preservation ratio.

**Results:**
- Preservation ratio: median ≈100.00%, P25 94.9%, min 1.66% (the STX 7/30 trade). 152/181 trades (84%) sit
  at ≥90% preservation; only 4 trades (2.2%) are below 50%, all STX.
- Cross-tab: the single most extreme cost/risk case (`>2R`) is also the single most eroded case (`<10%`
  preservation) — but the relationship is not 1:1: several trades sit in the elevated `0.50-1R` cost/risk
  bucket with *normal* (75-100%) preservation (naturally tight ATR, not erosion), and several moderately
  eroded trades (25-75% preservation) remain in *moderate* (`0.25-0.50R`) cost/risk buckets. The two
  diagnostics measure related but distinct things: preservation is purely geometric/causal, cost-to-risk is
  economic and also reflects the trade's absolute (intended) risk size.
- Rule comparison: Rule B at 1.0R excludes exactly the 2 known-pathological trades with zero collateral
  damage. Rule A needs a 50% floor to catch both (STX 2025-11-20's preservation is 26.7%, above a 25% floor)
  and at that level also excludes 2 additional non-pathological trades. **Rule B is more surgically precise
  and more economically interpretable; Rule A is more directly tied to the measured causal mechanism
  (erosion) but less precise.**
- **Mandatory broad-edge check:** excluding just the 2 known-pathological trades (or equivalently, Rule B at
  1.0R) → 5bps: total R +8.82, expectancy +0.049, **PF 1.046** (all three of positive-expectancy/PF>1/
  positive-total-R are technically satisfied) — but 10bps remains **-60.33R**, decisively negative. The
  "restoration" at 5bps is real but marginal (PF barely above 1.0, on a population whose 0bps result was
  itself not statistically distinct from zero per Task 14's bootstrap CI) and does not extend to 10bps or
  20bps under any tested exclusion rule.
- Symbol: all 4 severely-eroded (<50% preservation) trades are STX; AMD/PYPL/other symbols show similar
  median preservation (~100%) and similar median cost-to-risk (~0.39-0.46 at 5bps) but zero severe erosion —
  STX-specific, not broad.
- Session: `POST_MARKET_CLOSED` has the lowest P10 preservation (71.7% vs. `REGULAR`'s 88.7%) — after-hours
  shows more erosion at the tail, though median preservation stays high (98.7%) even there.
- Fill movement: median signal→fill delay is 1 minute (P90 also 1 minute; only P99 reaches 5.4 minutes) —
  multi-minute gaps are rare, not typical. Median adverse move is 0.0% (most fills land almost exactly at
  the signal price); the erosion tail comes entirely from the P1-P5 adverse-move tail (down to -0.64%).
  Adverse move vs. preservation ratio: Pearson r=-0.757, Spearman r=-0.969 — a strong, genuine (non-tautological)
  empirical relationship.

**Defects/anomalies:** None new. Consistent with Task 15's `STRATEGY_RISK_MODEL_ISSUE` finding.

**Conclusions:** A pathological-tail fix (either rule, at a precise cutoff) can restore a *marginal* positive
edge at the lowest tested cost tier (5bps) but does not restore a *durable* edge across the realistic cost
range already tested in Task 14 (10-20bps remain solidly negative under every exclusion evaluated). This
confirms and sharpens Task 15's `MIXED_CAUSES` finding rather than reversing it.

**Previous conclusion (Task 15):** `MIXED_CAUSES` — broad and tail effects both real and necessary.
**New evidence (Task 16):** quantified that the *best possible* tail-only fix restores only a marginal
(PF≈1.05) edge at 5bps and none at 10bps+, directly measuring how much of Task 15's "broad" component
survives after removing the "tail" component precisely.
**Updated conclusion:** `TAIL_FIX_ALONE_DOES_NOT_RESTORE_EDGE` — consistent with, not a reversal of, Task 15.

**Limitations:** All rule evaluations are descriptive/diagnostic slices, not valid backtests — none was
selected as a production threshold, and none was implemented. `fill_price` was treated as identical to
`entry_price`, matching this engine's own model, not an approximation introduced by this task.

**Decision:** `TAIL_FIX_ALONE_DOES_NOT_RESTORE_EDGE`

**Next experiment (recommended, not started):** see `results/task16_entry_risk_audit/task16_summary.md`
§13 — a controlled, diagnostic-only test of whether a *combined* signal-quality condition (e.g. requiring
both adequate preservation AND adequate cost/risk) explains more of the 164-trade "normal" population's own
cost fragility than either single-cause diagnostic alone, since Task 16 shows neither mechanism in isolation
accounts for the broad component.

---

## Task 17 — Gross Edge Attribution & Stability Audit

**Date:** 2026-08-20
**Objective:** Determine where the corrected 0.20% strategy's GROSS (0bps) trading edge actually comes from
— broad across trades, or concentrated in particular symbols/setups/regimes — and whether any winner/loser
characteristic is stable across chronological subperiods, before introducing any new entry filter.
**Hypothesis:** Given Task 15/16's symbol-concentration findings (STX carrying most of the thin-risk tail),
expected gross edge to also show meaningful symbol concentration, though the degree was not yet quantified
at the gross (pre-cost) level.

**Dataset/hash:** same 181-trade population, `5e5412a960bf`, reused — no replay. `git_commit
2a5e8855ecf0c337db755577909c74923cb6c2c1` reconfirmed. Built from Task 13B's `trades.csv` (confluence,
screening/execution R:R, volume_surge_ratio, trend_alignment, MFE/MAE) joined to Task 15's risk-geometry
table (risk_pct, preservation ratio, session) — `gross_edge_margin_5bps` reconciled to Task 14's `net_R_5bps`
to floating-point precision (2.8e-17).

**Tests performed:** WINNER/LOSER/BREAKEVEN classification from gross_R (no outcome-derived rule invented);
winner-vs-loser distributional comparison across 10 continuous + 5 categorical attributes; symbol
attribution (share of gross positive R / share of gross losses); concentration views (excluding top-N
winners, excluding symbol combinations); confluence-score variation check; Spearman correlation of
screening_rr/execution_rr/ATR%/risk_pct/volume_surge_ratio against gross_R and 5bps R; volume quartile
analysis; exit-reason and holding-time-quartile attribution; the same relationships repeated independently
in each of the four Task-13 subperiods with an explicit STABLE/WEAK/REGIME_DEPENDENT/CONTRADICTORY/
INSUFFICIENT_SAMPLE classification; a leave-one-period-out directional-validation check (fit direction on
3 periods, verify same sign in the 4th, held-out period) for every relationship tested.

**Results:**
- Confluence: confirmed unchanged — all 181 trades carry confluence_score=2 exactly, no variation, cannot
  explain any quality difference (matches Task 13's finding).
- Symbol concentration: STX+AMD+PYPL = 94.9% of all gross positive R from 3/9 traded symbols; excluding all
  three flips gross R from +75.98 to **-20.97**. Excluding STX alone leaves the remaining population's 5bps
  result *nearly breakeven* (-1.27 from a gross +32.92, only ~4% relative degradation) vs. the full
  population's complete sign flip (~128%) — **STX alone accounts for roughly two-thirds of the entire
  0→5bps deterioration**, a sharper concentration than Task 15/16's trade-level thin-risk cluster, now
  confirmed independently via gross attribution rather than cost-to-risk mechanics.
- Only 38/181 trades (21.0%) carry enough gross margin to survive a 5bps cost at all.
- R:R (screening or execution): no significant relationship with gross outcome (Spearman ≈0.04, p>0.5);
  leave-one-period-out direction failed to replicate in 0 of 4 held-out periods — the least stable
  relationship tested.
- ATR%/risk_pct: no relationship with gross quality (Spearman ≈-0.06/-0.07, not significant) but a strong
  relationship with 5bps-adjusted outcome (Spearman 0.46/0.53, p<1e-9) — the *same* cost-mechanics
  relationship Tasks 15-16 already established, re-derived from a different angle, not a new gross-edge
  predictor. Both `CONTRADICTORY` across subperiods.
- Volume surge ratio: the *only* directionally-reproducible relationship found — negative in all 4
  subperiods and 4/4 in leave-one-period-out — classified `WEAK` (consistent direction, not individually
  significant per period). Counter to design intent: the lowest-volume-surge quartile has the best win rate
  and is the only quartile with positive 5bps expectancy.
- Edge depends on trades that run long: only the longest holding-time quartile (median ≈5.15h) is positive
  at both gross and 5bps; STOP exits (139/181, the majority class) are -1.0 gross by construction.

**Defects/anomalies:** None found — `gross_edge_margin_5bps` reconciled exactly to Task 14's `net_R_5bps`.

**Changed hypotheses:** None reversed. Sharpens the Task 15/16 concentration narrative: the mechanism found
there (thin-risk trades, mostly STX) and the symbol-level concentration found here (STX dominates both gross
wins and gross losses) are two views of the same underlying fact, now cross-validated by independent
methods.

**Conclusions:** Gross performance is concentrated, not broad — by symbol (3/9 symbols), by trade (removing
3-5 winners flips gross negative; only 21% of trades individually gross-margin-positive enough for 5bps),
and by subperiod within STX itself (71% of STX's own gross R in one quarter). No signal-quality attribute
tested (R:R, ATR%, risk_pct) shows a stable, temporally-reproducible relationship with gross outcome; only
volume_surge_ratio does, and its direction is weakly *negative* — opposite of the design rationale.

**Decision:** `CONCENTRATED_GROSS_EDGE`

**Limitations:** Diagnostic only; no filter combinations were ranked by P&L or optimized; subperiod sample
sizes (25-71 trades) limit statistical power, especially for the smallest window (Aug-Oct 2025); LOO is
directional validation only, not a fitted or backtested model.

**Next experiment (recommended, not started):** a diagnostic-only test of the volume_surge_ratio relationship
against a genuinely held-out data slice not used in any prior task's analysis (e.g. data beyond the current
dataset's end date, if/when available) before ever treating it as a candidate filter input. Screening_rr,
ATR%, and risk_pct should not be pursued further as gross-quality predictors.

---

## Task 18 — Volume Relationship Confounding Audit

**Date:** 2026-08-20
**Objective:** Determine whether Task 17's negative volume_surge_ratio-vs-gross_R relationship (negative
direction in all 4 subperiods, 4/4 leave-one-period-out) is genuinely present within comparable trades, or
is caused by symbol/session/exit-type concentration.
**Hypothesis carried forward from Task 17:** volume_surge_ratio had a negative gross-R relationship in all
four subperiods and passed leave-one-period-out 4/4 — the most temporally-reproducible relationship Task 17
found, but causality was explicitly not assumed.

**Dataset/hash:** same 181-trade population, `5e5412a960bf`, reused — no replay. `git_commit
2a5e8855ecf0c337db755577909c74923cb6c2c1` reconfirmed. Built from Task 17's `task17_trade_features.csv`
directly.

**Tests performed:** raw Pearson/Spearman reproduction; within-symbol Spearman for every symbol with
adequate sample, classified NEGATIVE/POSITIVE/FLAT/INSUFFICIENT_SAMPLE; pooled within-symbol correlation
after demeaning both variables by symbol; symbol-exclusion views (STX/AMD/PYPL individually and combined);
session and within-regular-session time-of-day control (reusing `talonx_backtest.analysis`'s own existing
09:30/10:00/15:00/16:00 ET boundaries, not invented here); subperiod-level repetition plus a
pooled within-subperiod-demeaned test; volume-vs-holding-time correlation and volume-vs-gross_R within
holding-time quartiles; volume distribution and within-group correlation by exit type; direction (bearish/
bullish) split; a multivariate OLS model (`gross_R` and `net_R_5bps` each on volume_surge_ratio + symbol +
session + direction + subperiod + holding_hours) with HC3 robust standard errors, hand-implemented since
statsmodels is not installed in this environment.

**Results:**
- Raw relationship was already marginal: Pearson ≈0.000 (p=0.996), Spearman -0.130 (p=0.083 — barely under
  0.10, not significant at 0.05).
- Within-symbol: **STX (94 trades, 52% of the book) shows NO relationship (-0.028, FLAT)**. AMD/PYPL/TSLA
  show negative relationships; NVDA's sign *reverses* (+0.160, POSITIVE). Pooled within-symbol demeaned
  correlation survives weakly (-0.123, p=0.100) but is driven unevenly by the smaller symbols only.
- **Exit-type composition is the single most mechanistic finding:** `STOP` (139/181 trades, 77%) has
  gross_R constant at exactly -1.0 by construction — correlation with volume is undefined for that class, not
  merely small. Among the only two exit types with actual variance, TARGET shows a *positive* relationship
  (+0.197) and END_OF_SESSION is flat (+0.012) — opposite of the pooled negative direction. STOP trades also
  carry modestly *higher* median volume surge (2.546) than TARGET (2.240) or END_OF_SESSION (2.258).
- Session: present in REGULAR (-0.135, p=0.097) but *flips positive* in POST_MARKET_CLOSED (+0.112, p=0.61,
  small n). Regime: pooled within-subperiod-demeaned correlation attenuates to -0.097, p=0.194.
- Holding time: volume and holding time are not meaningfully correlated (p=0.428) — rules out "low volume
  proxies long duration" directly. Within holding quartiles the pattern is inconsistent (Q1 positive, Q3 the
  only individually significant slice found anywhere in this audit at p=0.026, Q4 flat).
- **Multivariate model (decisive):** with symbol + session + direction + subperiod + holding time controlled
  simultaneously, the volume coefficient is statistically indistinguishable from zero for both gross_R
  (coef -0.039, p=0.813) and net_R_5bps (coef +0.010, p=0.949, sign flips) — CIs span both meaningfully
  negative and positive effect sizes.

**Defects/anomalies:** None. Win/loss logistic model skipped (not unstable per se, but the STOP-constant-
outcome structural issue would make it degenerate for the same reason the raw correlation is confounded —
skipped per the task's own "if unstable, skip" instruction rather than force a fit).

**Changed hypotheses:** **Revises** Task 17's framing. Task 17 correctly found the negative direction was
temporally reproducible (4/4 subperiods, 4/4 LOO) and explicitly did not assume causality — Task 18 confirms
that caution was warranted: the relationship does not survive within the dominant symbol, is largely
explained by exit-type composition (a structural artifact of STOP being a constant-outcome majority class),
and disappears under joint multivariate control. Task 17's recommendation to test volume_surge_ratio against
held-out data is **superseded** — this task recommends against spending that validation budget on it.

**Previous conclusion (Task 17):** volume_surge_ratio was the one candidate signal-quality attribute with a
temporally-reproducible relationship, worth held-out testing before other continuous features.
**New evidence (Task 18):** within-symbol, exit-type, and multivariate controls each independently weaken or
eliminate the effect; the raw pooled relationship was already only marginally significant before any control.
**Updated conclusion:** `MIXED_CONFOUNDING` — not a robust independent relationship; do not pursue as a
candidate filter input.

**Conclusions:** No single confound (symbol, session, holding time, regime) alone fully explains the raw
correlation away, but none needs to — the raw effect was weak to begin with, and the full multivariate
control removes it. Exit-type composition (STOP's constant -1.0 outcome inflating the appearance of a
volume effect purely through class composition) is the most mechanistically clean single contributor found.

**Decision:** `MIXED_CONFOUNDING`

**Limitations:** OLS with hand-implemented HC3 errors, not a validated statistics package; R² (~0.12-0.14)
is modest, meaning the controls used explain only a fraction of trade-to-trade variance; multicollinearity
between symbol/session/subperiod dummies and volume_surge_ratio is plausible and would inflate standard
errors (consistent with, not contradicted by, the wide CIs observed); all findings remain diagnostic-only,
no filter was created or tested for P&L, no threshold was tuned.

**Next experiment (recommended, not started):** an exit-type composition audit — `STOP` is a majority-class
(77%) outcome with zero within-class gross_R variance by construction, which this task showed structurally
distorts continuous-feature correlations computed against the pooled book. Tasks 17-18 together have now
tested R:R, ATR%, risk_pct, and volume_surge_ratio without finding a single stable, deconfounded predictor of
gross_R; auditing exit-type composition itself is a more promising next step than testing further continuous
features one at a time. The Task 18 out-of-sample protocol (`task18_oos_protocol.md`) remains defined for
future use but is not recommended for volume_surge_ratio specifically given these findings.

---

## Task 19 — Exit-Path & Stop-Out Anatomy Audit

**Date:** 2026-08-20
**Objective:** Explain why ~77% of corrected 0.20% trades exit at STOP while a small TARGET/EOD population
produces almost all gross edge, and determine whether STOP vs. TARGET/EOD is associated with stable
PRE-ENTRY characteristics or whether currently-qualified trades are largely indistinguishable before entry.
**Hypothesis (updated from Task 18):** exit-path composition itself may be the more fundamental source of
gross performance variation than any single continuous feature — Task 18 showed volume_surge_ratio's
apparent relationship was largely an artifact of STOP being a constant-outcome (-1.0R) majority class;
Task 19 tests exit-path prediction directly rather than inferring it indirectly.

**Dataset/hash:** same 181-trade population, `5e5412a960bf`, reused — no replay. `git_commit
2a5e8855ecf0c337db755577909c74923cb6c2c1` reconfirmed. Built from Task 17's `task17_trade_features.csv` +
Task 16's `task16_trade_geometry.csv` (fill-movement fields). Strict pre-entry/post-entry separation
maintained throughout: only pre-entry fields (symbol, direction, session, ATR%, volume_surge_ratio,
screening/execution R:R, signal→fill delay, risk_pct, risk-preservation ratio, fill movement) were used as
candidate STOP predictors; post-entry fields (holding time, MFE, MAE) were used only for descriptive
anatomy, never as model inputs.

**Tests performed:** exit-class baseline (count/R/symbols/sessions/subperiods per STOP/TARGET/EOD);
full pre-entry continuous-feature comparison (mean/median/P25/P75/Cohen's d/Mann-Whitney) across the three
exit classes; a descriptive logistic STOP-vs-non-STOP model on pre-entry features (sklearn, unregularized,
hand-computed Hessian-based Wald p-values and AUC, since statsmodels is not installed) — run twice, once
with the full feature+categorical-dummy set and once as a reduced continuous-only robustness check per the
task's own "prefer a small interpretable model" instruction; TARGET-vs-EOD comparison; symbol-level STOP
rates; symbol-demeaned (within-symbol) checks on every candidate relationship; subperiod-level STOP-rate
stability plus leave-one-period-out; session/time-of-day exit rates; signal→fill movement vs. exit class;
post-entry STOP excursion anatomy (bucketed by MFE reached before the stop) and STOP holding-time-speed
buckets, each explicitly descriptive/anatomical, never model inputs; cost deterioration by STOP speed;
R:R-vs-exit-path (Kruskal-Wallis across the three classes plus Spearman vs. the binary STOP indicator);
confluence-score variation recheck; an explicit OOS-candidate scorecard requiring both LOO direction
consistency and symbol-demeaned significance before any variable could be labeled a candidate.

**Results:**
- Exit composition: STOP 139/181 (76.8%, gross total -139.00, constant -1.0R per trade by construction),
  TARGET 16 (8.8%, +105.23 gross), END_OF_SESSION 26 (14.4%, +109.75 gross) — a 23.2% minority produces all
  gross positive R.
- STOP model: the full model (19 parameters, categorical dummies included) showed AUC=0.686 but with huge,
  untrustworthy standard errors (intercept SE=6153) — a quasi-separation artifact of sparse symbol
  categories (AAPL/MSFT/GOOGL: 1-3 trades each, perfectly predicting their own outcome). The **reduced,
  continuous-only model** (the task's own recommended robustness check) showed AUC=**0.578** (barely above
  random) with **every coefficient non-significant** (p=0.33-0.97) — the full model's apparent
  discrimination was memorizing sparse categories, not real continuous-feature signal.
- TARGET vs. EOD: essentially the same pre-entry population — differ significantly only in R:R (p<0.001,
  a mechanical consequence of target distance: closer targets get reached, farther ones stay open at
  session end), not in ATR%, risk_pct, volume, delay, or fill movement (all p>0.27). Merely different paths
  after an indistinguishable entry, not different setup types.
- Symbol STOP rates: modest spread (50-88% excluding tiny-sample symbols); PYPL notably lower (50%) but STX
  (52% of the book) sits close to the overall rate (78.7% vs. 76.8%) — not concentrated in one symbol.
- Signal→fill movement: **definitive null** — median adverse move and delay are identical (0.0%, 1 min)
  across all three exit classes; Spearman vs. is_stop = 0.025 (p=0.736). Confirms Tasks 15-16's
  risk-erosion mechanism is an isolated tail phenomenon (1-2 trades), not a general STOP driver.
- STOP anatomy: **56.1% of all STOP-outs moved favorably by ≥0.5R before eventually reversing** — a
  reversal-dominant failure mode, not an immediate-bad-entry-dominant one (only 16.5% show near-zero
  favorable excursion). Only 23.7% of STOPs are effectively immediate (<2 min); the `<2min` bucket suffers
  ~3× the per-trade cost deterioration of every other speed bucket, connecting to the Task 15-16 thin-risk
  mechanism (the single most extreme trade sits in this bucket).
- R:R vs. exit path: differs significantly across the three classes (Kruskal-Wallis p<0.001) but has
  essentially zero monotonic relationship with STOP specifically (Spearman ≈-0.01, p=0.90) — extends Task
  17's realized-R finding to exit-path prediction.
- Zero variables qualify as `CANDIDATE_FOR_OOS_VALIDATION` (requiring both LOO-consistent direction and
  symbol-demeaned p<0.10).

**Defects/anomalies:** None found in the data. The full logistic model's quasi-separation is a modeling
artifact of this task's own design choice (too many sparse categorical dummies for n=179), not a defect in
the trade data — flagged and corrected within the same task via the reduced-model robustness check.

**Changed hypotheses:** Confirms and sharpens Task 18 rather than reversing it — the updated hypothesis
("exit-path composition is the more fundamental source of variation") is supported: STOP's constant -1.0R
outcome structurally dominates the book, but WHICH trades become STOP is not predictable from any pre-entry
characteristic tested.

**Conclusions:** Currently-qualified trades are essentially indistinguishable before entry along every
pre-entry dimension tested (ATR%, volume, R:R, risk-preservation, fill movement, symbol/session, in
isolation or combined). The STOP/TARGET/EOD split is a post-entry, reversal-driven phenomenon — most losses
are trades that initially worked and then gave it back, not trades that were doomed from the start.

**Decision:** `STOP_OUTS_BROAD_AND_NOT_PREDICTABLE`

**Limitations:** Descriptive logistic models only (not predictive/trading models); reduced model's low AUC
(0.578) is itself the primary evidence, not a limitation to explain away; MFE/mechanism findings are
post-entry anatomy, explicitly not proposed as entry filters; subperiod sample sizes (25-71 trades) limit
power as in every prior task in this series.

**Next experiment (recommended, not started):** a diagnostic-only audit of the reversal mechanism itself —
for the 56.1% of STOP trades that reached ≥0.5R favorable excursion before reversing, characterize what (if
anything, post-entry) distinguishes trades that held their move long enough to reach TARGET/EOD from those
that gave it back. Explicitly a post-entry, risk-management-relevant question, not a new entry filter — to
be scoped as its own diagnostic task.

---

## Task 20 — Trade Excursion & Reversal Anatomy

**Date:** 2026-08-20
**Objective:** Understand the post-entry path of the corrected 0.20% trade population — whether TalonX's
primary weakness is failure to retain favorable excursion after entry, and whether any trade-management
hypothesis (breakeven, trailing, tightening, time-based) deserves future controlled testing.
**Hypothesis carried forward from Task 19:** many STOP trades initially move favorably (56.1% reach ≥0.5R
before reversing), so post-entry path behavior may be more informative than entry filtering.

**Dataset/hash:** same 181-trade population, `5e5412a960bf`, reused — no full replay. `git_commit
2a5e8855ecf0c337db755577909c74923cb6c2c1` reconfirmed. This task DID read raw 1-minute bars (11,896 bars
across all 181 trades, entry-to-exit) to reconstruct running MFE/MAE — this is bar-level reconstruction of
trades that already happened, not a strategy replay; no stop/target/trailing logic was altered or simulated.

**Tests performed:** direction-adjusted R-unit conversion of every bar using each trade's original initial
risk (`risk_dollars_per_share`, the same denominator `gross_R` itself uses); excursion-landmark crossings at
7 levels (+0.25R to +3.00R) with time-to-level; exit-class (STOP/TARGET/EOD) excursion comparison; STOP
reversal-anatomy buckets (A: never reaches +0.25R, through E: reaches ≥2R); favorable-then-stop population
analysis at 3 thresholds; winner-retracement analysis (maximum subsequent pullback after first reaching a
landmark, for TARGET/profitable-EOD trades only); breakeven-crossing rates by exit class; a transparent,
pre-defined path-shape classification (IMMEDIATE_FAILURE / SMALL_FAVORABLE_THEN_STOP / LARGE_FAVORABLE_
THEN_REVERSAL / DEEP_RETRACE_WINNER / MONOTONIC_WINNER / SLOW_TREND_WINNER / OTHER); symbol/session/subperiod
breakdowns of reversal rates; cost interaction (0bps vs. 5bps) by path class; a management-hypothesis
screening against 5 candidate mechanisms using only path evidence, no simulation, no threshold selection.

**Results:**
- STOP's P75 MFE (1.31R) exceeds many TARGET/EOD trades' minimum favorable excursion — substantial path
  overlap between eventual losers and winners in early excursion; they only diverge in how the trade
  resolves after a shared range of initial favorable movement.
- STOP reversal anatomy: 56.1% of stops (C+D+E buckets) reach ≥0.5R before reversing — independently
  reconstructed via full bar-by-bar walk here, exactly matching Task 19's single-field estimate
  (cross-validated by two different methods).
- Favorable-then-stop population: 78 trades reach ≥0.5R before stopping (-108.21R at 5bps), 50 reach ≥1.0R
  (-69.57R), 24 reach ≥2.0R (-34.30R). Reversals are gradual (minutes to ~an hour), not instantaneous.
- **Winner retracement (decisive):** 100% of eventual winners reach +0.25R and +0.5R at some point; 87.5%
  of them subsequently cross back through breakeven after +0.5R, and 55% still do so even after a full +1R.
  Even after +1R, 37.5% of eventual TARGET winners and 69.2% of eventual EOD winners dip back to breakeven
  before their final profitable outcome.
- Path classes: **`DEEP_RETRACE_WINNER`** (35 trades, 19.3% of the book — winners that crossed back through
  breakeven after first reaching +0.5R, then still won) contributes **+194.45 gross R, more than the entire
  book's net +75.98 total**, since every other path population (`IMMEDIATE_FAILURE`, `SMALL_FAVORABLE_THEN_
  STOP`, `LARGE_FAVORABLE_THEN_REVERSAL`) is net negative. This single population is the strategy's actual
  source of edge, and it is defined precisely by tolerating deep, breakeven-crossing retracements.
- `IMMEDIATE_FAILURE` (41 trades, median 2-minute resolution, near-zero favorable excursion) is the single
  largest contributor to the 0→5bps cost deterioration (42.81R of 97.39R total), connecting to Task 19's
  <2min-STOP cost-fragility finding.
- Broadly present across symbols (40-71% of each symbol's stops reach ≥0.5R) and sessions (55-63%), and
  `STABLE` across subperiods (46-67%, never reversing direction).
- Management-hypothesis screening: breakeven protection, partial tightening, and trailing stops are all
  classified `HIGH_RISK` — each has a direct, quantified path through the `DEEP_RETRACE_WINNER` population.
  Time-based exit is `UNTESTED_HERE` (the distinguishability of `IMMEDIATE_FAILURE` from the early minutes of
  a future `DEEP_RETRACE_WINNER` was not tested).

**Defects/anomalies:** None. All bar-walk totals reconciled against the existing ledger before analysis.

**Changed hypotheses:** Confirms and extends Task 19 — the reversal pattern found there is real and
quantified here at the population level, but the critical NEW finding is that eventual **winners** show the
*same* breakeven-crossing behavior as eventual losers at similar rates, which was not established by Task 19
alone. This directly informs (and constrains) any future trade-management hypothesis.

**Conclusions:** TalonX's primary weakness is not entry-signal quality (Tasks 17-19) — it is that the
strategy's entire edge is concentrated in a specific post-entry path (`DEEP_RETRACE_WINNER`) that requires
tolerating exactly the kind of deep retracement that any naive reversal-management rule would cut short.

**Decision:** `HIGH_RISK_OF_KILLING_WINNERS`

**Limitations:** Diagnostic and anatomical only — no management rule was simulated or backtested; the
path-class boundaries (0.25R/1.0R for STOP buckets, holding-time median for the SLOW_TREND split) are fixed,
transparent definitions, not optimized cutoffs; `n=40` winners is a modest sample for the retracement
percentages, though the pattern is consistent across both TARGET and EOD subgroups independently.

**Next experiment (recommended, not started):** a diagnostic-only test of whether `IMMEDIATE_FAILURE`
trades can be distinguished from the early minutes of eventual `DEEP_RETRACE_WINNER` trades using only
information available in that same early window — the one path class this task did not find direct evidence
of winner overlap with, and therefore the most promising (if still unproven) candidate for any future
narrowly-targeted mechanism. No rule should be tested or simulated until that question is answered.

---

## Task 21 — Early Failure Separability Audit

**Date:** 2026-08-20
**Objective:** Determine whether `IMMEDIATE_FAILURE` trades (Task 20) can be distinguished, using ONLY
information genuinely available in the first minutes after entry, from trades that eventually become
`DEEP_RETRACE_WINNER` — the population responsible for essentially all of TalonX's gross edge. A diagnostic
separability study, explicitly not a strategy modification.
**Hypothesis carried forward from Task 20:** a broad breakeven/trailing-stop rule is dangerous
(`HIGH_RISK_OF_KILLING_WINNERS`), but a genuinely identifiable immediate-failure *state* might be a more
targeted future research direction, since Task 20 found `IMMEDIATE_FAILURE` (41 trades) showed no direct
evidence of path overlap with `DEEP_RETRACE_WINNER` the way the other loss populations did.

**Dataset/hash:** same 181-trade population, `5e5412a960bf`, reused — no replay. `git_commit
2a5e8855ecf0c337db755577909c74923cb6c2c1` reconfirmed. Task 20's exact path-class counts (`IMMEDIATE_
FAILURE`=41, `DEEP_RETRACE_WINNER`=35) reconciled before analysis, not redefined.

**Tests performed:** strict information-time discipline (features at horizon T use only bars from entry
through min(T, exit) — no final holding time, exit reason, future MFE/MAE, or later-session information
ever enters the feature set); 5 pre-registered horizons (1/2/3/5/10 minutes, fixed in advance, not tuned);
14 early price-path and volume features per horizon (current_R, running MFE/MAE, distance-to-stop,
range-since-entry, close-location-value, favorable/adverse/consecutive bar counts, path efficiency, 4
volume variants); first-minute distributional comparison; fixed-horizon survival counts (avoiding
look-ahead for trades that already exited); conditional-survivor comparison at every horizon; Mann-Whitney
tests with Benjamini-Hochberg FDR correction across the full 70-test (5 horizons × 14 features) grid; a
small, pre-specified 3-feature logistic model (fixed before inspecting the distributional results) with
5-fold cross-validated AUC; leave-one-subperiod-out validation across all 4 Task-13 windows; leave-one-
symbol-out validation for STX/AMD/PYPL/TSLA/NVDA; a mandatory false-protection-risk quantification (correct
failure-flag rate vs. false winner-flag rate, using a descriptive median-midpoint threshold, explicitly not
converted into a P&L simulation); economic attribution by population.

**Results:**
- First minute: immediate failures are already visibly worse on price-path features — current_R median
  -0.548 (A) vs. +0.087 (B), Cohen's d=-1.39, p=2.5e-7; distance-to-stop_R median 0.452 (A) vs. 1.087 (B),
  same effect size. Volume features showed no significant separation at T=1 — the signal is entirely in
  price path, not volume.
- 40 of 70 pre-registered feature×horizon tests remain significant after BH-FDR correction (α=0.05) — a
  large, not marginal, fraction.
- Model discrimination: pre-specified 3-feature logistic model reaches AUC 0.88-0.91 in-sample and
  0.80-0.85 cross-validated across T=1-5 minutes — **a large information gain versus Task 19's pre-entry
  benchmark of AUC 0.578 (essentially random)**. T=10 minutes is underpowered (only 4 `IMMEDIATE_FAILURE`
  survivors remain by then, since that population resolves in a median ~2 minutes).
- Subperiod validation: leave-one-subperiod-out AUC ranges 0.77-1.00 where testable (the smallest
  subperiod, Aug-Oct 2025, becomes untestable as a held-out set at T≥3 due to shrinking survivor counts).
- Symbol validation: STX held out shows AUC 0.80-0.84 at T=1-3 but **degrades to near-random (0.56) at
  T=5**; AMD held out generalizes well throughout (0.89-1.00); PYPL/TSLA/NVDA test sets are too small
  (1-8 trades) to judge. Cross-symbol generalization is present but incomplete and horizon-dependent.
- **False-protection risk (mandatory, decisive for the final call):** the best single early-window feature
  per horizon, at a purely descriptive midpoint threshold, correctly flags 62.5-100% of `IMMEDIATE_FAILURE`
  trades but also falsely flags **17.6-23.5% of `DEEP_RETRACE_WINNER` trades** at most horizons. Given
  `DEEP_RETRACE_WINNER` trades average +5.56 gross R each versus `IMMEDIATE_FAILURE`'s exactly -1.00R each
  (a ~5.5× per-trade value asymmetry), this false-flag rate represents a materially larger economic risk
  than the raw percentage suggests — reported as context, not as a P&L simulation.
- Economic attribution: `IMMEDIATE_FAILURE` (41 trades, 22.7% of the book) remains the single largest
  contributor to 0→5bps cost deterioration (44.0% of the total), confirming Task 20's finding independently.

**Defects/anomalies:** None. All population counts and totals reconciled exactly against Task 20 before
analysis.

**Changed hypotheses:** Meaningfully updates (does not reverse) the research trajectory: pre-entry
information (Tasks 17-19) carries essentially no predictive signal (AUC 0.578), but **post-entry price
action, even just the first minute, carries substantial genuine signal** (AUC 0.85-0.91) — a materially
different and more encouraging finding than anything found pre-entry. However, this signal does not yet
clear the bar for a safe mechanism given the false-protection risk on the economically dominant winner
population.

**Conclusions:** Early failures ARE statistically separable from eventual deep-retrace winners using only
post-entry information — a genuine, cross-validated, largely FDR-significant effect, unlike any pre-entry
relationship tested in Tasks 17-19. But separability is not yet "safe": incomplete cross-symbol
generalization (STX degrades at T=5) and a false-protection rate of 17.6-23.5% on a population worth ~5.5×
more per trade than the failures being targeted mean any early-exit mechanism built on this signal today
would carry real, quantified risk to the strategy's actual source of edge.

**Decision:** `EARLY_FAILURE_WEAKLY_SEPARABLE`

**Limitations:** Diagnostic and exploratory only — no rule was created, tested, or simulated for P&L; the
false-protection thresholds are descriptive (median midpoints), not optimized or proposed cutoffs; sample
sizes shrink sharply at T=10 (4 `IMMEDIATE_FAILURE` survivors) and for most held-out symbols other than STX
and AMD, limiting the strength of claims at those specific slices; BH-FDR correction was applied but with
n=181 trades total and much smaller per-horizon subsamples, statistical power remains modest by
conventional standards.

**Next experiment (recommended, not started):** a diagnostic-only test of the same early-window features
and model specification against the genuinely held-out data slice already defined in Task 18's
out-of-sample protocol (`2026-08-17` onward, never used in any prior task) — before any early-exit
mechanism is ever prototyped. This is exactly the situation that protocol was designed to gate.

---

## Task 22 — Freeze & OOS Early-Failure Validation Protocol

**Date:** 2026-08-20
**Objective:** Freeze the Task 21 early-failure hypothesis before examining any post-2026-08-14 outcomes,
and build a deterministic, append-only true out-of-sample validation pipeline — preventing further
in-sample optimization of the early-failure signal.
**DISCOVERY PERIOD:** `2025-08-15` through `2026-08-14`. **OOS PERIOD:** `2026-08-17` onward. **Task 21
decision carried forward:** `EARLY_FAILURE_WEAKLY_SEPARABLE`.

**The Task 21 hypothesis is now FROZEN as of this task.** Any later change to its features, coefficients,
horizon, classification threshold, or population definitions constitutes a **new** research hypothesis and
cannot reuse the OOS sample accumulated under this freeze as clean validation.

**Frozen specification:** `docs/research/task21_frozen_early_failure_spec.json` — re-extracted (not
retrained; same code, same discovery-period data) from Task 21's own fitted models: a 3-feature
unregularized logistic regression (`current_R`, `running_MAE_R`, `consecutive_adverse_bars`) at each of 4
horizons (1/2/3/5 minutes — T=10 excluded, Task 21 itself could not fit a stable model there with only 4
positive cases). Task 21 designated no single "best" horizon, so all 4 are frozen as a **co-equal family**,
to be read jointly in any future OOS evaluation, never cherry-picked after the fact. `frozen_spec_hash =
9c15d11c021dddbd`, independently recomputed and verified to match at OOS-evaluation time.

**OOS data:** `2026-08-17` through `2026-08-19` (3 trading days — the entirety of already-closed trading
between the discovery cutoff and 2026-08-20, the date this task ran; 2026-08-20 itself had not traded yet).
Sourced via yfinance (no Alpaca/Polygon credentials available in this environment) — a genuine
provider-source difference from the Alpaca-sourced discovery data, recorded as a caveat. Written to a
separate directory (`data/historical_1m/task22_oos/`); the discovery dataset was never touched
(`5e5412a960bf` reconfirmed unchanged). OOS dataset hash: `e78ab77afe36`.

**Strategy freeze:** OOS trades were generated with the exact frozen `min_atr_pct=0.20%` strategy and all
other unchanged production defaults — the Task 21 model is strictly observational and did not influence
these trades in any way.

**Results:**
- The 3-day OOS window produced **1 trade** (`MSFT-2026-08-18`, STOP, gross R=-1.0, path class
  `SMALL_FAVORABLE_THEN_STOP` — neither primary population).
- Status: **`OOS_ACCUMULATING`** — 1 trade is far below the pre-registered 40-trade minimum (carried
  forward unreduced from Task 18's protocol); no statistical metrics (AUC, sensitivity, specificity,
  confidence intervals) were computed or interpreted, per the pre-registered rule.
- **Leakage test: PASS** — every horizon-T feature verified to use only bars with elapsed minutes ≤ T.
- **Determinism test: PASS** — feature extraction rerun independently produced identical SHA-256 hashes.
- The single available trade is reported as a purely illustrative, non-statistical worked example: the
  frozen model's predicted `IMMEDIATE_FAILURE` probability was 0.947/0.924 at T=1/2 minutes, then flipped to
  0.206/0.024 at T=3/5 minutes as the trade's actual modest recovery unfolded before it eventually stopped
  out — demonstrating the pipeline runs correctly end to end, not evidence for or against the hypothesis.

**Defects/anomalies:** None. All integrity checks (frozen-spec hash, dataset hashes, leakage, determinism)
passed.

**Conclusions:** The freeze-and-validate infrastructure is built, tested, and functioning correctly. The
OOS sample is, as expected given only 3 elapsed trading days, far too small to say anything about the
hypothesis itself yet.

**Decision:** `OOS_ACCUMULATING`

**Limitations:** n=1 permits no inference. Provider difference (yfinance OOS vs. Alpaca discovery) is a
data-provenance caveat to track as more OOS data accumulates. At the discovery-period base rate (~181
trades/year across these 10 symbols), reaching 40 OOS trades will likely take several weeks to a few months
of elapsed trading time.

**Next experiment (recommended, not started):** continue accumulating OOS trades under the frozen
specification with zero changes to features, coefficients, horizons, or thresholds; re-run
`research/scripts/task22_oos_evaluate.py` unchanged against an updated OOS data pull once the sample
plausibly approaches 40 trades. Do not shorten the minimum, do not inspect intermediate AUC for early
signal, and do not retrain or recalibrate before then.

---

## Checkpoint — Durable Research Review Checkpoint (2026-08-20)

**Purpose**: *"Freeze current evidence before first-principles correctness re-audit."* Not a strategy
experiment — no parameters, logic, or the frozen Task 21 specification were touched. Pushed the current
validated local state to GitHub as a reviewable branch/PR ahead of Task 24 (full requirements/data/
implementation/live-backtest-parity/execution-correctness audit).

**Checkpoint commit**: `268f59efcfa253cafe09b7c2bba0d3656ba62bf6`
**Branch**: `research/talonx-strategy-validation` (pushed to `origin`, new remote branch — this branch had
never been pushed before this checkpoint; `origin/main` confirmed as a clean ancestor of the checkpoint
commit, no rebase/force needed)
**Date**: 2026-08-20

**What was included** (staged individually, path by path — no `git add -A`/`.`): `docs/research/
TALONX_RESEARCH_LEDGER.md` (this file, Task 1.1–22 backfilled + contemporaneous), `docs/research/
task21_frozen_early_failure_spec.json` (frozen spec, `frozen_spec_hash 9c15d11c021dddbd` — unaltered),
and the 9 deterministic research scripts `research/scripts/task15_risk_distance_audit.py` through
`research/scripts/task22_oos_evaluate.py` + `task22_freeze_spec.py`. This commit also carries the two
prior local-only commits it sits on top of (`0682693` live-pipeline hardening, `2a5e885` the Task 13B
fill-geometry fix) — both confirmed present in the working tree and **absent from `origin/main`** at
checkpoint time (`git diff origin/main..HEAD` — 24 files, +2372/−110 lines, including `talonx_backtest/
engine.py`'s `_finalize_fill_geometry` and its dedicated 9-test file `tests/test_backtest_fill_geometry.py`,
neither of which exist on `origin/main`).

**What remained ignored/uncommitted**: `logs/` (6 small stdout/timestamp files from Task 14's background
cost-sensitivity replays — transient operational logs superseded by the proper `results/task14_cost_
sensitivity/` artifacts, which are deliberately `.gitignore`d by long-standing project convention along
with all of `data/`, `results/`, and `reports/`). No secrets, `.env`, credentials, or raw market datasets
were staged or committed.

**Focused tests run** (not the full suite; documentation-only files did not require a strategy replay):
`pytest tests/test_backtest_fill_geometry.py` (9), `tests/test_backtest_execution.py` (28), `tests/
test_backtest_lookahead.py` (4), `tests/test_backtest_reproducibility.py` (31), `tests/test_backtest_
engine_state.py tests/test_backtest_regression.py` (18), `tests/test_backtest_cli.py tests/test_backtest_
research_telemetry.py` (26) — **116/116 passed, 0 failed**. Task 22's leakage/determinism checks were
re-run against the existing (not re-fetched) OOS data and frozen spec: `leakage_ok=True`,
`determinism_ok=True`, feature-hash-identical across two independent runs, sample unchanged (still 1 OOS
trade, still `OOS_ACCUMULATING`) — no additional OOS outcomes were inspected.

**Remote verification**: `origin/research/talonx-strategy-validation` confirmed identical to local HEAD
(`268f59e...`) post-push. Draft PR opened: **#10**, `research/talonx-strategy-validation` → `main`,
`isDraft: true`, titled "Research checkpoint: TalonX validation through Task 23" — explicitly marked as a
review checkpoint, not a merge request, and not marked ready for review/merge.

**No prior research conclusion in this ledger was altered by this checkpoint.**
