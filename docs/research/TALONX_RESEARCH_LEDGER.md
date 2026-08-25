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

---

## Task 24 — First-Principles Requirements & Live-vs-Backtest Parity Audit (2026-08-20)

**Purpose**: Establish what TalonX is supposed to do (from requirements-level evidence, never from
profitability) and compare that against the live/paper implementation, the historical backtester, tests,
and documentation. No strategy parameters, confluence weights, or volume thresholds were changed; no new
historical backtest was run; no additional Task-22 OOS outcomes were inspected; no production code was
changed. Full detail in `results/task24_requirements_parity_audit/` (11 artifacts: `fill_geometry_audit.md`,
`long_short_flow.md`, `closing_eod_audit.md`, `confluence_semantics.md`, `volume_baseline_audit.md`,
`live_vs_backtest_traceability.csv`, `gate_order_parity.csv`, `test_coverage_audit.csv`,
`research_impact.csv`, `task24_summary.md`, `task24_summary.json`).

**Canonical requirement determined from evidence**: the strategy is **LONG_ONLY**. A BEARISH/CONTRADICTED
signal is intended as an exit trigger for an existing long position, never a new short entry — established
independently by `README.md`'s BUY/SELL-only vocabulary, `docs/modules/quant.md`'s closing-blackout
rationale comment, `docs/modules/paper.md`'s flat/long-only state diagram, `talonx_paper`'s actual
implementation (no code path opens a short), and the dedicated test
`test_confirmed_bearish_flat_is_ignored`.

**Critical finding — long/short semantic mismatch confirmed as a BUG, not a documented divergence**:
`talonx_backtest` opens genuine new short positions on BEARISH `QuantSignal`s (`TradeSimulator.open_position`
treats direction symmetrically; PnL formula applies `direction_sign = -1.0` for BEARISH). No document
anywhere describes this as an intentional research design choice, and no backtest test affirmatively
asserts it as a deliberate contract. From existing artifacts only (no rerun): 133 of 181 trades (73.5%) and
94.96% of gross positive R in the corrected 0bps baseline (Task 13B/14 artifacts) are attributable to this
trade type.

**Compounding finding**: the backtest's EOD-flatten sweep only fires once per calendar date; a position
opened during 15:50–16:00 ET via the long/short bug can structurally survive un-flattened until the
following day's checkpoint. Reachable only through the same root-cause bug, not an independent overnight
exposure path.

**Other confirmed findings**: `US_MARKET_SESSION_CLOSED` gate present in live, absent and undocumented in
backtest (P1); `talonx_paper` has no equivalent of the backtest's `_finalize_fill_geometry` fill-price
reconciliation (P1, new finding, live-side gap); RSI-curl trigger and RSI-confluence conditions are
structurally mutually exclusive on the same bar, with no documentation either way
(P2, `REQUIREMENT_AMBIGUOUS`); MACD-cross confluence scoring is deliberately direction-agnostic and
consistently documented (`INTENDED`, not a defect); volume-surge-ratio's denominator includes the current
bar (confirmed mechanically — 19×100+300bp example yields ≈2.727x, not 3.00x) — this is shared code used
identically by live and backtest, so not a parity issue, but the convention is undocumented and unpinned by
any test (P3).

**Task 13B fill-geometry fix**: re-confirmed unchanged (`git diff 2a5e885` = 0 lines) and `CORRECT` — all 9
dedicated tests still pass.

**Final decision**: `MULTIPLE_MATERIAL_CORRECTNESS_ISSUES`.

**Recommended next task (not started)**: Task 25 — Long-Only Backtest Engine Correction & Full Historical
Re-Validation — fix `talonx_backtest`'s BEARISH-signal handling to match the LONG_ONLY requirement
(exit-only, mirroring `talonx_paper.decide_trade`), add regression tests, then re-run the full historical
backtest and Task 20/21/22-style validation from scratch on the corrected engine.

### Revision to prior conclusions (Tasks 14, 16–20, 22)

> **Previous conclusion**: Task 14's cost-sensitivity total-R/expectancy/profit-factor figures, and the
> economic-viability conclusions of Tasks 16–20 and Task 22's OOS accumulation, were treated as
> characterizations of the TalonX strategy's live economic performance (combined across all trades).
>
> **New evidence**: Task 24 established that ~95% of the gross positive R in these direction-undecomposed
> figures comes from `talonx_backtest`-opened short positions — a trade type confirmed, from first-principles
> requirements evidence, not to exist in the live/paper system as built (`talonx_paper` is long-only; see
> `long_short_flow.md`).
>
> **Updated conclusion**: These prior findings are reclassified from economic evidence to
> `NOT_YET_VALID_AS_LIVE_ECONOMIC_EVIDENCE` (see `results/task24_requirements_parity_audit/research_impact.csv`
> for the full per-task breakdown). This does not discard the underlying research — the *implementation*
> measurements within these tasks (e.g., that the shared gate/signal-generation code behaves as coded) remain
> valid — only the direction-undecomposed economic/profitability conclusions are affected, pending re-derivation
> on a long-only-corrected backtest engine (Task 25, recommended above).
>
> **Reason**: the long/short semantic mismatch was not previously known; Task 24 was the first task to
> independently determine the canonical requirement from evidence (rather than from returns) and trace it
> against the actual implementation.

---

## Task 25A — Long-Only Backtest Parity Correction (2026-08-20)

**Objective**: Correct the defect Task 24 identified — `talonx_backtest` opening a genuine short position on
every BEARISH `QuantSignal` — so the backtest's trade lifecycle matches the canonical LONG_ONLY requirement
(BULLISH-while-flat opens a long; BULLISH-while-long is a no-op; BEARISH/CONTRADICTED-while-long closes the
long; BEARISH/CONTRADICTED-while-flat is a no-op, never a new short). Full detail in
`results/task25a_long_only_parity_fix/` (9 artifacts: `task25a_summary.md`, `task25a_summary.json`,
`state_machine_matrix.csv`, `live_backtest_contract.csv`, `closing_eod_tests.csv`,
`closed_session_tests.csv`, `fill_geometry_live_gap.md`, `test_results.txt`, `research_impact.md`).

**Task 24 defect being corrected**: see this ledger's own Task 24 entry above and
`results/task24_requirements_parity_audit/long_short_flow.md` — `TradeSimulator.open_position` treated
BULLISH/BEARISH symmetrically and applied a `direction_sign=-1.0` short-PnL formula to BEARISH candidates.

**Canonical requirement**: LONG_ONLY (unchanged from Task 24's determination — re-derived from evidence, not
from returns).

**Files changed**: `talonx_backtest/engine.py` (LONG_ONLY lifecycle, new `US_MARKET_SESSION_CLOSED` and
`POST_EOD_FLATTEN_NO_NEW_ENTRY` gates, `_PendingExit`), `talonx_backtest/execution.py`
(`TradeSimulator.close_on_signal_exit`, `_close` gained an optional `exit_signal` parameter),
`talonx_backtest/portfolio.py` (`Trade.exit_signal_type`/`exit_signal_direction`, both default `None`). No
changes to `talonx_quant/*` or `talonx_paper/*`.

**Exact lifecycle before**: any qualifying `QuantSignal` (BULLISH or BEARISH) that survived the gate pipeline
and was flat-eligible opened a new `OpenPosition` with `direction` copied straight from the signal;
`execution.py`'s PnL formula (`direction_sign = 1.0 if BULLISH else -1.0`) then profited a BEARISH position on
a price decline — a genuine simulated short.

**Exact lifecycle after**: a BULLISH signal behaves exactly as before (opens/no-ops on an existing long). A
BEARISH/CONTRADICTED signal is now routed by `_flush_throttle` based on current position state: if a long is
open, it schedules an alert-driven `_pending_exit`, filled at the next bar's open (`exit_reason="SIGNAL_EXIT"`,
never a synthetic STOP/TARGET); if flat, it is recorded as `NO_ACTIVE_POSITION` (the same reason
`talonx_paper.decide_trade` uses for the identical case) and opens nothing.
`TradeSimulator.open_position`/`check_bar_for_exit`/`_close`'s direction-symmetric math were deliberately kept
generic rather than guarded/deleted — the invariant is enforced entirely by `_flush_throttle`'s routing, which
is the only call site that ever populates `_pending_entry`/`_pending_exit`.

**Tests**: 2 new files — `tests/test_backtest_long_only_lifecycle.py` (13 tests: full FLAT/LONG ×
BULLISH/BEARISH matrix, closing-blackout integration, post-EOD-flatten no-re-entry, closed-session parity,
next-bar-open no-lookahead proof) and `tests/test_live_backtest_contract.py` (3 tests: a permanent
`talonx_paper.decide_trade`-vs-backtest position-state-sequence parity regression). Required pre-existing
focused suite + both new files: 75/75 passed. Full `tests/ -k backtest`: 261 passed, 1 skipped (pre-existing,
unrelated), **15 xfailed (strict, new)**, 0 failed — see below.

**New finding (independent corroborating evidence)**: all four of the project's own canonical example-data
demo trades — `examples/data/sample_AAPL_trade_1m.csv`'s one documented trade and
`examples/data/sample_multi_trade_1m.csv`'s TSTW/TSTL/TSTE three-trade win/loss/EOD demo — turn out to have
been built entirely around the same long/short bug (a BEARISH `macd_bearish_cross` opening a short while
flat). Under the corrected lifecycle they now correctly produce zero trades. The 15 tests depending on this
are marked `pytest.mark.xfail(strict=True, reason=...)` rather than left silently failing; CSV regeneration
under the frozen production `QuantConfig` (requires real 200-bar/15-min HTF trend-gate warmup —
`_trend_gate_applicable` is itself BULLISH-only, further independent evidence for the LONG_ONLY reading) is
tracked as a follow-up, not rushed in this task.

**Remaining ambiguities**: left untouched per instruction — RSI-curl-vs-RSI-confluence self-exclusion, MACD
direction-agnostic confluence scoring, volume-surge-ratio denominator documentation. No `talonx_quant`
threshold, weight, or gate-ordering value was changed.

**Live fill-geometry conclusion**: `talonx_paper` still has no equivalent of `_finalize_fill_geometry`.
Investigated (not fixed): the required ATR/pivot data is present on `alert.triggering_signal`, but
`talonx_paper` has no `QuantConfig`/`min_risk_reward_ratio` wired in at all — a real architectural gap, not a
same-function fix. Marked `BLOCKING_FOLLOW_UP`; see `fill_geometry_live_gap.md` for the investigation and the
smallest-fix sketch (Task 25B, recommended below).

**No historical performance result**: no full historical replay was run; no PF/expectancy/total-R was
computed or compared in this task, by design (Task 25A proves implementation correctness only).

**Task 22 status update** (conceptual only — no new OOS outcomes inspected, frozen spec hash
`9c15d11c021dddbd` untouched): `OOS_SUSPENDED_PENDING_CANONICAL_LONG_ONLY_BASELINE` — the Task 21/22
hypothesis was derived from a historical population containing a large majority of simulated shorts canonical
TalonX never opens.

**Decision**: `LONG_ONLY_FIX_VALIDATED_WITH_REMAINING_P1_GAPS`.

**Next task (recommended, not started)**: Task 25B — Live Fill-Geometry Reconciliation (wire
`QuantConfig`/`min_risk_reward_ratio` into `talonx_paper`, port `_finalize_fill_geometry`'s logic into
`_execute_buy`, add dedicated tests).

**State**: not committed, not pushed — diff returned for review per instruction.

### Revision to prior conclusion (historical backtester validity)

> **Previous conclusion**: The historical backtester (`talonx_backtest`) represented TalonX's intraday
> execution behavior faithfully enough that its trade records could be treated as a proxy for how the live
> strategy would have traded historically.
>
> **New evidence**: Task 24 proved BEARISH signals opened new short positions in the backtester but are
> exit-only in live/paper (`talonx_paper`); Task 25A corrected the backtester's lifecycle to match, and in
> doing so confirmed the scale of the prior mismatch directly (73.5% of trades, 94.96% of gross positive R in
> the pre-fix 0bps baseline came from the now-removed short-opening path) and found it had also silently
> shaped the project's own canonical example datasets.
>
> **Updated conclusion**: Historical economic results produced by the pre-Task-25A backtester cannot represent
> canonical TalonX live economics and must not be cited as such going forward. Results produced by the
> corrected (post-Task-25A) engine are implementation-correct for the LONG_ONLY lifecycle, but no full
> historical re-run has yet been performed on it (see "No historical performance result" above) — a fresh
> economic evaluation remains a future task (Task 25 summary's original recommendation, still pending), not
> something this correctness-only task attempted to supply.
>
> **Reason**: trade lifecycle mismatch, not parameter/threshold performance — the defect was in *what
> counted as a trade*, not in how well any given trade was scored or gated.

---

## Task 25A.1 — Durable Long-Only Correction Checkpoint (2026-08-20)

**Purpose**: finalize, review, and durably commit/push the Task 25A long-only backtest correction after
three targeted lifecycle-risk reviews, before moving to live shadow capture.

**Pre-commit integrity**: HEAD confirmed at the expected checkpoint (`77769d259e9131047e505c3df8eb64c1aec32e27`)
before any staging; `git status --short` clean apart from untracked `logs/`.

**Three lifecycle risks reviewed, each with new deterministic regression coverage**:

1. **Pending SIGNAL_EXIT vs. same-bar STOP/TARGET ordering** — confirmed correct by construction (the
   pending-exit branch in `_process_symbol_bar` runs and closes the position, using only the bar's open,
   strictly before the stop/target `check_exit` branch further down even has a chance to run, since that
   branch is gated on `has_open`, already `False` by then). Proven with two new tests, one where a STOP
   would have hit later in the same bar and one where a TARGET would have — SIGNAL_EXIT wins both times,
   using the bar's open price, not the stop/target level or the bar's high/low.
2. **Duplicate/multiple bearish signals** — confirmed correct: the existing intra-flush cooldown recheck
   (unchanged, shared machinery) rejects a second same-bar BEARISH candidate before it can overwrite
   `_pending_exit`; a bearish candidate arriving on the fill bar of an already-resolved exit is rejected
   (`COOLDOWN` while still armed, `NO_ACTIVE_POSITION` once cleared) — never a duplicate close. Proven with
   two new tests.
3. **Loss-lockout semantics** — confirmed already correct (no code change needed): `_maybe_arm_loss_lockout`
   is a generic, direction-agnostic `net_pnl < 0` check that was never short-vs-long-aware in the first
   place; a BEARISH-while-flat no-op never creates a `Trade` at all, so it can never arm lockout; a losing
   `SIGNAL_EXIT` arms it exactly like a losing STOP would; a profitable `SIGNAL_EXIT` does not; and with
   shorts no longer openable at all, there is no code path left that could produce a losing short to arm
   risk state from. Proven with four new tests, including a structural confirmation that every trade's
   direction is BULLISH by construction.

8 new tests added to `tests/test_backtest_long_only_lifecycle.py` (21 total in that file). Full required
suite + both new lifecycle/contract files: 83/83 passed. Full `tests/ -k backtest`: 272 passed, 1 skipped
(pre-existing, unrelated), 15 xfailed (same set as Task 25A, all `strict=True` with a precise reason
referencing this correction, none hiding an unrelated failure), 0 failed.

**Committed**: `1e28647c3f04b9a07d00f7c8f0a7bb1143c80f91` — `fix(backtest): align intraday lifecycle with
long-only paper semantics`. Staged individually (never `git add -A`/`.`): `talonx_backtest/engine.py`,
`execution.py`, `portfolio.py`, the two new test files, three adjusted test files, and this ledger.
Reviewed staged diff for secrets before committing (none found). `results/`, `data/`, `logs/` excluded (all
`.gitignore`'d project-wide, per long-standing convention).

**Pushed**: `origin/research/talonx-strategy-validation` (`77769d2..1e28647`). Draft PR #10 confirmed
updated to the new commit, still open, still draft — not merged.

**No strategy/threshold/gate-ordering value was changed.** No new historical replay was run. No Task 22
OOS outcomes were inspected.

---

## Task 25-LIVE-CAPTURE — Live Shadow Evidence Capture — 2026-08-20

**Purpose**: correctness/parity evidence only — capturing today's live TalonX behavior as a flight-recorder
dataset for later deterministic replay against the corrected (Task 25A) backtest engine, once Task 25B
(live fill-geometry reconciliation) is also resolved. **No profitability interpretation** — no total R,
P&L, profit factor, expectancy, win rate, or "did today's signal work" judgment is recorded anywhere in
this capture, by design.

**Method**: a new, read-only observational script (`scripts/task25_live_shadow_capture.py`) subscribes to
the Redis channels every TalonX module already publishes to (`talonx:market:stream`,
`talonx:signals:quant`, `talonx:quant:rejected`, `talonx:alerts:dispatch`, `talonx:paper:trades`,
`talonx:ingest:ws_heartbeat`) and periodically polls (read-only) `talonx_paper`'s existing SQLite store for
ignored-decision rows not otherwise published. No production module was modified; no trading logic was
touched. The live pipeline itself (`run_talonx.py`) was started with its periodic filing/earnings-ingestion
jobs skipped (irrelevant to intraday quant/paper decisions) but every intraday-relevant module (market
data, quant, brain, core, dispatch, paper trading) running with completely unmodified logic.

**Commit SHA used**: `1e28647c3f04b9a07d00f7c8f0a7bb1143c80f91` (recorded at capture start, post-Task-25A-push);
the ledger/script commit `c1fcc9eb158cd66571a75226000857a7693991c5` landed after capture had already started
and changed no module the capture observes. Strategy fingerprint (`get_strategy_version()`): `88529b8a3fa1`.
Default `QuantConfig` fingerprint (`config_hash`): `9174f5232c20`. Neither changed during the session.

**Symbols**: 8 of the 10 requested research symbols are present in the current production watchlist and
were captured — AAPL, MSFT, NVDA, AMD, TSLA, GOOGL, PYPL, STX. **AMZN and META are not in the current
watchlist and were not added** (per instruction, not changing the production watchlist for this
experiment) — never captured, never backfilled from downloaded history. Full artifact list:
`results/task25_live_shadow_2026-08-20/` (`live_session_manifest.json`, `live_bars.csv`,
`live_indicator_trace.csv`, `live_candidate_trace.csv`, `live_gate_trace.csv`, `live_quant_outputs.csv`,
`live_paper_state_transitions.csv`, `live_runtime_events.csv`, `live_data_quality.json`,
`live_shadow_summary.md`) — file SHA-256 hashes recorded in `live_session_manifest.json`.

**Exact start/end**: started `2026-08-20T13:05:37Z` (09:05:37 ET / 14:05:37 London), stopped
`2026-08-20T20:12:54Z` (16:12:54 ET / 21:12:54 London) — covering both Window A (premarket → opening →
normal session) and Window B (15:15-16:05 ET closing window) in full. Stopped via SIGINT first (matching
`run_talonx.py`'s documented Ctrl+C path), escalated to SIGTERM after neither process logged a clean
shutdown message within 8s (a known git-bash-to-Windows-python.exe signal-delivery limitation on this
host); both confirmed gone within 5s of SIGTERM. Every capture row is flushed to disk immediately on write,
so no already-processed event was lost, but no explicit clean-shutdown log line was captured — recorded
honestly, not claimed. Shutdown reason: `NORMAL_SESSION_COMPLETE` (the trading day had already fully
elapsed at stop time).

**Final counts**: 9,946 bars (all 8 symbols); 3,116 gate rejections (3,109 `LOW_VOLATILITY`, 6
`LOW_CONFLUENCE`, 1 `TREND_GATE` — the 7 non-volatility rejections all on STX, 09:46-11:06 ET, none near the
closing blackout or EOD-flatten checkpoint); **0 candidates published all session**; 0 paper-state
transitions; 0 special events flagged (none of scenarios A-G occurred, since no candidate was ever
published).

**Runtime stability**: 0 Redis disconnects, 0 handler errors, 0 out-of-order bars, 0 duplicate bars, 0
paper-store poll errors, 0 process restarts, no host sleep/interruption. 32 premarket bar-cadence gap
observations, all before 09:30 ET regular-session open, zero after.

**Data-fidelity observations** (classified `DATA_PROVIDER_OBSERVATION`, not strategy bugs, provider
behavior not modified): (A) premarket bars arrived sparsely (~270-465s gaps per symbol) despite the 12s
poll interval; (B) premarket volume reported as 0.0 for every bar; (C) no cadence anomaly after 09:30 ET
regular-session open.

**Scenarios not exercised**: `SIGNAL_LIFECYCLE_OBSERVATION` = INCONCLUSIVE, `REAL_SIGNAL_LIVE_BACKTEST_PARITY`
= NOT_EXERCISED, `LIVE_FILL_GEOMETRY_OBSERVATION` = NOT_EXERCISED — no qualifying signal was published for
these 8 symbols today under production-default thresholds, so no lifecycle behavior (bearish-while-flat,
bearish-while-long, blackout handling, EOD flatten of a real position, live fill geometry) could be
observed from a real signal. **No inference about strategy quality is drawn from this** — it is an honest
result about today's specific market conditions/symbol set, not a capture defect (infrastructure and data
flow are both GREEN) and not a profitability judgment.

**No profitability interpretation**: no total R, P&L, profit factor, expectancy, win rate, or "did today's
signal work" judgment is recorded anywhere in this capture.

**Task 22 status**: unchanged, `OOS_SUSPENDED_PENDING_CANONICAL_LONG_ONLY_BASELINE`. Frozen spec hash
`9c15d11c021dddbd` untouched; no new OOS outcomes inspected.

**No replay performed**: today's 9,946 captured bars have deliberately NOT been replayed through the
backtester — that is planned as a later task, after Task 25B (live fill-geometry reconciliation) is
resolved.

**Final decision**: `LIVE_SHADOW_CAPTURE_COMPLETE`.

---

## Task 25B — Live Fill-Geometry Reconciliation (2026-08-20)

**Task 24 P1 finding being addressed**: `talonx_backtest` re-anchors a position's stop/target to the actual
fill price when a gap invalidates the pre-fill geometry (`_finalize_fill_geometry`, Task 13B);
`talonx_paper` had no equivalent — stop/target were persisted verbatim from the screening `QuantSignal`,
never validated against the actual (spread-shifted) fill price.

**Architecture traced first** (full detail: `results/task25b_live_fill_geometry/live_fill_architecture.md`):
`talonx_paper`'s own wire contract (`TriggeringSignalRef`) carries only `price`/`stop_price`/`target_price`
— no `atr`, no `pivot_resistance`/`pivot_support` — and `talonx_paper` imports nothing from `talonx_quant`
anywhere in the codebase, a project-wide, deliberate convention every live module honors (confirmed via
grep across `talonx_core`/`talonx_brain`/`talonx_dispatch` too; the one documented exception anywhere is
`talonx_backtest`, an explicit research-replay tool). Pydantic's default `extra="ignore"` silently drops
`atr`/pivot fields from the wire payload even though `talonx_core` publishes them, because
`TriggeringSignalRef` never declares them. Safe canonical recomputation is therefore genuinely unavailable
without either a first-of-its-kind live-module cross-import (breaking the established boundary) or
duplicating the geometry formula (explicitly forbidden).

**Selected solution**: fail-closed validation against the ORIGINAL screening-time stop/target bracket, no
live-side recomputation — the task's own "Option C" fallback. New pure function
`talonx_paper/engine.py::fill_geometry_is_valid(fill_price, stop_price, target_price)`, wired into
`talonx_paper/consumer.py::_execute_buy` before any sizing/persistence step; rejects
(`FILL_GEOMETRY_INVALID`, via the existing `record_ignored` audit path) rather than persisting an invalid
position.

**Alternatives rejected**: (A) direct reuse of `calculate_trade_geometry` — would break the project's only
consistently-honored live-module boundary; (B) carry geometry metadata into execution and recompute — still
requires the formula itself, which duplication is forbidden from reproducing.

**Files changed**: `talonx_paper/engine.py`, `talonx_paper/consumer.py`, `tests/test_paper_engine.py` (8
new tests), `tests/test_paper_consumer.py` (5 new tests). No changes to `talonx_quant/*`,
`talonx_backtest/*`, `talonx_core/*`, `talonx_dispatch/*`; no strategy/threshold/long-only/blackout/EOD/
frozen-spec value touched.

**Tests**: 146 passed (new fill-geometry tests + fill_geometry.py + live/backtest contract + long-only
lifecycle + execution). Full paper+backtest sweep: 442 passed, 1 skipped (pre-existing), 15 xfailed
(unchanged set), 0 failed.

**Geometry contract parity result** (6 identical signal+fill scenarios run through both
`BacktestEngine._finalize_fill_geometry` and `fill_geometry_is_valid` directly — real code, not
hypothetical; see `results/task25b_live_fill_geometry/geometry_contract_matrix.csv`): **PARITY** on 3/6
(fill-inside-bracket; a target-breach where backtest's own recompute also fails its R:R gate; missing-data
passthrough) and **DIVERGENT** on 3/6 (stop-side breaches, including one exact-boundary and one severe gap)
where `talonx_backtest` safely re-anchors using still-valid pivot data and `talonx_paper`, lacking that
data, rejects the identical fill outright. `talonx_paper` is strictly more conservative in every divergent
case — it never opens a worse-than-screened position, but forgoes some entries the backtest would accept.

**Remaining gaps** (full detail: `results/task25b_live_fill_geometry/remaining_gaps.md`): no live-side
recomputation capability (architecturally unavailable without a real design change, not an oversight);
spec tests D/F from the task's own list don't literally apply under this architecture (documented why);
screening-vs-execution R:R distinction doesn't apply (`talonx_paper` has no R:R field at all); `execute_sell`
(exits) deliberately untouched, matching the backtest's own entry-only scope.

**No performance analysis performed** — no P&L/R/expectancy/win-rate was computed or compared. No Task 22
OOS outcomes inspected; frozen spec hash `9c15d11c021dddbd` untouched.

**Final decision**: `LIVE_FILL_GEOMETRY_VALIDATED_WITH_CAVEATS` — the fix is correct, safe, fail-closed,
deterministically tested, and never persists an invalid position, but does not achieve full outcome parity
with the backtest on stop-side breaches (an honest, evidence-based caveat, not a failure).

**State**: reviewed and committed as `6e15bc4` (`fix(paper): fail closed on invalid live fill geometry`),
pushed to `origin/research/talonx-strategy-validation`. PR #10 confirmed still draft/open, not merged.
Commit SHA itself recorded in a small follow-up docs commit, `78498b2`.

---

## Task 25C — Live-Captured Data Deterministic Replay & Decision-Parity Audit (2026-08-20)

**Objective**: given the exact live-captured 2026-08-20 market evidence
(`results/task25_live_shadow_2026-08-20/`), determine whether a deterministic replay of the same captured
bars through the corrected (Task 25A/25B) pipeline reproduces TalonX's live decisions at the
indicator/gate/candidate/published-signal level — a correctness/parity audit, not a profitability backtest.

**Task 25B checkpoint SHA used as the base**: `78498b2d151b4c638c65d3526dad09f9d6583104`.

**Result: halted at the input-integrity gate before any replay was performed.**

Before replay, this task recomputed SHA-256 hashes for the six live-capture files named in the task
instruction and compared them against `live_session_manifest.json`'s recorded values from Task
25-LIVE-CAPTURE's prior "finalization." **Three of six mismatched** (`live_bars.csv`, `live_gate_trace.csv`,
`live_quant_outputs.csv`; the other three matched only because they stayed empty throughout, not because
they were genuinely frozen).

**Root cause (confirmed via direct process inspection, not assumed)**: a live Windows process inventory
found **four `python.exe` processes still running** — a `.venv/Scripts/` launcher/shim paired with a
separate `pythoncore-3.12-64/python.exe` real worker, for each of `run_talonx.py` (PIDs 8364/12060) and the
capture script (PIDs 16700/21912). Task 25-LIVE-CAPTURE's earlier "graceful stop" sent SIGINT/SIGTERM via
git-bash's `kill` to bash's own job-table PIDs, which never corresponded to these real Windows PIDs — the
same class of PID-shim mismatch already documented elsewhere in this project's operational history,
independently reconfirmed here for ad-hoc background processes. The capture silently kept running and
appending real data for roughly 24 more minutes after being reported "stopped" (`live_bars.csv` grew from
9,946 to 10,529 rows; `live_gate_trace.csv`/`live_quant_outputs.csv` from 3,116 to 3,300) until this task's
integrity check caught it.

**Corrective action** (separate from, not a substitute for, the halted replay): all four processes located
and terminated (PowerShell `Stop-Process -Force`), confirmed via `tasklist` showing zero remaining
`python.exe` processes. The dataset is now genuinely frozen at the corrected counts above, giving a stable
starting point for a future re-attempt — this does not retroactively validate or complete this task's own
replay, which never ran.

**Instruction compliance**: per explicit instruction, no replay/indicator/session/candidate/gate/
published-signal comparison, first-divergence trace, or determinism check was performed. All 15 required
artifact files exist in `results/task25c_live_replay_parity/`; most are explicit `NOT_PRODUCED` placeholders
rather than populated analysis. Parity metrics (BAR_COUNT/SESSION/INDICATOR/RAW_CANDIDATE/GATE_EVENT/
REJECTION_REASON/PUBLISHED_SIGNAL) are all `NOT_EXERCISED` this run.

**What remains unexercised**: unchanged from Task 25-LIVE-CAPTURE's own finding — bullish entry fill,
bearish signal exit, live fill geometry, EOD flatten of a real position, stop/target lifecycle all remain
`NOT_EXERCISED_ON_REAL_SIGNAL`; this task adds no new information on that front.

**No profitability interpretation.** No P&L/R/expectancy/win-rate was computed. No Task 22 OOS outcomes
inspected; frozen spec hash `9c15d11c021dddbd` untouched. No production code was changed in this task.

**Focused tests** (run independently of the integrity finding, §21): 184 passed, 0 failed (live/backtest
contract, long-only lifecycle, fill geometry, lookahead, session classification, reproducibility/determinism
machinery).

**Final decision**: `INPUT_CAPTURE_MUTATED`.

**Next recommended action (not started)**: re-attempt Task 25C against the now-genuinely-frozen dataset
(10,529 bars / 3,300 rejections / 0 published) — re-verify hash stability across two consecutive checks
first, then perform the full replay/parity comparison this task was supposed to perform. This is a re-run
of the same task, not a new one; the mismatch was an operational process-management issue, not a code
defect, so no code fix is implied.

---

## Task 25C Re-attempt — Deterministic Replay Against the Genuinely Frozen Dataset (2026-08-20)

**Previous**: `INPUT_CAPTURE_MUTATED`.

**New evidence**: a follow-up process inventory (PowerShell `Get-CimInstance`, `tasklist` via two
independent tools) found zero remaining `python.exe` processes — the four real Windows workers identified
during the first attempt had already been terminated. A mandatory two-check hash-stability test (108
seconds apart) found all 8 checked capture files byte-identical across both checks.

**Correction**: the dataset is genuinely frozen. New canonical snapshot established: **10,529 bars, 3,300
gate rejections (3,293 LOW_VOLATILITY, 6 LOW_CONFLUENCE, 1 TREND_GATE), 0 published candidates, 0 paper-state
transitions** — explicitly superseding, not deleting, the earlier invalid 9,946-bar snapshot. Full detail:
`results/task25_live_shadow_2026-08-20/corrected_capture_manifest.json` and
`capture_freeze_verification.json`.

**Replay performed**: 10,521 of 10,529 rows (8 rows with null OHLV at the exact instant of market open
excluded, not repaired) fed through the existing `BacktestEngine`, `QuantConfig()` production defaults,
cold-start buffer (no pre-seed, per the explicit no-backfill instruction). **Determinism confirmed** — two
independent runs produced an identical SHA-256 fingerprint over the full signal log, rejection list, and
trade list.

**Session/blackout parity**: confirmed — all 10 boundary spot-checks (09:30/09:45/15:30/15:50/16:00 ET, ±1s)
matched documented rules exactly.

**Published-signal parity**: confirmed and meaningfully robust — live 0 published, replay 0 published/0
trades, despite replay generating 737 raw candidates (vs. live's heavily-suppressed rate) and reaching gate
stages live rarely got to. This independently strengthens confidence in the zero-publication result, since
it held under a materially *less* restrictive replay condition.

**First divergence, root-caused**: `AAPL, 2026-08-20T13:15:00Z` — live rejected as `LOW_VOLATILITY`; replay's
buffer wasn't warm yet. Traced conclusively via `run_talonx_stderr.log`: `run_talonx.py` pre-seeded **120
bars of real historical 1-minute data per symbol via yfinance at process startup**, before the capture
script began subscribing — this state is genuinely absent from `live_bars.csv` and cannot be reproduced
without a fresh historical fetch (fabrication, explicitly forbidden). A direct diagnostic measurement
confirmed replay's own `atr_pct` (1.15%–4.98% across sampled symbols) never fell below the 0.25%
`min_atr_pct` threshold, while live rejected 99.8% of all gate-checked bars as `LOW_VOLATILITY` — the gate
formula and threshold are identical, shared code; this is a missing-initial-state divergence, not a logic
bug. Essentially every downstream candidate/gate-count difference (replay's much higher raw-candidate rate,
its LOW_CONFLUENCE/TREND_GATE/LOW_RISK_REWARD/CLOSING_BLACKOUT/US_MARKET_SESSION_CLOSED events) traces to
this single cause, independently corroborated via a gate-ordering sanity check. One residual is honestly
unresolved: why live's low-ATR reading persisted the entire session rather than tapering once pre-seed bars
should have rolled out of the buffer — not conclusively re-derivable without inspecting the terminated
process's actual runtime state, recorded as an open question rather than assumed away.

**What remains unexercised**: unchanged — bullish entry fill, bearish signal exit, live fill geometry, EOD
flatten of a real position, stop/target lifecycle all remain `NOT_EXERCISED_ON_REAL_SIGNAL`.

**No profitability interpretation.** No P&L/R/expectancy/win-rate computed. No Task 22 OOS outcomes
inspected; frozen spec hash `9c15d11c021dddbd` untouched. No production code changed — the replay itself
was a standalone diagnostic script, left uncommitted per instruction.

**Focused tests** (§20): 99 passed, 0 failed (long-only lifecycle, live/backtest contract, session
classification, fill geometry, lookahead, reproducibility/determinism).

**Final decision**: `INCONCLUSIVE_DUE_TO_MISSING_INITIAL_STATE`. Not `PARITY_BROKEN` (no logic/config/
gate-ordering defect found anywhere checked); not `PARITY_CONFIRMED` (the dominant gate layer, 99.8% of
live's actual decisions, could not be verified at all).

**Next recommended action (not started)**: do not re-run Task 25C against this same dataset — the missing
initial state cannot be recovered from it. If future indicator/gate-level parity is wanted, a future live
capture should additionally record (read-only) each symbol's pre-seeded buffer contents at startup — a
capture-tooling suggestion, not started here.

---

## Task 26 — Canonical Corrected Long-Only Historical Baseline (2026-08-20/21)

**Objective**: establish the FIRST canonical historical performance baseline for the corrected LONG-ONLY
TalonX system (Task 25A/25A.1 lifecycle), at the frozen official configuration, over the complete Task7B
Alpaca discovery dataset. Not parameter optimization — exactly one configuration, one pass.

**Why old Tasks 8–22 economic results cannot represent canonical live economics**: every prior full-population
economic figure (Task 8: 93 trades/−13.24R; Task 13B: 181 trades/+75.98R) was generated by a backtest engine
that opened a genuine short on every BEARISH `QuantSignal` (Task 24's finding, fixed by Task 25A/25A.1).
~73.5% of those trades and ~95% of their gross positive R came from a trade type canonical `talonx_paper`
never opens. Task 26 is the first run of this entire research track on the corrected engine.

**Git/reproducibility**: HEAD `900908cee47d581d755c8bea2471bab52c769e18`, working tree clean apart from
untracked `logs/`. `QuantConfig` hash `9174f5232c20`, full `BacktestConfig` hash (engine-native)
`19654e22ffd5`, strategy version `88529b8a3fa1`. Dataset hash (project-canonical `get_dataset_hash`)
`5e5412a960bf` — matches this same dataset's previously-established hash from earlier tasks, independently
confirming dataset identity. Dataset: 1,903,044 bars, 10 symbols (AAPL/MSFT/NVDA/AMZN/META/AMD/TSLA/GOOGL/
PYPL/STX), 2025-08-15 to 2026-08-14, Alpaca SIP, no redownload/extension/substitution/repair. Quality clean
(0 duplicates/out-of-order/NaN/Inf/negative-volume/invalid-OHLC); "unexpected" gaps present, the same
previously-deferred holiday false-positive pattern, still documented not fixed.

**Configuration**: pure `QuantConfig()` production defaults confirmed against every value named in the task
instruction (min_atr_pct=0.25%, RSI 30/70, volume 2x/premarket 3x, ATR move 1.0x/stop 1.5x/reward 2.0x, R:R
1.5, cooldown 20min, confluence≥2, Opportunity Score weights default) — zero overrides, one pass only.

**Focused correctness suite** (§5 gate, run before the historical replay): 127 passed, 0 failed
(long-only lifecycle, live/backtest contract, fill geometry, lookahead, reproducibility, execution,
session). Gate cleared.

**Run**: 22:14:35 → 02:33:03 (256.4 minutes) over the full 1,903,044-bar dataset via `BacktestEngine`
directly (no alternate strategy implementation).

**Signal funnel**: 5,021 raw candidates (194 RSI curl, 4,725 MACD cross, 102 MA cross) → 1,781,848
LOW_VOLATILITY bar-level rejections + 4,995 candidate-level rejections across 10 other reasons (dominated by
LOW_CONFLUENCE=3,255) → **85 published** (26 bullish, 59 bearish-while-flat, 0 bearish-used-as-SIGNAL_EXIT)
→ **26 executed long entries, 26 completed trades**.

**Zero-short invariant**: `CONFIRMED` — all 26 trades `direction=bullish`, geometry invariant
(`stop<entry<target`) valid for all 26. Not `LONG_ONLY_INVARIANT_BROKEN`.

**Exit-path decomposition**: STOP 18 (−18.0R, median 4min), TARGET 3 (+8.15R, median 14min),
END_OF_SESSION 5 (+14.14R, median 2.6hr), **SIGNAL_EXIT 0** — fully reconciled as a consequence of few
trades + short holding times relative to a full year, not a bug (talonx_paper's own synthetic contract
tests already prove the mechanism works when the state aligns).

**Baseline performance (0bps)**: 26 trades, 8W/18L/0BE, win rate 30.77% (95% CI 13.0–48.5%), gross total
+4.289R, expectancy +0.165R/trade (95% CI −0.63 to +0.96), profit factor 1.238, max drawdown −5.76R.

**Cost sensitivity** (derived from the frozen 0bps trade set's raw prices via the existing cost-application
functions, not by re-running the engine 3 more times — proven equivalent since gate/geometry decisions are
cost-invariant by construction): 0bps +4.29R → 5bps −4.64R → 10bps −13.56R → 20bps −31.41R. Trade count
identical (26) across every scenario.

**Symbol decomposition**: 5/10 symbols (AAPL, AMZN, GOOGL, META, MSFT) produced zero trades over the full
year despite having raw candidates (71–207 each). STX produced the most candidates (1,994) and trades
(15/26, +6.78R). Winner-only concentration: STX = 75.3% of positive R; STX+AMD+PYPL = 100% of positive R.

**Holding-time pattern**: the previously-observed short-STOP/long-winner pattern persists after removing
shorts (STOP median 4min vs. TARGET/EOD medians of 14min/2.6hr).

**Old vs. new population** (diagnostics only, not a benchmark): old mixed-direction populations (93 and 181
trades at different `min_atr_pct` thresholds) are not directly comparable to the new 26-trade canonical
population on either count basis; no improvement/regression claim drawn.

**Determinism**: `CONFIRMED` via a bounded 70,320-bar/2-week/10-symbol spot-check run twice (identical
SHA-256 fingerprint) plus the 31-test reproducibility suite plus Task 25C's own same-day full-scale 2x-run
proof. A literal second full 1.9M-bar run was not performed (would double an already 256-minute run).

**What remains unproven**: statistical power (n=26, CIs spanning zero), cost robustness (edge erased by
5bps), symbol generalization (edge concentrated in 2-3 of 10 symbols), live/replay indicator-level parity
(Task 25C's unresolved gap).

**Task 25C observability follow-up** (recorded, not acted on): a future live shadow capture must persist
the exact startup indicator seed/warmup state for true indicator-level live/replay parity.

**Task 22 status**: unchanged, `OOS_SUSPENDED_PENDING_CANONICAL_LONG_ONLY_BASELINE`. Frozen spec hash
`9c15d11c021dddbd` untouched. No post-Aug-17 outcomes inspected, no retraining, no early-exit tuning.

**Final decision**: `CANONICAL_BASELINE_ESTABLISHED_BUT_EDGE_UNPROVEN` — the baseline process itself
(correctness, zero-short invariant, determinism, full documentation) succeeded; the underlying edge did
not reach a size/robustness that n=26 trades and 5bps of cost can support asserting either way.

**Next recommended action (not started)**: reassess whether Task 22's OOS suspension can now be formally
revisited, given a canonical long-only baseline now exists — without changing the frozen spec, retraining,
or treating this small-sample result as tuning grounds.

**State**: results/diff returned for review — **not committed, not pushed**, per instruction. All 18
required artifacts written to `results/task26_canonical_long_only_baseline/`.

---

## Task 27 — Strategy Feasibility & Gate Interaction Audit (2026-08-21)

**Objective**: explain WHY the canonical corrected long-only strategy is so selective (26 trades from 5,021
raw candidates from 1,903,044 bars, per Task 26), distinguishing deliberate design, independently-reasonable
filters interacting restrictively, or an actual implementation/requirements contradiction. Explicitly not
parameter tuning — no alternate thresholds of any kind were run.

**Method**: a second full-dataset diagnostic pass reusing only existing, imported `talonx_quant` functions
(no reimplemented logic) alongside the same frozen `QuantConfig`, over the same Task 26 dataset. Produced
`_bar_flags.parquet` (1,901,854 warm bars) and `_candidates_full.csv` (5,021 candidates). Cross-validated
against Task 26: candidate count matches exactly; independently-reconstructed confluence scores match the
recorded `confluence_score` with 0/5,021 mismatches.

**Effective strategy contract** (`effective_strategy_contract.md`): every family's trigger, per-family
preconditions, confluence formula, and the full 13-stage downstream gate order transcribed verbatim from
`talonx_quant/strategy.py`/`consumer.py`.

**RSI curl / confluence audit (highest priority)**: confirmed empirically that 0/194 real RSI-curl candidates
ever had their own RSI value support their own confluence leg — structurally mutually exclusive on the
trigger bar (re-confirming Task 24's analytical finding with full-population evidence). 92.3% of RSI-curl
candidates (179/194) are permanently capped at confluence=1; only 7.7% (15/194) reach the gate minimum via a
coincident MACD cross + volume surge. Classification unchanged: `REQUIREMENT_AMBIGUOUS` — no doc/commit
anywhere states the intended interaction.

**MACD feasibility**: 4,725 candidates. MACD's own cross always contributes its point (no self-exclusion);
91.9% (4,343/4,725) still fail confluence because neither RSI-extreme nor volume-surge coincides on the same
bar. ATR-filter-survival alone exactly predicts MACD's real candidate count.

**MA crossover feasibility**: the dominant bottleneck is the 0.15% spread hysteresis (0.31% of raw
crossovers clear it), not the ATR-move filter (41.6% clear that alone). Small ~7%/4% unreconciled gap between
independently-computed "both filters clear" (59/49) and actual generated (55/47), not chased further given
the no-re-run constraint. 98% of the 102 actual MA candidates fail confluence (MA-cross contributes zero
confluence points itself).

**ATR filter stacking**: `min_atr_pct` (bar-level) and `atr_move_multiplier` (per-trigger) confirmed
structurally distinct and independently quantified (`atr_filter_interaction.csv`). 93.7% of all warm bars
fail `min_atr_pct`; 62.1% fail `atr_move`.

**Confluence component matrix**: overall combo distribution 000=84, 001=192, 100=4,346, 101=367, 110=32,
**111=0 — never observed** across all 5,021 candidates (empirical rarity, not proven structurally impossible,
unlike RSI curl's proven case).

**Order-dependence** (`first_failure_vs_all_failures.csv`): all 930 `OPENING_BLACKOUT`-first-failure
candidates would also independently fail confluence — opening-blackout is never the sole real blocker. Of
3,651 `LOW_CONFLUENCE`-first-failure candidates, 1,219 fail only confluence and 2,432 would also fail a
downstream gate. Task 26's first-failure-only rejection histogram can understate downstream-gate selectivity;
this is a reporting/interpretation risk, not a code defect (gate order itself is deliberate and
live-matching, per Task 24).

**R:R/pivot audit**: 74.2% (3,727/5,021) of candidates have `risk_reward_ratio` populated. The gating factor
for the remaining 25.8% is a structural pivot on the wrong side of price or an ATR-fallback target, not
missing pivot data (pivot data is present for essentially all candidates once warm).

**Direction asymmetry**: confirmed exhaustively that `trend_gate_applicable=0` for all 2,533 bearish
candidates (zero exceptions), vs. 1,874/2,488 (75.3%) for bullish, of which 942 (37.9% of all bullish
candidates) then fail the trend gate itself. Matches `_trend_gate_applicable`'s own code condition exactly;
classified as an intentional asymmetry consistent with LONG_ONLY design, not a bug.

**SIGNAL_EXIT feasibility** (`signal_exit_feasibility.csv`): for all 26 Task 26 trades, checked every bearish
candidate for the same symbol during the exact holding window. 21/26 trades (80.8%) had zero bearish raw
candidates at all while open; the other 5/26 had bearish candidates, and 100% of those (5/5) failed
confluence — the same bottleneck that blocks candidates strategy-wide. 0/26 had a bearish candidate published
or failing on any other gate while open. SIGNAL_EXIT's absence (0/85 published signals ever used as
SIGNAL_EXIT) is a compounded-selectivity outcome, not a broken mechanism.

**Live-day vs. historical comparison** (`live_day_vs_history.csv`): 2026-08-20 live day (52 candidates, 0
published) broadly consistent with the full-year candidate-rejection profile (LOW_CONFLUENCE share 67.3% live
vs. 65.2% full year); other deltas within normal n=52 sample noise. No live-day outcome/P&L inspected.

**Documentation/test gaps** (`documentation_test_gaps.csv`, 5 rows): one `STALE_DOC` (config.py confluence
comment), the RSI-curl/confluence interaction re-confirmed `REQUIREMENT_AMBIGUOUS`, two `TEST_GAP` findings
(RSI-curl+own-confluence-leg untested; MA-cross own confluence score untested end-to-end), one
`AMBIGUOUS_REQUIREMENT` (first-failure histogram interpretation risk).

**Focused correctness suite**: 236 passed, 1 skipped, 15 xfailed, 0 failed — same composition as Task 26's
gate.

**Bugs vs. design ambiguities**: no implementation bugs found — every gate condition matches its own code
exactly, and every cross-validation check (candidate count, confluence-score reconstruction, MACD ATR-filter
prediction) had zero discrepancies. Three open design/documentation items remain: (1) RSI-curl/confluence
self-exclusion with no stated intent (highest priority, unresolved across two tasks), (2) the stale
config.py comment, (3) the first-failure-histogram interpretation risk.

**Final decision**: `MULTIPLE_STRATEGY_DESIGN_ISSUES_REQUIRE_RESOLUTION` — the strategy's selectivity is
fully explained by a chain of individually-coherent filters stacking multiplicatively (not an unexplained
residual, not a bug), but the RSI-curl/confluence interaction has no documented intent anywhere despite two
rounds of investigation and materially caps that entire family's reach — combined with two smaller open
documentation items, this is judged as requiring conscious resolution rather than simply "coherent but
selective." Decision made independent of profitability, per instruction.

**Next recommended action (not started)**: resolve the RSI-curl/confluence interaction's intended semantics
with the strategy owner — a requirements decision, not a code change, not parameter tuning.

**State**: results/diff returned for review — **not committed, not pushed**, per instruction. All 15
required artifacts written to `results/task27_strategy_feasibility_audit/`.

---

## Task 28 — RSI Curl / Confluence Requirements Resolution (2026-08-21)

**Objective**: resolve the INTENDED meaning of the RSI confluence leg (state-based vs. event-based) for the
structural self-exclusion Task 24 and Task 27 both classified `REQUIREMENT_AMBIGUOUS`. A requirements/design
task — no parameter tuning, no performance experiment, no P&L calculation, no code change unless the evidence
strongly supported one.

**Task 27 checkpoint**: before this task's analysis, reviewed `git status`/`git diff` (only
`TALONX_RESEARCH_LEDGER.md` modified — the Task 26 and Task 27 entries, 189 insertions; no production
strategy code touched), staged only that file (not `git add -A`), committed as `d497c8c7cfa0c7915ba44411f5b23a44826291a8`
("docs(research): record Task 26 canonical baseline and Task 27 feasibility audit"), pushed to
`research/talonx-strategy-validation`. PR #10 confirmed still draft/open after push.

**Task 28 integrity**: HEAD `d497c8c7cfa0c7915ba44411f5b23a44826291a8` (unchanged through this task — no
further commits), git status clean apart from untracked `logs/`. Task26 dataset hash `5e5412a960bf`,
`QuantConfig` hash `9174f5232c20`, strategy fingerprint `88529b8a3fa1` — all unchanged, not touched. No
strategy code modified during requirements analysis.

**Requirements archaeology**: reviewed README, `docs/modules/quant.md`, all other `docs/*.md`, `config.py`,
`strategy.py` docstrings, full git history (origin commit `7b7d815`, 2026-08-16, which introduced BOTH
direction-aware confluence AND the RSI reversal curl as two unlinked commit-message bullets with zero
cross-reference; and follow-up correctness-audit commit `f2f0840`, which also missed the interaction), all
RSI/confluence tests, and the prior Task 24/27 ledger entries. Full evidence table (12 sources) in
`results/task28_rsi_confluence_requirement/requirements_evidence.csv`.

**Finding**: every direct statement of what the confluence RSI leg measures (`config.py:244-249`,
`strategy.py`'s `_confluence_score` docstring, `docs/modules/quant.md:104-112`) is consistent, repeated,
present-tense state language ("RSI currently/sitting in the extreme zone"), with explicit general-purpose
rationale ("must not silently pad a long setup's score"). Every direct statement of what the RSI-curl
trigger means uses event/confirmation language, but never discusses confluence, and neither side ever
discusses the interaction with the other.

**Truth table** (`rsi_truth_table.csv`, 12 boundary cases including the exact 30.0/70.0 threshold edge,
computed via the real `_confluence_score` function): confirms exceptionlessly — every one of the 6 fired-curl
rows has `rsi_confluence_leg_current_behavior=0` and `rsi_confluence_leg_event_interpretation=1`, zero
counter-examples.

**Signal-family consistency** (`signal_family_consistency.md`): MACD's apparent self-credit is a degenerate
coincidence (its trigger and confluence-leg condition are the literal same boolean), not a general policy. MA
crossover — a closer precedent, also edge-triggered — gets **zero** self-credit unconditionally, and this is
never flagged as a bug anywhere in this repository. RSI curl already gets partial self-credit via volume
(guaranteed by its own trigger definition), just not via the RSI leg specifically.

**Double-counting analysis** (`double_counting_analysis.md`): the system already operates on a
"trigger + one additional confirmation" model (per the MACD precedent). RSI curl's trigger already bundles
reversal + volume, and its volume leg already supplies that one automatic credit. A second automatic credit
via the RSI event leg, for the same underlying trigger firing, would be closer to double-crediting a single
trigger across two legs than to filling a genuine gap.

**RSI signal contract** (`rsi_signal_contract.md`): answer **B** — RSI reversal + volume only creates a
candidate; a same-bar MACD-cross coincidence is mathematically mandatory for publication under
`confluence_score_min=2`, given the confirmed state-based leg. A direct, calculable consequence of
already-confirmed rules, never previously written down; flagged as a naming/expectation mismatch worth the
strategy owner's attention (the signal's own name implies RSI+volume should be sufficient).

**Historical descriptive impact** (`historical_impact_without_pnl.csv`, built entirely from Task 27's
existing `rsi_curl_audit.csv`, no new engine run): of 194 real RSI-curl candidates, 194/194 have volume=1,
0/194 have the RSI state leg=1, 15/194 (7.7%) have a same-bar MACD coincidence and reach confluence=2 today,
179/194 (92.3%) are permanently capped at confluence=1. No P&L, trade-count, or hypothetical-execution claim
made.

**Test contract audit** (`test_contract_audit.csv`, 11 rows): 7 of 8 existing RSI/confluence tests classified
`IMPLEMENTATION_LOCKING` (lock in current behavior without stating why it's intended); 1
`REQUIREMENT_PROVING` (but for the MACD family, not RSI). 4 `MISSING` categories, most notably: no test
anywhere fires an RSI-curl signal and asserts its resulting `confluence_score`, and no test uses the exact
30.0/70.0 boundary values.

**Documentation issues** (`documentation_corrections.md`): `STALE_DOC` at `config.py:244-249` ("computed once
per bar" — should read "computed fresh per signal direction"), with a proposed new explicit note on the
RSI-curl self-exclusion consequence; proposed cross-reference addition to `docs/modules/quant.md`'s RSI
Reversal Curl bullet; proposed clarification to `docs/modules/quant.md`'s Rejection Trace Logging section
that rejection counts are first-failure-only, not independent-gate-failure counts. None applied — text-only,
returned for review.

**What is proven vs. ambiguous**: proven — the RSI confluence leg's documented definition is state-based,
consistently, across three independent sources, with explicit rationale; the structural self-exclusion is a
correct, deterministic consequence of that definition; no implementation bug exists. Remains ambiguous —
whether the specific consequence for RSI-curl candidates (92.3% capped, mandatory unrelated MACD coincidence)
was ever a deliberately *wanted* product outcome, as opposed to an uncalculated by-product of two features
shipped in the same commit; this is a product judgment, explicitly out of this task's scope.

**Final requirement decision**: `RSI_CONFLUENCE_STATE_BASED_CONFIRMED` — strongly supported by consistent,
repeated, authoritative documentation of the leg's own definition, reinforced by the double-counting analysis
and the MA-crossover precedent (zero self-credit is already an accepted pattern elsewhere in this same
strategy).

**Code change required**: **NO**. Current code already matches the confirmed requirement exactly. Per the
task's rule for a state-based confirmation, the previously undocumented consequence is now written down
explicitly (`rsi_signal_contract.md`, plus proposed — not applied — doc corrections above), rather than any
threshold/formula/gate change.

**Next recommended action (not started)**: document/lock the requirement with tests (add an end-to-end test
firing a real RSI-curl signal and asserting its resulting `confluence_score` at both the interior and exact
30.0/70.0 boundary), then separately reassess whether the strategy's extreme selectivity (Task 27's finding)
is acceptable as a product/research objective given this now-confirmed and documented constraint.

**State**: Task 27 checkpoint committed and pushed (`d497c8c7cfa0c7915ba44411f5b23a44826291a8`). Task 28
research artifacts and this ledger entry — **not committed, not pushed**, per instruction. No strategy code
changed. PR #10 remains draft. All 10 required artifacts written to
`results/task28_rsi_confluence_requirement/`.

---

## Task 29 — Lock Confirmed RSI-Confluence Contract (2026-08-21)

**Objective**: make Task 28's confirmed requirement (`RSI_CONFLUENCE_STATE_BASED_CONFIRMED`) permanent and
explicit in tests, correct stale/ambiguous documentation, and prevent a future developer from accidentally
"fixing" the confirmed behavior. No strategy behavior change, no performance experiments.

**Task 28 checkpoint**: before this task's changes, confirmed HEAD `d497c8c7cfa0c7915ba44411f5b23a44826291a8`,
git status showing only the Task 28 ledger entry modified plus untracked `logs/`, and all 11 Task 28
artifacts present in `results/task28_rsi_confluence_requirement/`. Staged only the ledger file (not
`git add -A`), committed as **`820332bfb9c1479e8a7cedcc38d104a7324ce1fa`**
(`docs(research): record RSI confluence requirements resolution`), pushed to
`research/talonx-strategy-validation`. PR #10 confirmed still draft/open after push.

**No strategy code change**: `talonx_quant/strategy.py` untouched. The only production file touched is
`talonx_quant/config.py`, and only its comments — verified via `git diff` that zero non-comment, non-blank
lines changed.

**Requirement-proving tests added** (12 total, all classified `REQUIREMENT_PROVING`, none reading a
`results/` artifact at runtime — see `results/task29_rsi_contract_lock/requirement_test_matrix.csv`):
- 4 in `tests/test_quant_strategy.py` for contract cases A-D (bullish/bearish RSI curl, with/without a
  coincident MACD cross), via the real `evaluate_signals`, asserting `confluence_score==1` without MACD and
  `==2` with — exactly matching the confirmed contract.
- 6 exact 30/70 boundary tests (29.9→30.0, 30.0→31.0, 28.0→29.9 bullish; 70.1→70.0, 70.0→69.0, 72.0→70.1
  bearish), each asserting both the curl-fires boolean and the confluence RSI-state leg value — confirms the
  trigger's inclusive recovery check and the confluence leg's strict current-state check are complementary
  at every point, including exactly at 30.0/70.0.
- 2 in `tests/test_quant_consumer.py` through the real `QuantScanner._handle_message` gate path (consistent
  with this file's own established boundary of stubbing `evaluate_signals`, so the injected confluence
  values are the exact values the strategy-level tests above independently prove): confluence=1 rejected
  `LOW_CONFLUENCE`, confluence=2 clears the gate and reaches `_pending_candidates` (bearish direction used
  deliberately to isolate the confluence gate from the trend gate, which never applies to bearish
  candidates).

**Documentation corrections applied** (not merely proposed, per this task's explicit instruction):
`talonx_quant/config.py:244-262` — corrected the stale "computed once per bar" phrase and added an explicit
note on the confirmed RSI-curl self-exclusion. `docs/modules/quant.md` — three additions: the RSI Reversal
Curl bullet now states the curl/confluence interaction explicitly and confirms it is intentional, not a bug;
a new bullet states the three signal families' confluence contracts are NOT mathematically symmetric; the
Rejection Trace Logging section now clarifies rejection counts are first-failure-only. No threshold, weight,
or gate order changed in either file.

**Zero strategy behavior change**: confirmed both structurally (the `config.py` diff touches only comment
and blank lines) and empirically (full regression, below).

**Regression result**: 447 passed, 1 skipped, 15 xfailed, 0 failed
(`results/task29_rsi_contract_lock/test_results.txt`). `test_quant_strategy.py`: 54/54 (44 pre-existing + 10
new). `test_quant_consumer.py`: 157/157 (155 pre-existing + 2 new). No Task 26 rerun; no P&L, expectancy, PF,
or trade-count figure calculated anywhere in this task.

**What remains open**: whether the confirmed contract's real-world consequence (92.3% of RSI-curl candidates
permanently capped at confluence=1, per Task 27/28) is the desired PRODUCT behavior — explicitly reserved for
Task 30.

**Final decision**: `RSI_CONTRACT_LOCKED_AND_DOCUMENTED`.

**Next recommended action (not started)**: Task 30 — Strategy Operating Objective & Selectivity Review, per
the user's own stated plan; must not begin with parameter changes.

**State**: Task 28 checkpoint committed and pushed (`820332bfb9c1479e8a7cedcc38d104a7324ce1fa`). Task 29
code/test/documentation changes (`talonx_quant/config.py`, `docs/modules/quant.md`,
`tests/test_quant_strategy.py`, `tests/test_quant_consumer.py`) and this ledger entry — **not committed, not
pushed**, per instruction. PR #10 remains draft. All 6 required artifacts written to
`results/task29_rsi_contract_lock/`.

---

## Task 30 — Strategy Operating Objective & Selectivity Review (2026-08-21)

**Objective**: stop asking "how do we get more trades" and instead answer "what is TalonX supposed to be as
a product, and does current strategy behavior match that?" A product/research-design task — no parameter
tuning, no new backtest, no threshold relaxation.

**Task 29 checkpoint**: reviewed the Task 29 uncommitted diff (5 files: `talonx_quant/config.py`
comments-only, `docs/modules/quant.md` docs-only, `tests/test_quant_strategy.py`,
`tests/test_quant_consumer.py`, the ledger's Task 29 entry) — re-confirmed zero behavioral strategy code
changes. Staged each file individually (not `git add -A`), committed as
**`3c97d9d16b401ea207b57ddd25eae4eea037e552`** (`test(quant): lock state-based RSI confluence contract`),
pushed to `research/talonx-strategy-validation`. PR #10 confirmed draft/open after push.

**Task 30 integrity**: HEAD unchanged at `3c97d9d16b401ea207b57ddd25eae4eea037e552` throughout this task's
own analysis. Task26 dataset hash `5e5412a960bf`, QuantConfig hash `9174f5232c20`, strategy fingerprint
`88529b8a3fa1` — all untouched. No production strategy modification made.

**Evidence reviewed**: README (current + initial-commit versions), all `docs/modules/*.md` and top-level
docs, `docs/performance.md`'s full noise-filter history, full git history (origin commit, watchlist/
conviction/alert/scanner commit-message greps), config comments, and the prior research ledger. Full table
in `results/task30_operating_objective_review/objective_evidence.csv` (17 rows).

**Key finding — no stated frequency target anywhere**: exhaustive search found zero instances of a developer
or researcher ever writing down a target trade/signal frequency, at any point in this project's history. The
system's ORIGINAL design (initial commit) was structurally loose (no ATR-move gate, no confluence score, no
R:R filter); its natural, pre-filtering rate was observed at ~20 Telegram pushes/hour (commit `2b4e838`)
before Smart Dispatch Filtering existed. Every major selectivity gate now in the stack was added reactively,
fixing a specific named incident (alert chatter, a 0.33 profit-factor paper session, a 3-consecutive-SMCI-
loss streak, a stop-out incident) — never implementing a pre-declared rarity target.

**Intended operating model**: Model C (active trading) is clearly rejected — every documented decision moved
away from it. Model A (rare high-conviction) matches CURRENT OBSERVED behavior closely but has no evidence
of being the original DESIGN TARGET. Model B (regular opportunity scanner) is circumstantially favored by
the intended 50+-symbol watchlist scale (commit `7b7d815`) and "scanner"/"opportunity" self-description, but
doesn't match current measured output. Best fit: **Model D (hybrid)** — a system that started structurally
like C, was reactively narrowed toward A's observed behavior, while never abandoning B's stated watchlist
ambition; these three signals were never reconciled in any document. Full comparison in
`operating_model_comparison.csv` and `current_vs_operating_models.csv`.

**Frequency objective**: resolved from evidence — zero-signal days are acceptable and expected
(`docs/modules/dispatch.md`'s explicit, named "mobile notification fatigue" concern, with no corresponding
concern anywhere about inactivity). NOT resolved from evidence — the target signal/trade frequency itself,
marked `OWNER_DECISION_REQUIRED`. Measured current output (descriptive, not a target): 26 trades/year (2.6/
symbol-year), 85 published/year (8.5/symbol-year), ~9.9% of trading days produce at least one executed entry
portfolio-wide, 5/10 historical-universe symbols produced zero trades all year, 0 published on the 35-symbol
2026-08-20 live day. Full detail in `current_signal_frequency.csv` and `live_user_experience.md`.

**Signal-family philosophy**: each family's own docs/naming describe it as a complete, standalone setup
(RSI = reversal, MACD = momentum transition, MA = regime change), but the implementation functions as a
cross-family confirmation network (MA needs 2 external legs with zero self-credit; RSI curl and MACD each
need ~1 more, most of the time) — never reconciled in any document (`signal_family_roles.md`). Confluence's
own product-level philosophy is undocumented; current behavior is closest to "trigger + one confirmation"
for MACD/RSI-curl and closer to "no single-indicator alert" for MA — an unexplained cross-family
inconsistency (`confluence_philosophy.md`).

**Hard vs. soft gate findings**: 14 gates classified in `gate_policy_classification.csv`. Every quality/
selectivity gate (ATR-move, min_atr_pct, MA spread, confluence, trend, R:R, loss lockout) is a hard pass/fail
filter in its own documentation, despite most having reactive, incident-specific origins rather than being
designed as universal invariants from the start. Only cooldown and the batch throttle are clearly
`OPERATIONAL_GATE`/`RANKING_FACTOR`.

**Opportunity Score role**: classified `POSSIBLE_OVER_FILTERING_DESIGN` (`opportunity_score_role.md`) —
confluence (35% weight) and trend (15% weight), half the score's total weight, have their post-gate
discriminating range severely compressed by the exact hard gates that already decided eligibility (confluence
can only be 2 or 3 of its 0-3 range among survivors; trend can only be 0.5 or 1.0). R:R (30%) and volume
(20%) retain full variance. An unexamined interaction between two independently-added mechanisms, not a
documented two-stage design.

**Watchlist role**: intended production scale is 50+ symbols (coverage-oriented), but the current
implementation empirically behaves as "quality threshold dominates regardless of symbol count" (reusing
Task 27's live-day-vs-history finding) — whether more symbols were meant to produce more opportunities was
never validated against the gate stack's actual behavior (`watchlist_role.md`).

**Execution-architecture consistency**: classified `REQUIREMENT_AMBIGUOUS` — the substantial
cooldown/throttle/lifecycle machinery is defensible either as "correctness matters regardless of trade
volume" or as "provisioned for a concurrency level the gate stack rarely produces"; evidence doesn't resolve
which (`execution_architecture_consistency.md`).

**Cost-tolerance requirement**: classified `COST_TOLERANCE_REQUIREMENT_UNDEFINED` — tight ATR-based stop
geometry and short holding periods imply a need for low cost tolerance, but no document states a number.
Task 26's 0→5bps edge-erosion result is a measured OUTCOME under a fixed testing grid, not evidence of an
intended requirement — not tuned around here (`cost_tolerance_requirement.md`).

**Statistical evidence standard**: proposed six qualitative dimensions without inventing exact numbers — CI
on expectancy excludes zero, multi-regime coverage, non-concentrated symbol contribution, cost robustness,
OOS validation, formal concentration limits. The n=26 canonical baseline currently clears none of the six
conclusively (`statistical_evidence_standard.md`).

**Task 22 relevance** (conceptual only, outcomes not inspected): classified `INSUFFICIENT_CANONICAL_SAMPLE`
— the early-failure-detection question remains conceptually relevant to any operating model, but the
corrected long-only population (n=26) is too small to rederive a secondary classifier on with statistical
validity, independent of Task 22's own original findings. Downstream of the same n=26 sample-size gap
identified above (`task22_relevance.md`).

**Product/strategy gaps**: 15-row table (`product_strategy_gap_analysis.csv`). Dominant pattern:
`PRODUCT_REQUIREMENT_UNDEFINED` (frequency target, confluence philosophy, signal-family-independence
expectation) rather than a confirmed mismatch; a smaller set show `NO_GAP` (zero-signal-day acceptability,
watchlist scale, holding period, precision-vs-coverage placement); remainder are specifically classified
(`POSSIBLE_OVER_FILTERING_DESIGN`, `COST_ROBUSTNESS_GAP`, `RESEARCH_EVIDENCE_INSUFFICIENT` x2,
`OBSERVABILITY_GAP` x2).

**No tuning performed**: no threshold was changed, tested, or proposed anywhere in this task; no alternate
P&L was computed; Task 22 outcomes were not inspected.

**Final decision**: `MULTIPLE_PRODUCT_REQUIREMENTS_UNDEFINED` — more than one distinct dimension (frequency
target, cost tolerance, confluence philosophy, signal-family independence expectation) is simultaneously
undefined by repository evidence, not just one overall objective statement; several other dimensions (zero-
day acceptability, watchlist scale, holding period, horizon) WERE resolved confidently from evidence, so this
is not a blanket "insufficient research" finding either.

**Next recommended action (not started)**: Task 31 — Owner Specification Session: resolve the explicitly
undefined items (target signal/trade frequency range, cost-tolerance threshold, intended confluence
philosophy, intended signal-family independence vs. confirmation-network behavior) into a signed-off written
product specification. Not a code task — no parameter changes, no new backtest, until that specification
exists.

**State**: Task 29 checkpoint committed and pushed (`3c97d9d16b401ea207b57ddd25eae4eea037e552`). Task 30
research artifacts and this ledger entry — **not committed, not pushed**, per instruction. No production
strategy changes. PR #10 remains draft. All 18 required artifacts written to
`results/task30_operating_objective_review/`.

---

## Task 31 — Owner Specification Session & ATR Semantics Decision (2026-08-21)

**Objective**: create the explicit TalonX product/strategy specification that has been missing, and
separately resolve ATR timeframe/semantic intent before any future ATR-related implementation or tuning. An
owner-decision task — no strategy code changes, no tuning, no backtest.

**Task 30 checkpoint**: reviewed the Task 30 diff (123 insertions, ledger only, no production changes),
staged individually, committed as **`c3ede492b3965788412ca021a81e0e449aabc70f`**
(`docs(research): record operating objective review`), pushed to `research/talonx-strategy-validation`. PR
#10 confirmed draft/open.

**Task 31 integrity**: HEAD unchanged at `c3ede492b3965788412ca021a81e0e449aabc70f` throughout this task's
own analysis. Task26 dataset hash `5e5412a960bf`, QuantConfig hash `9174f5232c20`, strategy fingerprint
`88529b8a3fa1` — all untouched. No production behavior modified.

**Methodology**: every requirement tagged `EXISTING_REQUIREMENT` / `OWNER_DECISION_REQUIRED` /
`RECOMMENDED_DEFAULT_PENDING_OWNER` / `TECHNICAL_CONSTRAINT` — no recommendation presented as historical
fact. `decision_register.csv` (15 rows) records every open item with `owner_answer=PENDING`, never silently
treated as approved.

**Product identity** (PROVISIONAL, proposed): "TalonX is a high-precision intraday opportunity scanner over
a broad, liquid-equity watchlist (50+ symbols targeted). It prioritizes quality over frequency, may produce
zero-signal days as a normal and accepted outcome, opens only long positions, uses bearish signals as exits
from an existing long (never as new short entries), and closes all exposure intraday." Long-only contract:
`LONG_ONLY_CONFIRMED` (already implemented/tested, Task 25A — not an open question).

**Frequency decision/status**: `OWNER_DECISION_REQUIRED` for a target — no historical target trade/signal
frequency was ever specified anywhere in this project's history (Task 30's exhaustive search, re-confirmed).
Zero-signal-day acceptability is `CONFIRMED` from evidence (`docs/modules/dispatch.md`'s explicit
"notification fatigue" concern, no inactivity concern found anywhere). Measured baseline (not a target): 26
trades/year, 85 signals/year, 10-symbol universe.

**Watchlist decision**: 35-50+ symbols proposed as the normal operating range (documented 50+ engineering
target, ~35-39 observed in practice). Whether breadth is meant to scale opportunity frequency or only
coverage remains an open policy choice.

**Signal-family independence decision**: all three families (RSI reversal, MACD crossover, MA crossover)
recommended to be classified as candidate-generators-requiring-confirmation, formalizing existing behavior
(MA needs 2 external legs with zero self-credit; RSI curl and MACD each need ~1 more, most of the time) —
matches the current implementation exactly, no code change implied.

**Confluence philosophy**: "trigger + one independent confirmation" (A) recommended — matches MACD and
RSI-curl's current behavior; MA crossover currently behaves closer to a stricter policy (zero self-credit,
needs two independent confirmations), flagged as an inconsistency, not corrected.

**Gate-policy decisions**: 14 gates reclassified using a MANDATORY_SAFETY_GATE / MANDATORY_QUALITY_GATE /
RANKING_FACTOR / SOFT_PREFERENCE / OPERATIONAL_CONTROL / REMOVE_FROM_PRODUCT_CONTRACT /
OWNER_DECISION_REQUIRED taxonomy (`gate_policy_spec.csv`) — loss lockout reclassified from Task 30's
"quality gate" label to `MANDATORY_SAFETY_GATE` (risk management, not setup-quality judgment).

**Opportunity Score role**: purpose `CONFIRMED` — ranks already-qualified signals only, never participates
in eligibility. Redundancy finding acknowledged (`POSSIBLE_OVER_FILTERING_DESIGN`: confluence 35% + trend
15% weight components have severely compressed post-gate discriminating range) — weights unchanged.

**Cost-tolerance decision/status**: `COST_TOLERANCE_REQUIREMENT_UNDEFINED`. System design (tight ATR-based
stops, short holding periods) implies a need for low absolute tolerance, but no specific bps number can be
defended without knowing the intended execution venue — information not present in this repository.

**ATR current semantics (VERIFIED EXISTING FACT)**: ATR(14) is computed on **14 one-minute bars** (not
daily candles), via `pandas_ta`'s Wilder-smoothed `ta.atr(length=14)` over the primary `RollingBarBuffer`
(same buffer RSI/MACD/SMA already use), continuous across session boundaries (not reset daily, fixed
2026-08-16 audit commit `f2f0840`), premarket bars contribute, identical between live and backtest at the
mechanism level (`talonx_backtest` imports and calls the exact same `compute_indicators` function). The
`min_atr_pct=0.25%` default is numerically consistent only with a 1-minute-scale ATR% reading — as a
classical daily-ATR% reading it would be an almost non-restrictive floor, contradicting both the gate's
stated purpose and its ~93.7% observed rejection rate (Task 27).

**ATR intended semantics/status**: no historical document ever discusses daily-vs-intraday ATR as a
considered choice — the 1-minute interval was inherited from the pre-existing bar pipeline, not deliberately
selected for ATR specifically. Per-use-case: `atr_move_multiplier` is `SEMANTICALLY_COHERENT` (both sides of
the comparison are definitionally same-timeframe); `min_atr_pct` is `REQUIREMENT_AMBIGUOUS`; **stop/target
geometry (`atr_stop_multiplier`) is `TIMEFRAME_MISMATCH`** — the highest-priority open finding. A stop sized
to 1.5x of 1-minute-scale ATR is plausibly, though not proven causally, too tight for the confirmed
minutes-to-hours holding horizon, and is consistent with (not proven to cause) Task 26's own observed
exit-timing asymmetry (STOP median 4 min vs. TARGET/EOD median 14 min/2.6 hr). Two files
(`talonx_quant/buffer.py`, `docs/bar_buffer_persistence.md`) were found to actively contradict the current
continuous-ATR behavior (stale, describe pre-audit session-reset behavior) — flagged, not corrected.

**Live/backtest ATR parity**: `PARTIAL_PARITY` — the computation mechanism is proven identical by shared
code (not merely observed similar); end-to-end numerical parity remains unverified due to Task 25C's
previously-identified, unresolved warmup-seed-capture gap. Not re-attempted in this task.

**Today's live-session recommendation**: `RUN_OBSERVATIONAL_SHADOW_ONLY` — per this task's own governing
decision rule ("if internally coherent but requirement intent ambiguous, prefer running existing validated
behavior observationally"), both conditions (coherent implementation, ambiguous intent) confirmed true.

**Statistical evidence standard**: an 8-dimension policy proposed (sufficient trade count via CI excluding
zero, multi-regime coverage, non-concentrated symbols, cost robustness, OOS validation, formal concentration
limits, deterministic reproducibility, confidence-interval reporting) — no arbitrary trade-count number
forced. Current n=26 baseline meets 1 of 8 dimensions fully (reproducibility).

**Task 22 policy**: `DEFER_UNTIL_SAMPLE_GROWS` — outcomes not inspected; decision based solely on the same
n=26 sample-size constraint that also blocks the primary edge claim, independent of Task 22's own original
findings.

**Open owner decisions**: 15 items in `decision_register.csv`, all `owner_answer=PENDING`. Highest priority:
target signal/trade frequency, cost-tolerance requirement, ATR stop-distance intended timeframe.

**No tuning/code changes**: no threshold, formula, or gate was changed, tested against alternatives, or
proposed for change anywhere in this task. 21 existing ATR-relevant tests run (16 `test_quant_indicators.py`
+ 5 ATR/volatility cases in `test_quant_consumer.py`), 21/21 passed, 0 new tests written (existing coverage
was sufficient to verify current behavior deterministically).

**Central artifact**: `docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md` created (17 sections, each marked
CONFIRMED or PROVISIONAL) — intended to become the product-level strategy authority below explicit future
owner decisions.

**Final decision**: `MULTIPLE_OWNER_DECISIONS_STILL_REQUIRED` — too many first-order decisions remain open
for a "confirmed" label; this is a specification proposal awaiting sign-off, not a finished spec with minor
items pending.

**ATR decision (reported separately)**: `ATR_INTRADAY_14_CONFIRMED` for CURRENT implementation only —
intent for 2 of 3 use cases (`min_atr_pct`, stop geometry) remains `OWNER_DECISION_REQUIRED`, not folded
into this label.

**Next recommended action (not started)**: Task 32 — Owner Decision Capture: convene the actual product
owner to work through `decision_register.csv`'s 15 open items (priority order: target frequency, cost
tolerance, ATR stop-distance intent, then the remainder), recording real answers in place of `PENDING` and
updating `TALONX_PRODUCT_STRATEGY_SPEC.md`'s PROVISIONAL sections to CONFIRMED as each resolves. Not a code
task — no implementation should begin until this capture is complete.

**State**: Task 30 checkpoint committed and pushed (`c3ede492b3965788412ca021a81e0e449aabc70f`). Task 31
specification artifacts, `docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md`, and this ledger entry — **not
committed, not pushed**, per instruction. No production strategy changes. PR #10 remains draft. All 21
required artifacts written to `results/task31_owner_specification/`.

---

## Task 32 — Owner Decision Capture (2026-08-21)

**Objective**: turn the most important unresolved Task 31 owner decisions into explicit, version-controlled
product requirements. A decision-capture task — no code changes, no tuning, no backtest.

**Task 31 checkpoint**: reviewed the Task 31 diff (two files: `docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md`
new, ledger's Task 31 entry — no production changes), staged individually, committed as
**`4c6ef7e6691be4dd144cb7c1e1e3644d5e664e45`** (`docs(research): add TalonX product strategy specification`),
pushed to `research/talonx-strategy-validation`. PR #10 confirmed draft/open.

**Task 32 integrity**: HEAD unchanged at `4c6ef7e6691be4dd144cb7c1e1e3644d5e664e45` throughout. Task26
dataset hash `5e5412a960bf`, QuantConfig hash `9174f5232c20`, strategy fingerprint `88529b8a3fa1` — all
untouched. No production behavior modified.

**Confirmed inherited requirements (not reopened)**: long-only trade-direction contract, session behavior
(blackouts, EOD flatten), holding horizon — all already evidence-backed/tested in prior tasks, restated here
as `CONFIRMED`, no contradictory evidence found.

**Unresolved owner decisions — 9 items, all `owner_answer=PENDING`, none silently treated as approved**:

- **FREQ-001 (opportunity-frequency objective)**: `OWNER_DECISION_PENDING`, no default recommended — the
  evidence is genuinely split between `RARE_HIGH_CONVICTION` (matches current measured output: 26 trades/
  year, ~9.9% of trading days with an entry, 5/10 symbols zero trades) and `REGULAR_OPPORTUNITY` (matches
  the 50+-symbol watchlist engineering ambition) — recommending either would functionally invent the missing
  historical requirement.
- **CONF-001 (confluence philosophy)**: `OWNER_DECISION_PENDING`. Claude recommends `TRIGGER_PLUS_ONE_
  CONFIRMATION` (matches MACD/RSI-curl's current behavior exactly, smallest gap of any option; MA crossover
  flagged as inconsistent) — recommendation only, not accepted.
- **SIG-001/002/003 (signal-family independence)**: `OWNER_DECISION_PENDING` for RSI reversal, MACD
  crossover, MA crossover individually. Claude recommends `CANDIDATE_REQUIRING_CONFIRMATION` for all three
  (formalizes current behavior, zero code-change implied); asymmetric per-family classification explicitly
  permitted if preferred.
- **ATR-TRIGGER-001 (`atr_move_multiplier`)**: `OWNER_DECISION_PENDING`, but Claude's highest-confidence ATR
  recommendation — accept current `SHORT_TERM_INTRADAY_ATR` behavior as-is (`SEMANTICALLY_COHERENT`, both
  sides of the comparison are definitionally same-timeframe).
- **ATR-REGIME-001 (`min_atr_pct`)**: `OWNER_DECISION_PENDING`, no default recommended — `REQUIREMENT_
  AMBIGUOUS` between intraday-scale (current) and daily-regime-scale intent.
- **ATR-RISK-001 (stop/target geometry)**: `OWNER_DECISION_PENDING`, **highest-priority open ATR item**, no
  default recommended. Six risk-model options (A-F: short-term intraday / slower intraday / daily /
  market-structure-primary / multi-timeframe / custom) presented with trade-offs; `DAILY_ATR` explicitly NOT
  recommended merely by TA convention, per instruction — the choice must follow from TalonX's own confirmed
  minutes-to-hours trade horizon. `TIMEFRAME_MISMATCH` hypothesis (Task 31) restated as evidence, not proof:
  consistent with, not proven to cause, Task 26's STOP-exit median of 4 minutes vs. TARGET/EOD medians of 14
  min/2.6 hr. Risk principles captured for whichever option is eventually chosen (stop outside normal noise,
  structural-invalidation compatibility, live/backtest parity requirement, mandatory new canonical baseline
  before any future OOS evaluation).
- **COST-001 (cost-tolerance / execution model)**: `OWNER_DECISION_PENDING`, no bps number recommended. 8
  execution-environment sub-questions itemized (broker/venue, order type, spread, slippage, commissions,
  fill latency, liquidity assumption, premarket cost distinction) — 2 resolvable from evidence (liquid US
  equities; spread already modeled), 6 open. Task 26's 0/5/10/20bps result retained strictly as evidence
  (`CURRENT_CANONICAL_EDGE_NOT_COST_ROBUST_UNDER_TESTED_ASSUMPTIONS`), explicitly not used to select a
  threshold.

**ATR live policy**: `RUN_OBSERVATIONAL_SHADOW_ONLY`, carried forward unchanged from Task 31, until
ATR-REGIME-001 and ATR-RISK-001 are resolved. Capital-risk distinction made explicit: TalonX runs on
`talonx_paper` (simulated execution) — no real capital is at risk under this posture regardless.

**Opportunity Score and gate-policy status**: purpose (`ranks already-qualified signals only`) confirmed as
a factual description of current code; whether the owner ACCEPTS this as ongoing policy is a separate,
still-open question. Per-gate hard/soft classifications from Task 31 retained as Claude's proposed
classification only, not upgraded to owner-accepted status.

**Product identity**: left `PROVISIONAL` — no owner response exists; not made canonical merely because
Claude recommended the wording.

**Experiment blockers**: 10-row matrix mapping each open decision to the specific future research it blocks
(`results/task32_owner_decision_capture/future_experiment_blockers.csv`) — prevents unscoped experimentation
once answers start arriving.

**No tuning/code changes**: no threshold value (confluence count, ATR percentage, volume multiple, MA
spread, etc.) was proposed anywhere in this task, even conditionally on a chosen category — threshold design
is explicitly reserved for a future, separately-scoped task once owner decisions land.

**Task 22 status**: unchanged, `DEFER_UNTIL_SAMPLE_GROWS`. Outcomes not inspected, not resumed, not used to
solve the product-definition problem.

**New/updated artifacts**: `docs/research/TALONX_OWNER_DECISIONS.md` (new — the canonical, prioritized,
human-readable decision form, 9 items, every `OWNER ANSWER` field literally blank/`PENDING`).
`docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md` updated to v0.2 (introduces the CONFIRMED / PROVISIONAL /
OWNER_DECISION_PENDING / TECHNICAL_CONSTRAINT taxonomy; splits Opportunity Score and ATR sections into their
more precise per-item markers).

**Final decision**: `CRITICAL_OWNER_DECISIONS_PENDING` — no actual owner answer was captured anywhere in
this task; every P1-P5 priority item remains genuinely open, and no Claude recommendation is treated as a
decision.

**Next recommended action (not started)**: `OWNER_DECISION_REQUIRED` — return
`docs/research/TALONX_OWNER_DECISIONS.md` to the actual human product owner for the 9 prioritized answers
(FREQ-001 and ATR-RISK-001 first, as the two with no recommended default and the largest downstream research
impact). No strategy-experiment task should start until at least those are captured.

**State**: Task 31 checkpoint committed and pushed (`4c6ef7e6691be4dd144cb7c1e1e3644d5e664e45`). Task 32
decision-capture artifacts, `docs/research/TALONX_OWNER_DECISIONS.md`, the updated
`docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md`, and this ledger entry — **not committed, not pushed**, per
instruction. No production strategy changes. PR #10 remains draft. All 14 required artifacts written to
`results/task32_owner_decision_capture/`.

---

## Task 33 — Owner Decisions Captured & Product Specification Finalized (2026-08-21)

**Objective**: record the product owner's actual answers to Task 32's nine priority decisions as canonical
product requirements, promote the corresponding Task 31/32 provisional items to CONFIRMED, compare current
implementation against the newly confirmed requirements, identify the single highest-priority mismatch, and
design (not execute) the next controlled experiment. Specification and research design only.

**Task 32 checkpoint**: reviewed the Task 32 diff (three files, no production changes), staged individually,
committed as **`baa0cc6efecababf2da519b7455700165e842c10`**
(`docs(research): capture pending owner decision framework`), pushed to
`research/talonx-strategy-validation`. PR #10 confirmed draft/open.

**Integrity**: HEAD unchanged at `baa0cc6efecababf2da519b7455700165e842c10` throughout. Task26 dataset hash
`5e5412a960bf`, QuantConfig hash `9174f5232c20`, strategy fingerprint `88529b8a3fa1` — all untouched. No
production behavior modified.

**All 9 explicit owner decisions recorded verbatim** in `docs/research/TALONX_OWNER_DECISIONS.md` (every
`OWNER ANSWER` field filled in, every status changed `OPEN` → `OWNER_CONFIRMED`):

- **FREQ-001**: `REGULAR_OPPORTUNITY` — a regular intraday opportunity scanner across the production
  watchlist, "a few good opportunities per week," not active/high-frequency, not so rare that silence
  defines the product. Zero-signal days acceptable.
- **CONF-001**: `TRIGGER_PLUS_ONE_CONFIRMATION` — trigger + at least one independent confirmation; hard
  quality gate, not ranking; trigger must not automatically count as its own confirmation.
- **SIG-001/002/003**: all three families (RSI reversal, MACD crossover, MA crossover) confirmed
  `CANDIDATE_REQUIRING_CONFIRMATION` — candidate generators, not standalone strategies; confirmation may
  come from any technical dimension, not necessarily another signal family.
- **ATR-TRIGGER-001**: accept current implementation — `SHORT_TERM_INTRADAY_ATR` for the bar-movement gate.
- **ATR-REGIME-001**: `MULTI_TIMEFRAME` — the volatility/regime qualification should reflect broader
  market/instrument context while still allowing short-term intraday information; no numeric period chosen.
- **ATR-RISK-001**: `MARKET_STRUCTURE_PRIMARY` — stop/risk geometry should primarily reflect market-
  structure invalidation (pivots/swing levels); ATR permitted only as fallback/buffer/minimum-noise
  allowance; no numeric buffer formula chosen.
- **COST-001**: execution-model components confirmed (liquid US equities, spread+slippage represented,
  market-order-style acceptable); exact bps threshold explicitly deferred.

**Product identity** (now `CONFIRMED`): "TalonX is a high-precision but REGULAR intraday opportunity scanner
over a broad, liquid-equity watchlist (50+ symbols targeted). It prioritizes quality over raw frequency but
is intended to surface a useful recurring flow of opportunities across the full watchlist — a few good
opportunities per week, not a guaranteed daily quota. Not intended to generate multiple trades every day,
and not intentionally designed as an ultra-rare scanner. Zero-signal days are acceptable."

**Frequency alignment**: `INSUFFICIENT_COVERAGE_TO_COMPARE` — the 10-symbol canonical baseline (26 trades/
year) does not represent the intended 35-50+ symbol production scale; the only production-scale data point
(a single 35-symbol live day, 0 published) is too small to judge. A suggestive, explicitly-unverified
arithmetic extrapolation using only already-published Task 26/27 rates puts production-scale frequency
plausibly within "a few opportunities per week," but this is not a measurement.

**Confluence contract traced by family** (`family_confluence_alignment.csv`): MA crossover `ALIGNED` (zero
self-credit, cleanest case). RSI reversal and MACD crossover both `REQUIREMENT_INTERPRETATION_NEEDED` — RSI's
trigger bundles a volume precondition that confluence re-scores as if independent; MACD's trigger check and
its own confluence credit are the literal same boolean. Notable trace: if MACD's trigger self-credit were
disallowed, MACD could never publish at all under `confluence_score_min=2` (the remaining two legs have
co-occurred zero times across 4,725 real candidates). Flagged for owner interpretation, not resolved
unilaterally.

**Signal-family roles**: all three confirmed `CANDIDATE_REQUIRING_CONFIRMATION`; TRIGGER FAMILY (which
technical event generated the candidate) distinguished from CONFIRMATION COMPONENT (the independent evidence
validating it) — confirmation need not come from a different signal family.

**ATR-USE-2 (trigger movement)**: `SHORT_TERM_INTRADAY_ATR` accepted as-is — `ALIGNED`, no follow-up.

**ATR-USE-1 (`min_atr_pct`, regime)**: `MULTI_TIMEFRAME` confirmed conceptually —
`CURRENT_IMPLEMENTATION_INCOMPLETE_FOR_CONFIRMED_REQUIREMENT` (not a historical bug; the requirement was
only just defined). 5 future design questions recorded, none answered, lower priority than ATR-USE-3.

**ATR-USE-3 (stop/target geometry) — the highest-priority finding of this task**: `MARKET_STRUCTURE_PRIMARY`
confirmed conceptually. A direct code trace of `calculate_trade_geometry`
(`talonx_quant/strategy.py:211-269`) found `stop = price - 1.5 x ATR(14, 1-minute)` computed UNCONDITIONALLY
for every candidate — there is categorically no structural-stop code path anywhere in this function.
Structural pivot data is used exclusively on the TARGET side, never the stop side. Classified `MISALIGNED` —
this upgrades Task 31's unproven `TIMEFRAME_MISMATCH` hypothesis to a proven, code-traced structural gap now
that a concrete owner-confirmed contract exists to trace against.

**Highest-priority implementation/research mismatch**: ATR-USE-3 (stop/target geometry), selected via a
5-criteria scoring against three other candidates (confluence-vs-philosophy, min_atr_pct-vs-multi-timeframe,
frequency-vs-REGULAR_OPPORTUNITY) — highest correctness severity, highest trade-validity/risk impact
(every executed trade's risk, no exceptions), a real prerequisite relationship to future edge-evaluation
work, fully testable via pure observational audit with zero tuning.

**Next controlled task designed, not started**: Task 34 — Structural Stop Geometry Contract Audit. Measure,
for all 26 Task 26 canonical trades (and ideally all eligible published bullish signals), the relationship
between entry price, structural anchor, ATR distance, and actual stop — explicitly no alternative stop
simulation, no alternative P&L. Would establish whether the mismatch affects most trades or only rare
fallback cases before any formula redesign is attempted.

**Cost model**: `OWNER_CONFIRMED_EXECUTION_ASSUMPTIONS` + `NUMERIC_TOLERANCE_PENDING` (both hold
simultaneously) — does not block specification finalization; unconditionally blocks any future
`PRODUCTION_EDGE_CONFIRMED` claim.

**Live observability**: traced actual `QuantSignal`/`Trade`/exported-CSV schemas directly — ATR value, stop,
and target are already captured everywhere; pivot/structure data is captured at signal generation but
DROPPED before reaching the trade record or exported CSV (confirmed by direct column inspection); ATR's
timeframe is never explicitly labeled anywhere; no field records which geometry path was taken. Classified
`OBSERVABILITY_GAP` — required fields defined, no instrumentation implemented.

**Task 22 status**: unchanged, `DEFER_UNTIL_SAMPLE_GROWS`. Outcomes not inspected. Owner decisions do not
make the old Task 21-derived classifier (built on the contaminated mixed long/short population) valid again
— a separate issue, unaffected by the product spec being finalized.

**Live policy**: unchanged, `RUN_OBSERVATIONAL_SHADOW_ONLY`. No capital at risk (paper execution). No live
observations used to tune anything.

**No tuning/code changes**: no threshold, formula, or gate was changed anywhere in this task.

**Final specification status**: `CORE_PRODUCT_SPEC_CONFIRMED` — all five P1-P5 blocking decisions
conceptually resolved by explicit owner answers; remaining open items correctly downgraded to
`RESEARCH_REQUIRED` (multi-timeframe volatility design, structural stop formula design, cost bps) or narrow
interpretation clarifications (RSI/MACD self-credit), not fresh open-ended owner decisions.

**Next recommended action (not started)**: Task 34 — Structural Stop Geometry Contract Audit, per the design
above. No formula change, no alternative P&L, until this measurement exists.

**State**: Task 32 checkpoint committed and pushed (`baa0cc6efecababf2da519b7455700165e842c10`). Task 33
decision updates (`docs/research/TALONX_OWNER_DECISIONS.md`, `TALONX_PRODUCT_STRATEGY_SPEC.md` v0.3), and
this ledger entry — **not committed, not pushed**, per instruction. No production strategy changes. PR #10
remains draft. All 13 required artifacts written to `results/task33_owner_spec_finalization/`.

---

## Task 34 — Structural Stop Geometry Contract Audit (2026-08-21)

**Objective**: measure how the existing 26 canonical Task 26 trades relate to actual market structure,
before any stop-formula change is designed. Geometry/requirements/measurement audit only — no stop
optimization, no alternative P&L, no parameter sweep.

**Task 33 checkpoint**: reviewed the Task 33 diff (three files, no production changes), staged individually,
committed as **`4f175599e35d046d646f901cd2923ec831ca7d0b`** (`docs(research): finalize TalonX core product
specification`), pushed to `research/talonx-strategy-validation`. PR #10 confirmed draft/open.

**Integrity**: HEAD `4f175599e35d046d646f901cd2923ec831ca7d0b`, git status clean. Task26 dataset hash
`5e5412a960bf`, QuantConfig hash `9174f5232c20`, strategy fingerprint `88529b8a3fa1` — unchanged. Task26
trade artifact hashes recorded (`task26_trades.csv`/`.json`). No production strategy behavior changed.

**Owner-confirmed `MARKET_STRUCTURE_PRIMARY` requirement**: stop/risk geometry should primarily answer "at
what price is the trade thesis structurally invalid," with ATR permitted only as fallback/buffer/minimum-
noise allowance, never as the unconditional dominant source.

**Current stop implementation (restated, re-verified)**: `stop = price - 1.5 x ATR(14, 1-minute)`,
unconditional, for every candidate — no structural-stop code path exists anywhere in
`calculate_trade_geometry`.

**Structural source definition** (fixed before measuring, no new indicator): classic floor-trader daily
pivot support (S1), via the existing `compute_daily_pivots` function — the same, unmodified, shared
live/backtest code already used for the TARGET side. Eligibility: `pivot_support is not None AND
pivot_support < entry_price`.

**Pivot causality result**: `CAUSAL_AT_SIGNAL_TIME`, proven directly from source — `compute_daily_pivots`
uses only the prior COMPLETED regular session, strictly excluding the current session's own bars. No future
bars used, zero exceptions found.

**Structural availability**: 22/26 trades (84.6%) had a valid structural anchor; 4/26 (15.4%) did not — a
legitimate, bounded, owner-anticipated ATR-fallback case.

**ATR stop vs. structure distribution — the headline finding**: of the 22 trades with structure, **100%
(22/22)** classified `ATR_STOP_INSIDE_STRUCTURE` — the current ATR stop sits strictly tighter than the
structural invalidation level in every measurable case. Zero trades had the stop at or beyond structure.
Median structural distance was ~13.3 ATR units away (range ~1.75-32), implying the current stop is, on
median, roughly 8.9x tighter than structure.

**STOP-trade thesis result**: of 18 STOP exits, 15/18 (83.3%) fired while the structural level remained
INTACT (never breached); zero STOP exits coincided with an actual structural breach; 3/18 had no structure
available. Cross-checked against MAE (observed low up to canonical exit, no extension): 0/22 trades with
structure ever had their MAE reach the structural level — structure was never breached in any of the 26
canonical trades, winners or losers.

**Target-side asymmetry**: 100% of the 26 trades' targets were structural (pivot-based) — every trade
therefore carries a mixed-timescale geometry contract (stop = 1-minute ATR, target = market structure),
classified `PRODUCT_SPEC_MISALIGNMENT`.

**Symbol concentration**: pattern is broad across every traded symbol (STX, AMD, PYPL, NVDA, TSLA) — a
uniform 100% ATR-stop-inside-structure rate wherever structure exists, not driven by STX alone despite STX's
15/26 trade concentration.

**Implementability**: `IMPLEMENTABLE_WITH_EXISTING_CAUSAL_DATA` — `pivot_support` is already a parameter of
`calculate_trade_geometry`, already causal, already shared identically between live and backtest; no new
indicator or state extension required. Only the fallback buffer formula remains an explicit future design
choice.

**Live/backtest parity requirements defined, not implemented**: structural level, structural level type,
structural source timestamp, ATR value, ATR timeframe label, fallback reason, selected stop, geometry path —
minimum schema for a future implementation to avoid Task 33's observability gap recurring.

**No alternative stop P&L**: no hypothetical winner count, expectancy, PF, or max-DD was calculated anywhere.
**No parameter tuning**: no ATR multiplier, pivot lookback, or buffer value was swept or proposed.

**Determinism**: core geometry extraction run twice independently from frozen inputs; output SHA-256 matched
exactly both times, 26 rows both times, zero mismatches.

**Tests**: no new tests written; 17 existing, directly relevant tests run (4 pivot + 13 structural
R:R/geometry), 17/17 passed.

**Final decision**: `CURRENT_ATR_STOPS_SYSTEMATICALLY_MISALIGNED_WITH_STRUCTURE` — the mismatch is broad and
systematic (100% of measurable cases), not limited to a small subset.

**Next recommended action (not started)**: Task 35 — Deterministic Market-Structure-Primary Stop
Implementation. Smallest implementation change (reuse the existing `pivot_support` parameter for the
bullish stop, mirroring the existing bearish-target logic); deterministic tests first; explicit ATR fallback
conditions only; preserve all unrelated parameters; live/paper/backtest parity per the defined minimum
schema; no economic comparison within that implementation task.

**State**: Task 33 checkpoint committed and pushed (`4f175599e35d046d646f901cd2923ec831ca7d0b`). Task 34
measurement artifacts and this ledger entry — **not committed, not pushed**, per instruction. No production
strategy changes. PR #10 remains draft. All 20 required artifacts written to
`results/task34_structural_stop_geometry/`.

---

## Task 35 — Deterministic Market-Structure-Primary Stop Implementation (2026-08-21)

**Objective**: implement the smallest deterministic correction needed to make LONG stop geometry conform to
the owner-confirmed `MARKET_STRUCTURE_PRIMARY` contract (ATR-RISK-001). Correctness/spec-alignment, not
optimization — no rule chosen from historical outcomes, no economic evaluation performed. **The first task
in this entire research track to modify production strategy code.**

**Task 34 checkpoint**: reviewed the Task 34 diff (ledger entry only, no production code; final decision
confirmed `CURRENT_ATR_STOPS_SYSTEMATICALLY_MISALIGNED_WITH_STRUCTURE`, all 20 artifacts present), staged
individually, committed as **`6133672c2e15a2c89a7dd27ebc3e9f0fea46d5bc`**
(`docs(research): record structural stop geometry audit`), pushed to `research/talonx-strategy-validation`.
PR #10 confirmed draft/open.

**Integrity**: HEAD `6133672c2e15a2c89a7dd27ebc3e9f0fea46d5bc` before any code change. Task26 dataset hash
`5e5412a960bf`, QuantConfig hash `9174f5232c20` — unchanged. Strategy fingerprint before:
`88529b8a3fa1`; after: `acd08feb59a7` (an expected consequence of a real `strategy.py` change, not itself
economically significant). Pre-modification SHA-256 hashes recorded for all touched files
(`talonx_quant/strategy.py`, `schemas.py`, `consumer.py`; `talonx_backtest/engine.py`, `execution.py`,
`portfolio.py`; `talonx_paper/schemas.py`).

**Old stop behavior**: `stop = price - 1.5 x ATR(14, 1-minute)`, unconditional, for every BULLISH candidate —
no structural input, ever (Task 34's finding).

**New stop behavior**: `calculate_trade_geometry` (`talonx_quant/strategy.py`) now selects, for BULLISH
candidates only, the prior-session S1 pivot support (the existing, causal, unmodified
`compute_daily_pivots`) as the stop LITERALLY — no buffer subtracted (Task 34 found none defined;
`STRUCTURAL_BUFFER_REQUIREMENT_NOT_DEFINED`, not invented here) — whenever it is finite, positive, and
strictly below price. Otherwise falls back to the unmodified `1.5x ATR` formula with an explicit
`fallback_reason` (`NO_STRUCTURAL_SUPPORT` / `STRUCTURE_INVALID_OR_NONFINITE` / `STRUCTURE_NOT_BELOW_ENTRY`).
`risk` is always `price - (the actual selected stop)`, so `risk_reward_ratio` always reflects real geometry.
BEARISH direction, target selection, `atr_move_multiplier` (trigger movement), and `min_atr_pct` (regime) are
all byte-for-byte unchanged.

**Structural source**: unchanged from Task 34 — classic floor-trader prior-session S1 pivot
(`compute_daily_pivots`), no new indicator. **Causal validity rule**: `pivot_support is not None AND
math.isfinite(pivot_support) AND pivot_support > 0 AND pivot_support < price`, re-evaluated fresh at every
geometry computation (screening, throttle-flush revalidation, actual fill) — never cached from an earlier
decision. **ATR fallback rule**: unmodified `1.5x ATR` formula, fires only when the validity rule fails,
three mutually-exclusive, explicit reasons recorded.

**R:R recalculation**: `risk` now derives from whichever stop was actually selected, not a stale ATR-only
figure — proven with an explicit rejection case
(`test_rr_rejection_case_correct_geometry_fails_where_old_atr_geometry_would_have_passed`): a candidate
whose OLD geometry would have cleared `min_risk_reward_ratio=1.5` (R:R=2.33) now correctly fails (R:R=0.35)
once its risk is measured against the real, wider structural stop — the implementation does not preserve the
old candidate/signal count artificially.

**Fill reconciliation**: `talonx_backtest.engine._finalize_fill_geometry` (Task 13's fill-anchored recompute)
and `talonx_quant.consumer._revalidate_candidate` both re-invoke the shared `calculate_trade_geometry`
against the current price at that moment, so the selected path can legitimately change between screening and
fill (5 cases proven: structure survives revalidation; price drifts through structure, falls back cleanly;
backtest fill-gap preserves the ATR path when structure is invalid at the real fill; backtest fill-gap
correctly selects structure when valid at the real fill; the Task 13 "no artificially favorable STOP
mislabel" invariant holds under the new code path too).

**Live/paper/backtest parity**: every path a trade can be represented on was traced and updated
consistently — signal generation, live pre-publish revalidation, backtest throttle-flush revalidation,
backtest fill-time reconciliation, and the canonical `Trade` record all carry the four new fields
(`geometry_path`, `fallback_reason`, `structural_level`, `structural_level_type`) in lockstep, via one
shared `calculate_trade_geometry` call everywhere — zero formula duplication. `talonx_paper`'s
`fill_geometry_is_valid` confirmed unchanged BY TRACING (not assumed): it validates `stop_price <
fill_price < target_price` generically, with no dependency on how `stop_price` was derived, so it already
works correctly for a structural stop with zero code change. `talonx_paper.TriggeringSignalRef` (wire
schema) extended with the four new fields, mirroring its own existing `stop_price`/`target_price` pattern —
the data was already on the wire (`talonx_core.ActionableAlert.triggering_signal: QuantSignal`, unchanged)
and only needed unlocking on the reduced consumer-side schema.

**Observability/schema changes**: `QuantSignal`, `Trade` (`talonx_backtest.portfolio`), and
`TriggeringSignalRef` (`talonx_paper.schemas`) all gained the four new fields, closing exactly the gap
Task 33/34 identified (pivot data previously dropped between signal generation and the trade record). Two
deliberate, documented scope boundaries, neither affecting correctness: `talonx_paper`'s SQLite
`trade_history` persistence and `talonx_dispatch`'s Telegram/audit-trail formatting were NOT extended (see
`results/task35_structural_stop_implementation/schema_observability_changes.md`).

**Tests**: 15 new tests (10 in `test_quant_strategy.py` — geometry cases A-F plus bearish-unaffected, 2 R:R
invariant tests, 1 rejection proof; 2 in `test_quant_consumer.py`; 2 in
`test_backtest_fill_geometry.py`/lifecycle files) plus 12 existing tests' shared fixtures adjusted (with
inline comments explaining why) to isolate their original, still-valid purpose from the new structural-stop
behavior — zero test weakened or deleted. Focused suite: **478 passed, 1 skipped, 15 xfailed (pre-existing,
unrelated), 0 failed.** Full-repository suite: **1724 passed, 1 skipped, 15 xfailed, 3 failed** — all 3
failures independently verified pre-existing and unrelated to Task 35 (one is the exact same already-known
Task 25A LONG_ONLY-lifecycle demo-CSV issue `test_backtest_sample_data.py` already xfails, re-confirmed by
running the identical CSV through the identical already-xfailed code path; two are `talonx_ingest`
yfinance-polling tests, a module untouched anywhere in this diff). Determinism proven directly on the core
geometry function (two independent runs, identical SHA-256, zero mismatches).

**No tuning**: no threshold named in the governing instruction's do-not-change list was touched — confirmed
directly by the diff. No `structural_stop_enabled` config flag or any other toggle was introduced. **No
P&L analysis**: no total R, expectancy, win rate, PF, max DD, or "did the strategy improve" claim appears
anywhere in this task's artifacts.

**What remains open**: the exact ATR-REGIME-001 (`min_atr_pct` multi-timeframe) implementation remains a
separate, not-yet-started future task, unaffected by this change. `talonx_paper`'s SQLite persistence and
`talonx_dispatch` formatting are documented, deliberate scope boundaries for a future task if paper-side
historical audit or Telegram surfacing of geometry path is wanted. A new canonical baseline has NOT been
established under the corrected geometry — Task 26's n=26 population is now based on the OLD, superseded
stop formula and should not be treated as representing the corrected strategy's behavior going forward.

**Final decision**: `STRUCTURAL_STOP_IMPLEMENTATION_VALIDATED` — implemented, tested, deterministic, fully
traced for parity, zero regressions in scope, zero economic claims made.

**Next recommended action (not started)**: Task 36 — Canonical Long-Only Baseline Re-establishment After
Structural Stop Correction. Re-run the full Task 26 dataset with the corrected stop geometry: freeze
implementation/config first, establish new dataset/config/code hashes, compare the resulting trade
population carefully against Task 26's (treating any difference as a new canonical strategy version, not an
error), run realistic cost sensitivity, do not tune parameters.

**State**: Task 34 checkpoint committed and pushed (`6133672c2e15a2c89a7dd27ebc3e9f0fea46d5bc`). Task 35
code/test/documentation changes and this ledger entry — **not committed, not pushed**, per instruction. PR
#10 remains draft. All 14 required artifacts written to `results/task35_structural_stop_implementation/`.

## Task 36 — Canonical Long-Only Baseline Re-establishment After Structural Stop Correction (2026-08-22)

**Objective**: re-run the full Task 26 dataset under the Task 35 corrected `MARKET_STRUCTURE_PRIMARY` stop
geometry and characterize the resulting trade population as a new canonical reference — explicitly NOT an
"improvement/regression" comparison against Task 26, since the two populations rest on different, mutually
incompatible stop-geometry contracts.

**Task 35 checkpoint**: committed and already on branch as **`5da8617d691221cdc54f4f1866f8d888847ffa5c`**
(`fix(quant): use market-structure-primary long stops`) prior to this task's own work beginning.

**Integrity**: QuantConfig hash `9174f5232c20` — unchanged from Task 26. BacktestConfig hash `19654e22ffd5`
— unchanged from Task 26. Strategy fingerprint `acd08feb59a7` — changed as expected (Task 35's code change).
Dataset hash `5e5412a960bf` — confirmed identical to Task 26's dataset. Focused test gate: 478 passed, 0
failed, re-confirmed before launching the run. Data quality: all 10 symbols clean, zero critical corruption
(identical dataset to Task 26).

**Run**: full 1,903,044-bar / 10-symbol dataset, `research_telemetry=True`. Completed in 233.8 minutes.
**A first launch attempt was lost mid-run** (killed when the executing session was torn down, ~85.7%
complete, no output artifacts written) and had to be relaunched from scratch; a duplicate-launch race during
the relaunch was caught and killed before any output was produced. The run reported here is a single, clean,
uncontaminated execution — config/dataset/strategy hashes above were re-verified identical to the aborted
attempt's logged values before treating this run as canonical.

**Signal funnel**: `signals_generated`=5,021 (identical to Task 27's candidate count — candidate generation
is untouched by Task 35). `LOW_RISK_REWARD` first-failure rejections rose from Task 26's 136 to **181**
(+45, +33%) — the only gate whose count could mechanically shift under Task 35, since bearish geometry and
all upstream directional-agnostic gates (confluence, blackout windows, trend, session) are byte-for-byte
unchanged. `signals_published`=67 (60 bearish `NO_ACTIVE_POSITION` — matches Task 26's 59 almost exactly — +
7 bullish). **Every one of the 7 bullish-published signals became an executed trade** (100% publish→execute
conversion, same clean pattern Task 26 showed at 26/26) — the population collapse happened entirely upstream
of publish, at the RR gate, not from any new throttle/fill-time rejection (`GEOMETRY_INVALIDATED_AT_FILL`
and `RR_DEGRADED_DURING_THROTTLE`: 0 occurrences, same as Task 26).

**Geometry-path distribution** (executed trades): 3 `STRUCTURAL_PRIMARY`, 4 `ATR_FALLBACK`. All 4 fallbacks
share the same reason: `STRUCTURE_NOT_BELOW_ENTRY` (structure existed but was at/above the entry price at
the moment geometry was computed) — `NO_STRUCTURAL_SUPPORT` and `STRUCTURE_INVALID_OR_NONFINITE` were never
observed among executed trades.

**R:R population effect**: candidate-level RR≥1.5 count fell from Task 27's 3,360 to 2,709 (-19%,
first-pass check, not gate-priority-ordered). Executed trade count fell from 26 to 7 (-73%). The gap between
these two figures is expected and not further investigated here (out of scope for a characterization task) —
gate evaluation order means a candidate that also fails an earlier gate (confluence, blackout, etc.) is never
attributed to RR in the first-failure accounting even if it would also have failed RR.

**Zero-short invariant**: CONFIRMED — all 7 executed trades `direction == bullish`.

**Executed trade count**: 7 (down from Task 26's 26).

**Geometry validity audit**: 7/7 trades pass the correct invariant (`stop < entry < target`, plus exact
`stop == structural_level` for the 3 `STRUCTURAL_PRIMARY` trades). An initial validity check incorrectly
flagged the 4 `ATR_FALLBACK` trades as invalid by re-deriving `entry_price - 1.5×atr` and comparing exactly
— this ignored `engine.py::_finalize_fill_geometry`'s deliberately narrow behavior (documented in Task 13/35):
it only re-anchors stop/target when the fill price actually breaks the bracket invariant, otherwise leaving
stop/target at their revalidation-time values even as `entry_price` (the real fill) drifts slightly from
that reference — the same pre-existing mechanism that lets `execution_rr` diverge from `screening_rr`. Fixed
before drawing any conclusion from it; not a Task 35 defect.

**Exit-path breakdown**: STOP=4, END_OF_SESSION=3, TARGET=0, SIGNAL_EXIT=0.

**Canonical 0bps performance** (n=7 — explicitly too small for a standalone edge claim, reported for the
record): win rate 42.9% (Wilson 95% CI [15.8%, 75.0%]); mean expectancy -0.139R (approx. 95% CI
[-1.03R, +0.75R]); gross total -0.976R; profit factor 0.756; max drawdown -2.946R; median trade -1.0R.

**Cost sensitivity** (same cost-invariant-population method as Task 26 — gate/geometry decisions use raw
pre-cost prices, so the 7-trade population is identical across all four scenarios): PF 0.756 (0bps) → 0.547
(5bps) → 0.402 (10bps, wins drop 3→2) → 0.216 (20bps). Already sub-1.0 profit factor at 0bps.

**Structural-primary vs. fallback characteristics**: the 3 `STRUCTURAL_PRIMARY` trades sit a median 3.74 ATR
units (0.96% of entry price, $4.08 median) below entry — materially wider than the old unconditional 1.5×ATR
stop. Execution R:R for structural trades (median 5.85) is proportionally lower than for ATR-fallback trades
(median 15.73), though both remain comfortably above the 1.5 gate for the 7 trades that did clear it.

**Symbol concentration**: only 2 of 10 symbols ever traded — AMD (4 trades, 57.1%) and STX (3 trades, all
losers). 8 symbols (AAPL, MSFT, NVDA, AMZN, META, TSLA, GOOGL, PYPL) recorded zero trades across the full
one-year dataset. AMD accounts for 66.9% of gross positive R; STX's 3 trades are all STOP-outs with zero
winners.

**Holding-time distribution**: overall median 5,820s (97 min), mean 6,506s. STOP exits are fast (median
330s / 5.5 min); END_OF_SESSION exits are much longer (median 7,740s / 129 min) — consistent with a stop
that, when it fires, fires close to entry in wall-clock terms.

**Task 26 → Task 36 trade-level reconciliation** (26 Task 26 trades classified): `TRADE_RETAINED`=4,
`GEOMETRY_CHANGED_ONLY`=3 (same entry, different stop under the new contract), `OLD_TRADE_NO_LONGER_PUBLISHED`
=19, `NEW_TRADE_APPEARS`=0. 4+3=7 accounts for every Task 36 trade; 19 accounts for the rest of Task 26's 26 —
fully reconciled both directions.

**Frequency vs. `REGULAR_OPPORTUNITY` product objective (Task 33)**: `INSUFFICIENT_COVERAGE_TO_COMPARE` —
this run covers 10 of the 35-50+ symbols the product objective implies; a frequency judgment against a
10-symbol, 2-symbol-active population would not be meaningful.

**Statistical evidence assessment**: sample size n=7 is smaller than Task 26's already-flagged-thin n=26;
multi-regime coverage is a full year but concentrated in 2 symbols out of 10 (severe concentration, not
generalized); cost robustness fails outright (PF already <1.0 gross, before any cost is applied); no OOS
validation performed (Task 22 correctly not inspected, per instruction); reproducibility confirmed via
config/dataset/strategy hashes and (see below) a determinism re-run. Overall: population is real, valid, and
correctly reconciled, but far too small and concentrated to support any edge claim in either direction.

**Determinism**: bounded 70,320-bar (2-week × 10-symbol) subset run twice; SHA-256 fingerprint over
`{signal_log, rejections, trades (incl. geometry_path/stop_price), signals_generated/published,
geometry_path_counts, fallback_reason_counts, bars_processed}`. Both runs produced identical hashes
(`085919ff38ef4e833c06d96aa65d81a85e63dcc7da5c82432d2a441d4edbed21`), 54 signals generated, 0 trades in each
run — the subset window itself contains no executed trades, but determinism is proven by hash equality
across two independent runs of identical code/config/data, not by the subset having trades.

**Task 22**: not inspected, per instruction — sample inadequacy (n=7) makes any OOS comparison premature
regardless.

**Final decision**: `CORRECTED_CANONICAL_BASELINE_ESTABLISHED_INSUFFICIENT_SAMPLE` — the corrected geometry
run is mechanically valid (deterministic, zero-short invariant holds, 100% publish→execute conversion,
geometry audit passes, fully reconciled against Task 26), but n=7 trades concentrated in 2 of 10 symbols with
a sub-1.0 gross profit factor is far too small and concentrated to establish or reject an edge. `COST_ROBUST`
is explicitly not selected — the population is cost-fragile, not cost-robust.

**Next recommended action (not started)**: **Task 37, option C** — expand the historical dataset to the
product objective's intended 35-50+ symbol universe before drawing any further performance conclusion. The
2-symbol concentration here (8 of 10 already-included symbols traded zero times in a full year) suggests the
10-symbol universe itself, not just the stop-geometry correction, is the binding constraint on sample size —
expanding symbol coverage is the highest-leverage next step before any cost-model refinement (option B) or
geometry-coherence investigation (option A) would have enough trades to act on.

**State**: Task 35 checkpoint committed (`5da8617d691221cdc54f4f1866f8d888847ffa5c`). This Task 36 ledger
entry and all `results/task36_structural_stop_canonical_baseline/` artifacts — **not committed, not
pushed**, per instruction. PR #10 remains draft.

**2026-08-22 update (Task 37)**: this Task 36 ledger entry was committed as `f280d5555ae81e96f90c11d4aaee0cb0f3fa5051`
(`docs(research): record corrected canonical baseline`) and pushed at the start of Task 37, per that task's
checkpoint-first instruction. `results/task36_structural_stop_canonical_baseline/` artifacts remain
untracked (repo-wide `/results/` is gitignored by design, confirmed — no results directory has ever been
committed in this repo's history). PR #10 confirmed still draft/open.

## Task 37 — Fast Production-Universe Feasibility Check (2026-08-22)

**Objective**: cheaply determine whether expanding from Task 36's 10-symbol universe toward the product's
intended 35-50+ symbol production universe (Task 33's `REGULAR_OPPORTUNITY` objective) would plausibly create
a meaningful recurring opportunity flow — a feasibility gate deciding whether an expensive full 35-50 symbol,
full-year backtest is worth running, NOT that expensive run itself.

**Task 36 checkpoint**: committed and pushed as `f280d5555ae81e96f90c11d4aaee0cb0f3fa5051`
(`docs(research): record corrected canonical baseline`) before any Task 37 work began.

**Frozen strategy**: zero code changes. HEAD `f280d5555ae81e96f90c11d4aaee0cb0f3fa5051` is docs-only;
QuantConfig hash `9174f5232c20`, BacktestConfig hash `19654e22ffd5`, strategy version `acd08feb59a7` — all
three identical to Task 36's values, confirmed at run start.

**Universe**: 35 symbols — Task 36's original 10 (AAPL, MSFT, NVDA, AMZN, META, AMD, TSLA, GOOGL, PYPL, STX)
plus 25 additional large/liquid Nasdaq-100 names (ADBE, ADI, AMAT, AVGO, BKNG, CMCSA, COST, CSCO, GILD, HON,
INTC, INTU, ISRG, KLAC, LRCX, MDLZ, MU, NFLX, PANW, PEP, QCOM, REGN, SBUX, TXN, VRTX), chosen from a fixed
alphabetical reference list before any Task 37 result was viewed — not cherry-picked. See
`universe_manifest.csv`.

**Sample windows**: three fixed, non-overlapping 10-trading-day windows selected mechanically from AAPL's
actual trading-day calendar (positional slices with a 10-day buffer at each end, split into early/middle/late
thirds) before any strategy result was viewed: A_early 2025-08-29→2025-09-12, B_middle 2026-02-06→2026-02-20,
C_late 2026-07-20→2026-07-31 — 30 trading days total (~6 weeks). See `window_manifest.csv`. The 10 original
symbols were sliced from their existing full-year local CSVs (zero network cost, guaranteed data-origin
consistency with Task 36); the 25 new symbols were freshly downloaded via the same Alpaca provider Task 7B
used, all 25/25 returning `FULL` status with no failures.

**Runtime policy**: estimated ~793K bars / ~1.6h before launching (41.7% of Task 36's workload, ~12% of a
hypothetical full 35-symbol year) — within the 1-2h MEDIUM budget, no STOP triggered. Actual: 600,363 bars,
75.4 minutes (31.5% of Task 36's workload, 9.1% of a hypothetical full 35-symbol year) — came in under
estimate. A second pass (`research_telemetry=False`, 75.5 min) re-ran the identical frozen strategy on the
identical data solely to recover per-symbol funnel detail the first pass had discarded — not a second,
different evaluation; the two passes cross-checked as an exact MATCH on signals_generated/published/trades
for all 3 windows, which doubles as this task's determinism evidence (see below).

**Data quality**: all 35 symbols × 3 windows clean, zero critical corruption.

**Signal funnel** (aggregate, 600,363 bars): raw candidates 2,473 (0.41% of bars); **LOW_VOLATILITY 530,360
(88.34% of ALL bars)** — overwhelmingly dominant, evaluated bar-level before any candidate exists, no
overlapping-failure ambiguity since nothing else is evaluated first; LOW_CONFLUENCE 1,548 (0.26%, the
distant second); LOW_RISK_REWARD 94 (0.016%); TREND_GATE 4; blackouts 507 combined; published bullish 1;
published bearish (NO_ACTIVE_POSITION, while flat) 18; executed longs 1. Full per-symbol breakdown in
`symbol_summary.csv` — LOW_VOLATILITY dominates for every one of the 35 symbols individually (range ~8,400 to
~27,000 rejected bars per symbol); COST alone produced zero raw candidates across its entire sample.

**Zero-short invariant**: CONFIRMED — the single executed trade is `direction == bullish`.

**Main product question**: across ~6 sampled weeks — executable longs/week ≈ **0.167** (1 trade / 6 weeks);
published bullish signals/week ≈ 0.167 (identical, 100% publish→execute conversion, same clean pattern as
Task 26/36); 29 of 30 sampled trading days had zero entries, 1 day had exactly 1 entry, 0 days had 2 or 3+;
only 1 of 35 symbols (BKNG) ever produced a trade, 34 produced zero. Against the `REGULAR_OPPORTUNITY`
objective ("a few good opportunities/week across the production watchlist"), this is not close — observed
frequency is roughly two orders of magnitude below even the low end of "a few/week."

**Frequency classification**: `LIKELY_TOO_SPARSE`.

**Bottleneck**: `LOW_VOLATILITY`, not `MULTIPLE` — no other gate is remotely comparable in magnitude (next
largest, LOW_CONFLUENCE, is 340x smaller). Because LOW_VOLATILITY is evaluated before `evaluate_signals` runs
at all, this is a clean first-failure measurement with no known overlapping-failure ambiguity to account for
(unlike candidate-level gates such as LOW_RISK_REWARD, where Task 27/33 established that first-failure
counts under-attribute rejections to gates evaluated later in priority order). No new threshold proposed.

**Economics (light only, n=1 — NOT STATISTICALLY SUFFICIENT FOR EDGE CLAIM)**: 1 trade, gross_R -1.0, 5bps
net_R -1.24, 0 wins / 1 loss (STOP exit, BKNG, 2026-07-30).

**Geometry**: 0 STRUCTURAL_PRIMARY, 1 ATR_FALLBACK (`STRUCTURE_NOT_BELOW_ENTRY`), 0 invalid geometry. Not
meaningful at n=1; no alternative-stop analysis performed.

**Determinism**: two independent full runs (differing only in `research_telemetry` on/off, extracting
different downstream detail) matched exactly on signals_generated/published/trades across all 3 windows —
stronger evidence than a bounded-subset replay would have been, at zero additional cost since the second pass
was independently required. A third, separate bounded-subset replay was deliberately skipped as redundant.
Focused test suite reused (not re-derived): 274 passed, 0 failed
(`test_quant_strategy/consumer/backtest_fill_geometry/backtest_long_only_lifecycle/live_backtest_contract/backtest_engine_state`).
Strategy-code determinism itself was already proven in Task 35 (core geometry function) and Task 36 (bounded
subset, full-year data) — not re-proven from scratch here.

**No tuning**: zero code changes; no threshold named in the governing instruction's do-not-change list was
touched, confirmed by the frozen config/strategy hashes matching Task 36 exactly. No Task 22 inspection.

**Decision gate**: condition B applies — the strategy is extremely sparse AND one gate (LOW_VOLATILITY)
overwhelmingly dominates (in fact the same underlying cause explains both). Per the governing instruction,
this means do NOT recommend an overnight full 35-50 symbol/full-year run; recommend a focused diagnostic of
the dominant bottleneck first.

**Final decision**: `DOMINANT_GATE_REQUIRES_DIAGNOSTIC`.

**Next recommended action (not started)**: a focused, measurement-only diagnostic of the LOW_VOLATILITY gate
across the 35-symbol universe — e.g. the distribution of realized ATR% relative to `min_atr_pct` per symbol,
whether the rejection is concentrated in extended-hours bars vs. the regular session, and whether it is
uniform across symbols or concentrated in specific names/sectors (COST rejected 100% of its sampled bars).
Explicitly measurement-only: no new threshold proposed, no config change, no re-run of the expensive
35-symbol backtest until this diagnostic explains the dominant gate's behavior.

**State**: Task 36 checkpoint committed and pushed (`f280d5555ae81e96f90c11d4aaee0cb0f3fa5051`). This Task 37
ledger entry and all `results/task37_fast_universe_feasibility/` artifacts — **not committed, not pushed**,
per instruction. PR #10 remains draft.

**2026-08-22 update (Task 38)**: this Task 37 ledger entry was committed as `df266c9c74e0afe41f99a51a327d3357dd6a11df`
(`docs(research): record production-universe feasibility check`) and pushed at the start of Task 38.
`results/task37_fast_universe_feasibility/` artifacts remain untracked (repo-wide `/results/` gitignored).
PR #10 confirmed still draft/open.

## Task 38 — LOW_VOLATILITY Gate Diagnostic (2026-08-22)

**Objective**: measurement-only diagnosis of why LOW_VOLATILITY rejects ~88% of bars (Task 37), and whether
the current 1-minute ATR% gate is semantically suitable for the owner-confirmed `MULTI_TIMEFRAME`
volatility-regime requirement (Task 33, `ATR-REGIME-001`). No code, config, or threshold changed.

**Task 37 checkpoint**: committed and pushed as `df266c9c74e0afe41f99a51a327d3357dd6a11df`
(`docs(research): record production-universe feasibility check`) before Task 38 began.

**Integrity**: HEAD `df266c9c74e0afe41f99a51a327d3357dd6a11df`, QuantConfig `9174f5232c20`, BacktestConfig
`19654e22ffd5`, strategy version `acd08feb59a7` — all identical to Task 36/37 (confirmed frozen, zero code
changes for this task). Reused Task 37's exact 35-symbol universe and 3 windows (2025-08-29→09-12,
2026-02-06→02-20, 2026-07-20→07-31) and already-downloaded data — zero new data fetched.

**Formula confirmed** (full trace in `atr_formula_trace.md`): `ATR(14, pandas_ta, 1-minute
RollingBarBuffer, 200-bar cap, continuous across session boundaries) / current bar close >= 0.25%`, strict
`<`/inclusive `>=`, 120-bar warm-up (silently skipped, no gate evaluation at all). Critically, gate ordering
places `_fails_min_volatility` BEFORE `evaluate_signals` in `engine.py::_process_symbol_bar` — a
volatility-failing bar never even attempts RSI/MACD/MA trigger detection, so the live `signal_log` can never
contain a volatility-failing candidate by construction. Not called a bug — the code does exactly what it
says.

**Method**: rather than a second full engine re-run (which cannot answer step 7's question, since
`evaluate_signals` is gated behind the volatility check in production), a lightweight diagnostic replay
reused the exact frozen buffer/aggregator/indicator/signal functions (`RollingBarBuffer`,
`HtfBarAggregator`, `get_session`, `compute_indicators`, `compute_htf_trend`, `compute_daily_pivots`,
`evaluate_signals`, `_fails_min_volatility` — zero formula reimplementation) but called `evaluate_signals` on
**every** bar regardless of the volatility outcome, to measure raw candidate density independent of the
gate. Smoke-tested (500 bars, ~84min projected) before the full run (105.5 min, single bounded pass, not
multi-hour). Fidelity validated exactly: the replay's candidates-passing-volatility count (2,473) matches
Task 37's actual published `signals_generated` (2,473) precisely.

**ATR% distribution** (587,868 post-warm-up bars): median 0.093%, p90 0.248%, p95 0.329% — the 0.25%
threshold sits almost exactly at the 90th percentile. Every symbol's median is below 0.25%, including the
most volatile name (STX, 0.207%).

**Session split**: pass rate 54.6% in the 09:30-09:45 opening blackout vs. 9.4% regular/8.9% pre-market/7.1%
closed/3.1% closing-blackout — passes cluster in a window ALSO independently blocked by `OPENING_BLACKOUT`.

**Price/symbol effect**: weak, likely non-causal correlation (r=0.135 level, r=0.080 pass rate); no
causality inferred from price alone.

**Candidate-level analysis (the central finding)**: 27,039 raw RSI/MACD/MA triggers exist unconditionally
in the sample; only 9.15% (2,473) would clear the volatility gate. MACD (25,927 candidates) and RSI (1,069)
fail 90.9%/94.3% of the time; MA-crossover (43, rarer/larger inherent move) passes 97.7%. **The gate is not
primarily filtering quiet/dead bars — it discards the large majority of genuine trigger events.** Rejected
candidates are mostly structurally short of the threshold (43% fall 50-75% short), not narrow misses.

**Broader-timeframe context** (descriptive, same source bars, no new formula): 15-min median ATR% 0.42%
(82% clear 0.25), 60-min median 0.84% (99.9% clear it); daily ATR not computable from a 10-trading-day
sample window. The same symbols/periods show normal-to-high volatility at broader timeframes — it is
specifically the 1-minute reading that rarely crosses 0.25%.

**Current gate semantics**: `EXTREME_1MIN_VOLATILITY_FILTER` (not `SHORT_TERM_NOISE_FILTER` — active
triggers fail it >90% of the time; not `BROADER_REGIME_PROXY` — every symbol fails at 1-minute scale
regardless of 15/60-min activity).

**Dominant-gate validation at candidate level**: 90.85% candidate-level rejection, essentially identical to
the 90.22% bar-level rate — confirms LOW_VOLATILITY remains dominant at candidate level, not a bar-counting
artifact.

**Requirement alignment**: `MISALIGNED` — the gate applies a single 1-minute-bar reading as if it were a
regime-level filter, directly confirming the `TIMEFRAME_MISMATCH` hypothesis first raised (unproven) in
Task 31. Requirements for a future replacement (contract-level only, no formula proposed):
comparable-across-price, reflects broader tradability regime, retains short-term trigger relevance, causal
and live-computable, identical live/backtest semantics, defined premarket/extended-hours behavior,
deterministic, no future-bar dependency. Full reasoning: `requirement_alignment.md`.

**No tuning**: zero code/config changes; 0.25% untouched; no alternative threshold or P&L computed; no
full-year 35-symbol run; no Task 22 inspection.

**Determinism**: no stochastic state; fidelity proven by the exact 2,473/2,473 cross-check against Task
37's independently-published output. Focused test suite reused: 237 passed, 0 failed.

**Final decision**: `CURRENT_VOLATILITY_GATE_MISALIGNED_WITH_PRODUCT_REQUIREMENT`.

**Next recommended action (not started)**: Task 39 — design (not tune, not P&L-optimize) the multi-timeframe
volatility-regime contract/formula, per the requirements listed above. Contract-design only.

**State**: Task 37 checkpoint committed and pushed (`df266c9c74e0afe41f99a51a327d3357dd6a11df`). This Task
38 ledger entry and all `results/task38_low_volatility_diagnostic/` artifacts — **not committed, not
pushed**, per instruction. PR #10 remains draft.

**2026-08-22 update (Task 39)**: this Task 38 ledger entry was committed as `4599d5948c26d5af0758e97e3dad53412b520f89`
(`docs(research): record low-volatility gate diagnostic`) and pushed at the start of Task 39.
`results/task38_low_volatility_diagnostic/` artifacts remain untracked (repo-wide `/results/` gitignored).
PR #10 confirmed still draft/open.

## Task 39 — Multi-Timeframe Volatility Regime Contract Design (2026-08-22)

**Objective**: design (not implement, not tune, not P&L-test) ONE clear, causal, live-computable
multi-timeframe volatility-regime contract, responding directly to Task 38's `MISALIGNED` finding. Design
only — no strategy code touched, no historical data processed, no full engine replay.

**Task 38 checkpoint**: committed and pushed as `4599d5948c26d5af0758e97e3dad53412b520f89`
(`docs(research): record low-volatility gate diagnostic`) before Task 39 began.

**Purpose statement (fixed first)**: "Is this symbol currently in a sufficiently active volatility regime
for the intraday strategy, relative to both recent intraday conditions and its broader normal volatility?" —
explicitly separate from the existing, unchanged 1-minute trigger-bar ATR test (`atr_move_multiplier`),
which remains valid.

**Models considered**: Model A (Absolute Multi-Timeframe, normalized ATR% on 2+ timeframes) — **selected**.
Model B (Relative-to-Self, percentile vs. own historical baseline) — conceptually the best fit for
cross-symbol comparability, but requires new persistent (20-60+ day) cross-restart state this system does
not have anywhere today — deferred. Model D (Normalized Ratio, short-term vs. broader baseline) — same
persistent-state gap as B, smaller in degree — deferred. Model C (Regime+Trigger separation) is not a
competing formula, it is the architectural principle already fixed by the purpose statement.

**Product-suggested formula reviewed as an option only, NOT adopted**: `ATR_14m / (ATR_14D / sqrt(390))`.
Explicitly assessed whether `sqrt(time)` scaling is appropriate for ATR specifically (not just standard
deviation) and found three distortions: (1) microstructure noise floor inflates 1-minute ATR beyond pure
diffusion scaling, (2) daily ATR partly reflects overnight gap risk with no intraday analog, (3) intraday
volatility is U-shaped, not flat — directly evidenced by Task 38's own session-split data (54.6% opening-window
pass rate vs. ~9% for the rest of the regular session). Needs empirical validation before trusting the
equivalence; recorded as a future candidate, not selected.

**Selected contract**: two-rung Absolute Multi-Timeframe — a **15-minute ATR% leg reusing the existing HTF
buffer entirely unchanged** (`RollingBarBuffer(210)` + `HtfBarAggregator(15, rth_only=True)`, the same buffer
already feeding `compute_htf_trend`/`compute_daily_pivots`), plus a **new 60-minute ATR% leg** (one new
`RollingBarBuffer` + one new `HtfBarAggregator(60, rth_only=False)` instance — same generic, already-proven
classes, zero new formulas, zero new bucketing logic). Both legs use the identical `pandas_ta.atr(length=14)`
call already relied on for the 1-minute case. The two legs are reported **separately** (not blended) as a
small `VolatilityRegimeSnapshot` — how they combine into a pass/fail rule and what numeric thresholds apply
are explicitly deferred to Task 40+. Daily timeframe **excluded** — Task 38 already proved it isn't
computable from available warm-up state without new persistent storage. **Redundancy check confirmed**: this
does NOT merely duplicate `current_bar_TR >= 1×ATR(14,1m)` — structurally different timeframe, different
underlying bars, different question.

**Session policy**: regime state changes continuously (never resets at a session boundary, matching the
existing 1-minute ATR's own 2026-08-16 precedent); each leg simply holds its last value between its own bar
closes. 15-minute leg stays regular-session-only (inherited convention, goes stale pre-market/after-hours);
60-minute leg is deliberately built continuous, staying live through pre-market/after-hours. Opening/closing
blackouts remain separate, untouched entry-timing gates — not special-cased in the regime read itself.

**`min_atr_pct` (0.25%) disposition**: `RETIRE_WHEN_NEW_REGIME_IMPLEMENTED` — not `RETAIN_AS_COMPONENT` (a
1-minute-calibrated number is a category error against a 15m/60m quantity) and not `REINTERPRET` (no
evidence-based reinterpretation exists without fresh calibration, which this task must not do). This is a
straightforward architectural consequence, not `OWNER_DECISION_REQUIRED` — what IS owner/future-task
decision-required is the eventual new numeric threshold(s) and the two-leg combination rule.

**Implementation feasibility**: smallest possible — one leg fully reused, one leg added via the same,
already-proven `RollingBarBuffer`/`HtfBarAggregator` classes and the same ATR formula, inheriting live/backtest
parity automatically via `aggregation.py`'s existing design guarantee. New state required only for the
60-minute buffer/aggregator pair.

**Warm-up/parity**: 15-min leg needs >14 bars (~3.5 regular-session hours) for a first reading, ~42-70 bars
(~2-3 trading days) to stabilize; 60-min leg (new) needs >14 bars (~2 continuous days) for a first reading,
~42-70 bars (~1-2 trading weeks) to stabilize; no daily bars needed (excluded). Connected explicitly to the
existing warm-up-capture gap: every buffer in this system is in-memory-only and cold-starts on restart today
— the new 60-minute buffer inherits this identical, already-known characteristic; not solved here, flagged
for whatever future task builds cross-restart persistence generally.

**No economic test**: no hypothetical signal count, trade count, R, PF, or threshold alternative computed.

**No tuning**: zero strategy code changed; `atr_move_multiplier` untouched; no threshold search; no Task 22
inspection; no full engine replay — reused Task 38's already-published evidence and existing source/docs
throughout.

**Final decision**: `MULTITIMEFRAME_VOLATILITY_CONTRACT_DEFINED`.

**Next recommended action (not started)**: Task 40 — minimal implementation of the two-rung regime snapshot
(15-minute reuse + new 60-minute buffer/aggregator) plus focused tests only. Must NOT run the historical
backtest, must NOT choose eligibility thresholds or a combination rule without a separate explicit decision
step, must NOT touch the unchanged 1-minute trigger test.

**State**: Task 38 checkpoint committed and pushed (`4599d5948c26d5af0758e97e3dad53412b520f89`). This Task
39 ledger entry and all `results/task39_multitimeframe_volatility_design/` artifacts — **not committed, not
pushed**, per instruction. PR #10 remains draft.

**2026-08-22 update (Task 40)**: this Task 39 ledger entry was committed as `c394c2d9689113419cb9cd430132775aa06c3411`
(`docs(research): define multi-timeframe volatility regime contract`) and pushed at the start of Task 40.
`results/task39_multitimeframe_volatility_design/` artifacts remain untracked (repo-wide `/results/`
gitignored). PR #10 confirmed still draft/open.

## Task 40 — Multi-Timeframe Volatility State Implementation & Parity (2026-08-22)

**Objective**: implement Task 39's designed two-rung volatility-regime STATE (15m reuse + new 60m
buffer/aggregator) with live/backtest parity and observability — explicitly NOT an eligibility gate. First
strategy-code implementation task since Task 35.

**Task 39 checkpoint**: committed and pushed as `c394c2d9689113419cb9cd430132775aa06c3411`
(`docs(research): define multi-timeframe volatility regime contract`) before Task 40 began.

**Files changed**: `talonx_backtest/engine.py` (+57/-2), `talonx_quant/config.py` (+12/-0),
`talonx_quant/consumer.py` (+81/-2), `talonx_quant/indicators.py` (+79/-0), new
`tests/test_volatility_regime.py` (17 tests). Purely additive — the only 2 deleted lines anywhere in the
diff are a single import statement reformatted (confirmed by grepping the diff for `^-` lines), zero existing
logic removed or reordered. `talonx_quant/buffer.py`, `talonx_quant/aggregation.py`,
`talonx_quant/schemas.py` byte-for-byte unchanged (SHA-256 confirmed) — proving genuine reuse, not
duplication.

**Regime snapshot**: new `talonx_quant.indicators.VolatilityRegimeSnapshot` (`atr_15m`, `atr_pct_15m`,
`ready_15m`, `atr_60m`, `atr_pct_60m`, `ready_60m`, `as_of` — no PASS/FAIL field), computed by one
authoritative `compute_volatility_regime` function called identically by both `engine.py` and `consumer.py`.

**15m implementation**: reuses the existing `buffer_htf`/`htf_aggregator` entirely unchanged — zero new
state, regular-session-only semantics preserved.

**60m implementation**: one new `RollingBarBuffer` + one new `HtfBarAggregator(60, rth_only=False)` instance
— same proven classes, zero new bucketing/ATR formula, deliberately continuous per Task 39's session policy.
New config: `regime_60m_bar_interval_minutes` (60), `regime_60m_max_bars` (60).

**Readiness semantics**: `ready_15m`/`ready_60m` report `False` honestly until each leg's own `>atr_period`
bar requirement is met — never a fake/zero value. Empirically confirmed on a 260-bar (~4.3h) fixture:
`ready_15m=True`, `ready_60m=False` (needs >14h). Zero signals blocked by regime state in Task 40.

**Live/backtest parity**: both paths call the identical `compute_volatility_regime` against buffers built by
the identical `RollingBarBuffer`/`HtfBarAggregator` classes — no separate wrapper. Directly tested
(numerical equality) via a bar sequence fed through both `BacktestEngine`'s per-bar path and `QuantScanner`'s
per-tick path independently.

**Observability**: `BacktestEngine.volatility_regime_snapshots`/`.regime_telemetry` (opt-in via
`research_telemetry=True`, mirroring the existing `volatility_telemetry` convention),
`QuantScanner._latest_regime_snapshot` — none reach `QuantSignal`, `Trade`, `TriggeringSignalRef`, or
Telegram/dispatch. Alert eligibility untouched.

**Warm-up capture**: extended the existing, already `buffer_type`-agnostic `checkpoint_buffer`/`load_buffer`
store mechanism to the 60-minute leg (checkpoint write + minimal no-gap-limit reload) — zero store schema
change needed. Deliberately deferred: a yfinance historical-backfill fallback for the 60m leg (analogous to
`_preseed_htf_if_needed`) — a materially larger separate feature, exact schema/gap documented in
`warmup_state_requirements.md` rather than built now.

**Zero strategy behavior change — proven, not assumed**: captured the TRUE pre-Task40 code via `git stash`
(reverting all 4 modified files), ran an identical small deterministic fixture, `git stash pop`ped to
restore, ran the identical fixture again, and diffed the two result sets. **`diff` exit code 0 — zero lines
of difference** across trades, signals_generated, signals_published, bars_processed, rejections, and the
full raw signal_log.

**Tests**: 17 new tests (`tests/test_volatility_regime.py`) covering 15m/60m aggregation and readiness, ATR%
calculation, invalid/zero/negative/NaN denominator handling, closed-bar causality, session behavior,
deterministic repeated state, live/backtest numerical parity, and the before/after proof. Focused suite (this
file + 9 existing files covering every touched code path): **310 passed, 0 failed** (63.7s). Full-repository
suite attempted but not completed — exceeded a 5-minute timeout at ~12-13% progress (~60+ min extrapolated);
deliberately not awaited to honor the 30-90 minute LIGHT-MEDIUM budget, an explicitly flagged residual gap,
not a hidden one.

**No tuning**: `min_atr_pct` (0.25%) not removed, not bypassed, byte-for-byte unchanged. 15m/60m legs not
wired into any eligibility path. No confluence/stop/R:R changes. No historical replay. No Task 22 inspection.

**Final decision**: `MULTITIMEFRAME_STATE_IMPLEMENTED_AND_PARITY_VALIDATED`.

**Next recommended action (not started)**: Task 41 — Multi-Timeframe Volatility Eligibility Contract
Calibration. Determine the combination rule and numeric thresholds for the 15m/60m legs using volatility
distributions and product semantics, explicitly NOT P&L optimization.

**State**: Task 39 checkpoint committed and pushed (`c394c2d9689113419cb9cd430132775aa06c3411`). This Task
40 code changes, tests, ledger entry, and all `results/task40_volatility_state/` artifacts — **not
committed, not pushed**, per instruction. PR #10 remains draft.

**2026-08-22 update (Task 41)**: this Task 40 change set (code + tests + ledger entry) was committed as
`9b58470f883b8aeb45dce0173972e045e9518aba` (`feat(quant): add multi-timeframe volatility regime state`) and
pushed at the start of Task 41, after re-confirming the 17-test `test_volatility_regime.py` suite still
passes. `results/task40_volatility_state/` artifacts remain untracked (repo-wide `/results/` gitignored).
PR #10 confirmed still draft/open.

## Task 41 — Multi-Timeframe Volatility Eligibility Contract Calibration (2026-08-22)

**Objective**: define ONE eligibility contract for the Task 40 15m + 60m volatility regime state, calibrated
by market semantics/distribution — explicitly NOT P&L optimization. No implementation, no trades, no
threshold sweep.

**Task 40 checkpoint**: committed and pushed as `9b58470f883b8aeb45dce0173972e045e9518aba` before Task 41
began.

**Integrity**: HEAD `9b58470f883b8aeb45dce0173972e045e9518aba`, QuantConfig `76bf7a395614`, BacktestConfig
`4a78bafa104e`, strategy version `6d0d49c8b0ca` — all match Task 40's recorded values exactly. Source data:
Task 38's already-downloaded 35-symbol/30-day window data and already-computed 27,039-row candidate-level
replay, both reused with zero re-download and zero engine replay.

**Distributions** (15m/60m ATR%, cross-symbol aggregate): 15-minute median 0.422% (p25 0.329%, p90 0.655%);
60-minute median 0.839% (p25 0.735%, p90 1.190%). Regular session consistently higher than pre-market/closed
at both timeframes. Full per-symbol/per-session breakdown: `regime_distributions.csv`.

**Three contracts compared** (market meaning/stability/symbol-fairness/session/readiness, NOT trade count):
A (BOTH_ACTIVE, symmetric median AND) — 33.97% coverage, 34/35 symbols; B (SLOW_REGIME_WITH_FAST_CONFIRMATION,
60m median AND 15m P25) — 38.93% coverage, 34/35 symbols; C (EITHER_ACTIVE, symmetric median OR) — 50.73%
coverage, 35/35 symbols, but rejected specifically because it is satisfiable by a single timeframe alone,
reintroducing the same single-timeframe-dependency weakness Task 38 found in the old 1-minute-only gate.

**Coverage check** (measurement only, no P&L, no trades, no downstream gates executed): current unchanged
1-minute gate passes 9.15% of the same 27,039 raw candidates. All three candidates widen this
dramatically; Contract B's 38.93% (RSI 36.39%/MACD 38.95%/MA 93.02%) is a 4.3x improvement while remaining
meaningfully selective. Full detail: `trigger_coverage.csv`.

**Selected contract: B (SLOW_REGIME_WITH_FAST_CONFIRMATION)** —
`eligible = ready_60m AND ready_15m AND (atr_pct_60m >= 0.839) AND (atr_pct_15m >= 0.329)`. Thresholds are
this task's own directly-measured percentiles (60m aggregate median, 15m aggregate P25) — not searched or
swept. 60m plays the primary regime-determinant role; 15m plays a confirmation role — matching the fixed
purpose statement's own two-part framing exactly. Selected over A (too symmetric, blurs the regime/
confirmation distinction) and C (see rejection reason above, despite higher raw coverage).

**Readiness policy**: 60m is the binding leg; `REGIME_STATE_NOT_READY` (never a fabricated eligible/
ineligible default) unless both legs are warmed up. Measured: 92.63% both-ready, 7.01% 15m-only-ready, 0.00%
60m-only-ready (structural — 60m always warms up slower under Task 40's buffer sizing), 0.36% neither-ready.

**Session policy**: 15m leg stays regular-session-only (Task 40, unchanged); 60m (the binding leg) stays
continuous, so Contract B eligibility remains determinable through pre-market/after-hours. Opening/closing
blackouts are NOT duplicated inside the regime logic — remain separate, untouched entry-timing gates.

**`min_atr_pct` (0.25%) disposition**: `RETAIN_TEMPORARILY_FOR_MIGRATION` — confirms Task 39's
`RETIRE_WHEN_NEW_REGIME_IMPLEMENTED` finding as the eventual target, recognizing "implemented" so far means
observability STATE only (Task 40), not an active eligibility gate. 0.25% stays exactly as-is through Task
42's implementation and a shadow observation period; retirement is a future task's decision.

**No P&L / no tuning / no threshold sweep**: confirmed throughout — no trade simulated, no downstream gate
executed, no candidate/RR/PF/expectancy computed, both thresholds are named already-observed distribution
percentiles, not a search. No confluence/stop/R:R change. No full-year run. No Task 22 inspection.

**Final decision**: `VOLATILITY_ELIGIBILITY_CONTRACT_DEFINED`.

**Next recommended action (not started)**: Task 42 — implement the selected Contract B eligibility function
+ focused tests only. Must NOT run historical P&L, must NOT wire the result into any actual signal-
eligibility decision (observability only, matching Task 40's own precedent), must produce zero signal/trade
behavior change (proven the same `git stash` before/after technique Task 40 used).

**State**: Task 40 checkpoint committed and pushed (`9b58470f883b8aeb45dce0173972e045e9518aba`). This Task
41 ledger entry and all `results/task41_volatility_eligibility/` artifacts — **not committed, not pushed**,
per instruction. PR #10 remains draft.

**2026-08-22 update (Task 42)**: this Task 41 ledger entry was committed as `7829afe`
(`docs(research): define multi-timeframe volatility eligibility contract`) and pushed at the start of Task
42. `results/task41_volatility_eligibility/` artifacts remain untracked (repo-wide `/results/` gitignored).
PR #10 confirmed still draft/open.

## Task 42 — Multi-Timeframe Volatility Eligibility Evaluator + Shadow Observability (2026-08-22)

**Objective**: implement the Task 41 Contract B evaluator and shadow comparison telemetry ONLY — must not
block/allow any signal. Enables Monday shadow mode to compare the current 1m LOW_VOLATILITY decision against
the new 15m+60m regime decision with zero trading-behavior change.

**Task 41 checkpoint**: committed and pushed as `7829afe` before Task 42 began.

**Evaluator implementation**: `talonx_quant.indicators.evaluate_regime(snapshot) -> RegimeEligibilityResult`
— one authoritative function, called identically by `talonx_backtest.engine` and `talonx_quant.consumer`.
Result: `eligible`, `ready`, `reason`, `atr_pct_15m`, `atr_pct_60m`, `threshold_15m`, `threshold_60m`,
`as_of`. Exactly the 5 required stable reasons.

**Provisional calibration values**: `PROVISIONAL_REGIME_15M_THRESHOLD_PCT = 0.329`,
`PROVISIONAL_REGIME_60M_THRESHOLD_PCT = 0.839` — Task 41's measured 15m aggregate P25 / 60m aggregate median,
named with an explicit `PROVISIONAL_` prefix, module-level comment citing Task 41/42, deliberately NOT
represented as `QuantConfig` fields (which would read as production-tunable). No threshold sweep.

**NOT wired into eligibility** (verified, not assumed): `min_atr_pct=0.25%` remains byte-for-byte unchanged,
the sole active gate. `evaluate_regime`'s output is consulted only by shadow telemetry.

**Readiness**: preserves and tightens Task 40's semantics — `ready=False` (never a fabricated value) when
either leg is unwarmed OR either `atr_pct` is `None` despite warm-up. No 15m-only fallback exists, directly
tested. 60m-not-ready → `REGIME_STATE_NOT_READY`, exactly as required.

**Shadow telemetry**: every required field captured, plus 5-category disagreement classification
(`BOTH_PASS`/`BOTH_FAIL`/`OLD_FAIL_NEW_PASS`/`OLD_PASS_NEW_FAIL`/`NEW_NOT_READY`, the last taking priority).
Backtest: opt-in `BacktestEngine.regime_shadow_comparisons` list (mirrors Task 40's `regime_telemetry`
convention). Live: Redis per-stage metric counters (`_incr_metric`, the same mechanism already feeding
`talonx_dispatch`'s Daily Funnel dashboard) + structured `logger.info` lines — deliberately no unbounded
in-memory list on the live side (long-running process) and no Telegram noise. `/ping` exposure deliberately
deferred (optional per instruction).

**Live/backtest parity**: one shared `evaluate_regime`/`classify_regime_shadow_disagreement` pair, no
per-path wrapper; live path verified to run without error against Task 40's already-parity-tested buffers.

**Zero behavior change — proven, not assumed**: same `git stash` before/after technique Task 40 used —
`diff` exit code 0, zero lines of difference across trades/signals/rejections/signal_log. One consumer.py
line was refactored (bare `_fails_min_volatility()` call extracted into a variable for telemetry reuse) —
directly confirmed behavior-neutral by this same proof.

**Tests**: 22 new tests (`tests/test_regime_eligibility_evaluator.py`) covering threshold logic, all
readiness combinations, no-fallback behavior, exact boundary, NaN handling, all 5 disagreement
classifications, determinism, and live/backtest parity. Focused suite (this file + 10 existing files,
including Task 40's own suite): **332 passed, 0 failed** (88.4s). Full repository suite not re-attempted,
per Task 40's own established precedent (exceeds the LIGHT-MEDIUM budget).

**Monday shadow report**: full specification written (`monday_shadow_report_spec.md`) — not a filled-in
report, since no live shadow session has run yet. Defines top-line metrics, the 5-category disagreement
breakdown, and per-symbol breakdown for a future task to compute once real telemetry accumulates.

**No historical backtest / no P&L / no tuning**: confirmed — all correctness evidence from small
deterministic fixtures and unit tests; `min_atr_pct` not touched/replaced/bypassed; no confluence/stop/R:R
change; no Task 22 inspection.

**Final decision**: `REGIME_SHADOW_EVALUATOR_VALIDATED`.

**Next recommended action (not started)**: Task 43 — Monday Shadow Readiness & Fast Regime Comparison
Validation. Do NOT wire the new regime into production eligibility yet.

**State**: Task 41 checkpoint committed and pushed (`7829afe`). This Task 42 code changes, tests, ledger
entry, and all `results/task42_regime_shadow/` artifacts — **not committed, not pushed**, per instruction.
PR #10 remains draft.

**2026-08-22 update (Task 43)**: this Task 42 change set (code + tests + ledger entry) was committed as
`2602152176c38494ddf5f7ad73b05851fd81524f` (`feat(quant): add shadow multi-timeframe volatility evaluator`)
and pushed at the start of Task 43, after re-confirming the 22-test `test_regime_eligibility_evaluator.py`
suite still passes. `results/task42_regime_shadow/` artifacts remain untracked (repo-wide `/results/`
gitignored). PR #10 confirmed still draft/open.

## Task 43 — Monday Shadow Readiness & Fast Regime Comparison Validation (2026-08-22)

**Objective**: freeze and validate a Monday shadow-ready build. No strategy behavior change. Pure
investigation/documentation task — zero code written.

**Task 42 checkpoint**: committed and pushed as `2602152176c38494ddf5f7ad73b05851fd81524f` before Task 43
began.

**Frozen Monday build**: HEAD `2602152176c38494ddf5f7ad73b05851fd81524f`, tracked tree 100% clean.
QuantConfig `76bf7a395614`, BacktestConfig `4a78bafa104e`, strategy `c9b095afc319`, regime evaluator module
hash `153a37a05a5aa0a0`.

**No capital path**: `SHADOW_ONLY_CONFIRMED` — a dedicated 5-point code audit (broker API calls, paper→live
switch, fill-simulation mechanism, entrypoint gating, broker SDK dependencies) found zero reachable
capital-order path in the run/startup import graph. `talonx_paper` is pure in-memory/SQLite simulation;
`run_talonx.py` wires up only `PaperTradingEngine`/`LongTermPaperEngine`; no live-broker SDK exists in any
`requirements.txt`.

**Watchlist**: discovered a real, existing, already-operational production `TickerWatchlistStore` (35 active
symbols, last modified 2026-08-18) — used this instead of Task 37's separate research sample, per
instruction's own escape clause. No strategy change from Task 37's findings applied to Monday's build.

**Startup/warm-up**: 1m/15m buffers have real prior persisted checkpoints (last bar 2026-08-20) — Monday is
a warm restart for these, correctly falling back to existing preseed/backfill for fast readiness. The
**60-minute leg has no persisted checkpoint at all** (its mechanism postdates that prior run) — a true cold
start, most likely `NOT_READY` for most/all of Monday (needs >14 continuous hours). Confirmed expected
behavior, not a defect — `evaluate_regime` never fabricates a value.

**Warmup capture gap assessment**: the persisted raw bars (1m/15m/60m, generic `buffer_type`-keyed store)
are already sufficient to exactly reconstruct ATR values, readiness, and full regime snapshots, since
`compute_volatility_regime`/`evaluate_regime` are pure, deterministic functions of those bars. **No new code
was needed or written** — Task 40's existing capture mechanism is already sufficient for replay.

**Live telemetry**: all required SYSTEM/PER-SYMBOL/VOLATILITY-COMPARISON/GEOMETRY items confirmed present —
pre-existing infrastructure (system health, funnel, rejections, paper lifecycle, geometry) plus Task 42's own
8 volatility-comparison fields. Zero gaps requiring new code.

**`/ping`**: confirmed unmodified since before Task 40, still read-only. New regime-shadow counters
deliberately not added to Telegram output (consistent with Task 42's reasoning) — live in Redis/logs only.

**Offline report smoke test**: all 6 required sections (system health, signal funnel, old-vs-new regime
comparison, per-symbol disagreement, paper lifecycle, geometry) produced successfully from a deterministic
fixture, zero P&L anywhere.

**Tests**: 515 focused tests passed, 0 failed, across quant strategy/consumer/indicators/buffer, Task 40/42's
own volatility-state/evaluator suites, paper engine/consumer/store, backtest geometry/telemetry/
regression/lookahead/lifecycle. Zero new failures.

**GO/NO-GO**: every directly-verifiable check passes. Redis/live-feed reachability are inherent
live-environment preconditions this research sandbox cannot confirm — already the explicit first steps of
the written runbook, not blockers this review discovered.

**No strategy changes**: confirmed — zero code changes in this task; `min_atr_pct` untouched; no
confluence/stop/R:R change; no historical backtest; no Task 22 inspection.

**Final decision**: `MONDAY_SHADOW_GO_WITH_OBSERVABILITY_CAVEAT` — caveat: the 60-minute regime leg will
most likely remain `NOT_READY` for most/all of Monday (expected, non-blocking); the full 15m+60m comparison
needs several consecutive days of continuous operation to become statistically meaningful.

**Next action (exactly one)**: Monday live SHADOW/PAPER observation only, per the written runbook. Do NOT
wire the new regime into production eligibility.

**State**: Task 42 checkpoint committed and pushed (`2602152176c38494ddf5f7ad73b05851fd81524f`). This Task
43 readiness artifacts and ledger entry — **not committed, not pushed**, per instruction. PR #10 remains
draft.

**2026-08-22 update (Task 44)**: this Task 43 ledger entry was committed as `7da9af4`
(`docs(research): record Monday shadow readiness`) and pushed at the start of Task 44.
`results/task43_monday_shadow_readiness/` artifacts remain untracked (repo-wide `/results/` gitignored).
PR #10 confirmed still draft/open.

## Task 44 — 60m Shadow-Regime Historical Warmup Bootstrap (2026-08-22)

**Objective**: remove the 60m cold-start observability caveat by bootstrapping the existing 60m
aggregator/ATR state from causal historical 1m bars before live processing. Zero trading behavior change.

**Task 43 checkpoint**: committed and pushed as `7da9af4` before Task 44 began.

**Root cause of cold start**: Task 40's 60m leg had no historical-backfill path (a deliberate, documented
scope decision) — only live ticks could ever warm it, requiring >14 continuous hours.

**Bootstrap architecture**: reuses `talonx_quant.preseed.fetch_1m_history` (the SAME function the existing
1-minute buffer preseed already uses — no second data-loading system), feeding historical bars through a
newly-extracted shared `_feed_60m_bar` step that both the live tick path and the new bootstrap path call
identically (`HtfBarAggregator.update()` → `RollingBarBuffer.add_bar()`) — one authoritative aggregation
path, no second ATR formula. `regime_60m_bootstrap_period="5d"` chosen empirically (measured: "1d"=957 bars,
"5d"=4,785 bars, "7d"=6,704 bars) — not a new stability threshold, just a data-sourcing decision that
comfortably clears the existing >14-bar readiness rule and the ~42-70 bar Wilder-convergence window.

**Causality/dedup rules**: bootstrap bars are, by construction, always at-or-before the fetch's own
wall-clock moment. A new `_bootstrap_60m_cutoff` skips any live tick at-or-before the last bootstrapped
minute. **A real bug was found and fixed during testing**: re-feeding a historical range overlapping an
already-partially-forming bucket double-counted volume (the aggregator's `+=` accumulation cannot itself
distinguish a legitimate new tick from an overlapping re-feed) — fixed by adding a small, additive
`HtfBarAggregator.reset(symbol)` method, called before the bootstrap feed loop, caught by
`test_checkpoint_bootstrap_overlap_is_idempotent_via_upsert`.

**Insufficient history**: fails honestly — `ready_60m=False`, `REGIME_STATE_NOT_READY`, no 15m-only
fallback, no fabricated ATR, no zero, no borrowed state.

**Restart priority**: a valid persisted checkpoint (>14 bars) skips the network fetch entirely; otherwise
bootstrap, made idempotent even under a partial-checkpoint overlap via the new `reset()` call.

**Parity result — the central proof**: continuous live feed vs. bootstrap-prefix-plus-live-suffix produce
byte-identical 60m state, `VolatilityRegimeSnapshot`, and `evaluate_regime` result. **PASS.**

**Immediate Monday readiness coverage (honest, real measurement)**: against the actual 35-symbol production
watchlist, an early concurrent measurement returned 18/35 ready; a later sequential measurement (matching
production's real `preseed_symbols()` loop exactly) returned 0/35 ready, all `NO_HISTORY_RETURNED` — this
reflects yfinance rate-limiting accumulated across this long research session in this sandbox (confirmed via
an independent retry that failed identically), **not a code defect** — the bootstrap correctly reported
`NOT_READY` for every affected symbol rather than crashing or fabricating a value. AAPL and others were
fetched successfully multiple times earlier in the same session before the rate limit was reached, proving
the fetch mechanism itself works. Flagged as a real operational risk for Monday's evidence capture, not a
correctness blocker.

**Zero behavior change**: `git stash` before/after (same technique as Task 40/42) — `diff` exit code 0,
byte-for-byte identical trades/signals/rejections/signal_log. `talonx_backtest/engine.py` has zero diff
lines in this task (a backtest always has its full dataset from the start).

**Tests**: 14 new tests (`tests/test_60m_bootstrap.py`), 14 passed, 0 failed. Broader focused regression (17
files, 529 tests): 0 failures.

**Monday safety reconfirmed**: no real broker path, new regime still observability only, active gate still
`min_atr_pct=0.25%`, unchanged.

**Final decision**: `60M_BOOTSTRAP_VALIDATED_WITH_PARTIAL_SYMBOL_READINESS` — mechanism fully validated via
deterministic tests; live 35-symbol measurement in this sandbox showed rate-limit-constrained readiness
rather than a clean fully-ready result.

**Next recommended action (not started)**: Task 45 — Monday Run Manifest + Evidence Fingerprinting, should
include live 60m-readiness telemetry as part of Monday's evidence capture so the actual production-day
outcome (not this sandbox's constrained measurement) is what gets reported. Do not modify strategy
eligibility.

**State**: Task 43 checkpoint committed and pushed (`7da9af4`). This Task 44 code changes, tests, ledger
entry, and all `results/task44_60m_warmup_bootstrap/` artifacts — **not committed, not pushed**, per
instruction. PR #10 remains draft.

**2026-08-22 update (Task 45)**: this Task 44 change set (code + tests + ledger entry) was committed as
`65b2e65` (`feat(quant): bootstrap 60m volatility state causally`) and pushed at the start of Task 45, after
re-confirming its 14-test suite passes. `results/task44_60m_warmup_bootstrap/` artifacts remain untracked
(repo-wide `/results/` gitignored). PR #10 confirmed still draft/open.

## Task 45 — Experimental Multi-Timeframe Volatility Gate Wiring + Correctness Validation (2026-08-22)

**Objective**: add an explicit experimental research/backtest mode that can use the 15m+60m regime instead
of the current `min_atr_pct` gate. Default/live behavior must remain unchanged. Implementation +
correctness only — no historical backtest, no economic conclusion.

**Task 44 checkpoint**: committed and pushed as `65b2e65` before Task 45 began.

**Mode design**: `talonx_quant.config.VolatilityGateMode` — exactly two members, `CURRENT_1M` (default) and
`MULTITIMEFRAME_EXPERIMENTAL`, constructed via `VolatilityGateMode(os.environ.get(...))` which itself raises
immediately on any invalid value (fail-closed at config-module-import time).

**Default/current invariant (mandatory, proven)**: `CURRENT_1M` reuses `_fails_min_volatility` and the
`"LOW_VOLATILITY"` rejection string byte-for-byte unchanged — proven via the same `git stash` before/after
technique Tasks 40/42/44 used (`diff` exit code 0) plus a dedicated unit-level regression test.

**Experimental wiring**: one shared dispatch function,
`talonx_quant.consumer._evaluate_active_volatility_gate`, called identically by `engine.py` and
`consumer.py`, containing zero threshold logic of its own — both inputs computed upstream by the unchanged
`_fails_min_volatility`/`evaluate_regime`. Active condition:
`ready_15m AND ready_60m AND atr_pct_15m >= 0.329 AND atr_pct_60m >= 0.839`.

**Readiness/rejection semantics**: a single new canonical rejection reason, `"LOW_VOLATILITY_REGIME"` — the
strategy rejection enum was not exploded; `evaluate_regime`'s 5 existing detail reasons preserved
separately. Experimental mode: either leg not ready → `REGIME_STATE_NOT_READY`, no fallback, no fabricated
value. `CURRENT_1M` mode: regime readiness has zero effect on eligibility.

**Evaluation order**: exactly one step swapped (the volatility predicate); trigger generation, confluence,
trend, blackout, R:R, and stop/target logic remain unmoved, unaware a mode selection exists — proven via a
mode-agnostic `evaluate_signals` unit test.

**Live safety**: two independent layers — `VolatilityGateMode`'s own constructor rejects invalid values at
import time; `QuantScanner.__init__` (the live/paper-shadow execution class, per Task 43's capital-path
audit) explicitly raises if `volatility_gate_mode != CURRENT_1M`, before any market tick is processed.
`BacktestEngine` deliberately unrestricted.

**Fingerprinting**: `config_hash` differs correctly between modes (`QuantConfig` `24fb06bdafa1` vs.
`1eb58828ad69`; `BacktestConfig` `becc5011a543` vs. `7096a993d034`); `strategy_version` (file-content-based)
stays a single explainable value (`a33b43f3794a`) shared by both modes, exactly as expected.

**Deterministic fixtures**: all 7 required (A: old pass/new fail, B: old fail/new pass, C: both pass, D:
both fail, E: not ready, F: exact 15m boundary, G: exact 60m boundary) — pass.

**Tests**: 22 new tests (`tests/test_volatility_gate_mode.py`), 22 passed, 0 failed. Broader focused
regression (19 files, 551 tests): 0 failures.

**No economic conclusion**: confirmed — no 35-symbol historical run, no profitability/PF/cost-sensitivity/
threshold-comparison analysis anywhere in this task.

**Final decision**: `EXPERIMENTAL_REGIME_GATE_IMPLEMENTED_AND_VALIDATED`.

**Next recommended action (not started)**: Task 46 — Fast 35-Symbol Experimental Regime Validation, using a
bounded, mechanically selected validation sample, measuring funnel/frequency/economics without threshold
tuning.

**State**: Task 44 checkpoint committed and pushed (`65b2e65`). This Task 45 code changes, tests, ledger
entry, and all `results/task45_experimental_regime_gate/` artifacts — **not committed, not pushed**, per
instruction. PR #10 remains draft.

**2026-08-22 update (Task 46)**: this Task 45 change set (code + tests + ledger entry) was committed as
`23db3fc` (`feat(quant): add experimental multi-timeframe volatility gate`) and pushed at the start of Task
46, after re-confirming its 22-test suite passes. `results/task45_experimental_regime_gate/` artifacts
remain untracked (repo-wide `/results/` gitignored). PR #10 confirmed still draft/open.

## Task 46 — Fast 35-Symbol Experimental Regime Validation (2026-08-22)

**Objective**: bounded out-of-development comparison of CURRENT_1M vs. MULTITIMEFRAME_EXPERIMENTAL on
identical data — a GO/NO-GO gate for a broader Task 47 run. Measurement only, no tuning.

**Task 45 checkpoint**: committed and pushed as `23db3fc` before Task 46 began.

**Window selection (declared before viewing any outcome)**: same real trading-day calendar Task 38/41 used,
at different (20%/60%/80% vs. Task 38/41's ~4%/48%/92%) percentage marks — programmatically verified
non-overlapping with the development windows. X_early (2025-10-27→10-31), Y_middle (2026-03-23→03-27),
Z_late (2026-06-03→06-09), 15 trading days total. Width mechanically reduced from 10 to 5 trading days
(runtime-budget decision, declared before running) to keep the required two full engine passes within the
60-120 min target — actual combined runtime came in at 120.9 min (58.3 + 62.6), higher than the 77.8 min
estimate but both runs completed without needing a mid-run reduction.

**Universe/data**: same reviewed 35-symbol universe as Task 37/38/41; 10 originals sliced from existing
local full-year data (zero new download), 25 additional symbols freshly downloaded via Alpaca (75/75
FULL, zero failures). Data quality clean, zero critical corruption, all symbols present in all windows.

**Identical execution confirmed**: `config_hash` differs only as expected (`24fb06bdafa1` vs.
`1eb58828ad69`) — the sole config difference is `volatility_gate_mode`.

**Headline result — zero executed trades in BOTH modes**: CURRENT_1M: 1,295 raw triggers, 7 published (all
bearish-while-flat), 0 trades. EXPERIMENTAL: 6,506 raw triggers (5x), 139 published (~20x, all
bearish-while-flat), 0 trades. LOW_VOLATILITY(_REGIME) remains dominant in both (85.7% of bars vs. 48.7% — a
real, substantial reduction, consistent with Task 41's offline coverage measurement) but LOW_CONFLUENCE
scaled up proportionally with the larger surviving candidate pool (847 → 4,209). The wider funnel did not
produce a single bullish published signal in either mode across this 3-week sample.

**Detail-reason breakdown not captured**: `REGIME_STATE_NOT_READY`/`15M_BELOW`/`60M_BELOW`/`BOTH_BELOW` were
not persisted in this run's saved output (canonical `LOW_VOLATILITY_REGIME` reason only) — flagged as a
capture gap for a future run script, not re-run to avoid an additional ~60 min pass, since it would not
change the core zero-trades finding.

**Product-frequency test**: 0.0 trades/week in both modes; 0/15 entry days, 0/35 symbols traded in either
mode. Success explicitly not declared on the upstream funnel movement alone.

**Economics/cost/statistical uncertainty/concentration/window-robustness**: all N/A — zero trades in both
modes at every cost level and in every window; no figure fabricated or approximated from an empty sample.
The zero-trade outcome IS consistently repeated across all 3 windows in both modes.

**Structural/risk invariants**: no trades occurred so none could be violated by this run; independently
proven unchanged by Task 45's own 551-test regression pass.

**Cost robustness classification**: `INSUFFICIENT_SAMPLE`.

**No tuning**: confirmed — all thresholds/gates/costs frozen exactly as Task 45 left them; window selection
frozen before any outcome was viewed; no Task 22 inspection.

**Final decision**: `INSUFFICIENT_SAMPLE` — neither advancing to Task 47's broader validation nor rejecting
the experimental gate is supported; there is no trade-level data yet to judge economics on.

**Next recommended action (not started)**: Task 47 (bounded) — extend the out-of-development validation
sample (revert to/exceed the original 10-trading-day window width and/or add windows) specifically to reach
a nonzero executed-trade count in at least one mode before attempting any economic comparison again. Still
bounded, still zero tuning.

**State**: Task 45 checkpoint committed and pushed (`23db3fc`). This Task 46 ledger entry and all
`results/task46_fast_regime_validation/` artifacts — **not committed, not pushed**, per instruction. PR #10
remains draft.

## Task 47 — Bullish Signal Path & Confluence Attrition Diagnostic (2026-08-22)

**Objective**: explain precisely why zero bullish signals survived to executable long trades in Task 46's
MULTITIMEFRAME_EXPERIMENTAL run. Diagnostic only — no strategy tuning.

**Task 46 checkpoint**: committed and pushed as `43f48bb` (`docs(research): record fast experimental regime
validation`) before Task 47 began. PR #10 confirmed draft/open.

**Population analyzed**: Task 46's `_signal_log_multitimeframe_experimental.parquet` — 6,506 raw,
post-regime-gate candidates (3,217 bullish / 3,289 bearish). Canonical count validation against Task 46's
own saved distributions: **PASS** (direction, `signal_type`, `confluence_score`, and `risk_reward_ratio`
null counts all match exactly). All gate semantics traced from live code (`strategy.py`, `consumer.py`,
`session.py`, `indicators.py`), not documentation. A focused test pass (session/blackout/confluence/trend
suites) came back 123 passed, 0 failed.

**Bullish vs bearish funnel**: LOW_CONFLUENCE is the single largest attrition point for bullish candidates
(87.5% all-failure basis, first-failure 2,063/3,217) but is nearly symmetric across direction
(confluence-eligible: 12.5% bullish vs. 13.4% bearish) — it is not the source of the directional asymmetry.
The asymmetry comes from bullish-exclusive gates: HTF_DATA_UNAVAILABLE (43.3% all-failure),
TREND_GATE (11.2%), and CLOSING_BLACKOUT (bullish-only, bearish exits always allowed through).

**Primary bullish attrition causes (ranked)**: (1) LOW_CONFLUENCE, largest single gate, symmetric across
direction; (2) LOW_RISK_REWARD (46.0% all-failure); (3) HTF_DATA_UNAVAILABLE (43.3%, bullish-only); (4)
US_MARKET_SESSION_CLOSED (19.4%, an unconditional session-closed drop not previously isolated in Task 46's
saved output); (5) TREND_GATE (11.2%, bullish-only, smaller in isolation than HTF unavailability).

**Confluence family alignment**: MACD is **MISALIGNED** — measured 100% self-credit rate across all 6,243
MACD-triggered candidates (`_macd_crossed_this_bar` credits the same crossover that fired the trigger),
confirming Task 33's earlier finding on an independent population. RSI is **AMBIGUOUS/leaning
INTENDED_SELECTIVITY** — its own confluence leg is structurally near-unreachable for RSI-triggered
candidates (0% true rate measured, both directions) because the trigger fires on RSI *recovering out of*
the extreme zone while the confluence leg requires RSI still *inside* it; RSI candidates depend entirely on
incidental MACD/volume co-occurrence to reach threshold. MA remains **ALIGNED** (carried forward from Task
33, sample too small here for new evidence).

**Trend gate contribution**: secondary, not primary — TREND_GATE itself rejected only 13 bullish candidates
first-failure / 359 all-failure basis, smaller than HTF_DATA_UNAVAILABLE or LOW_CONFLUENCE. Trend/HTF
reconstruction was only exact for the 10/35 symbols with sufficient full-year lookback (200x15-min RTH bars
needs ~50 trading days, unavailable from the other 25 symbols' window-local-only data) — documented gap,
not force-approximated.

**R:R contribution**: not a source of directional asymmetry — bullish `rr_available` (83.4%) was actually
higher than bearish's (65.6%), consistent with `calculate_trade_geometry`'s fail-closed
`risk_reward_ratio=None`-unless-structural-target posture explaining the 25.6% null rate observed in Task
46 (not a bug).

**Directional asymmetry source**: the interaction of (a) already-severe, roughly-symmetric confluence
attrition, (b) bullish-exclusive TREND_GATE/HTF_DATA_UNAVAILABLE/CLOSING_BLACKOUT, and (c) a **stateful
COOLDOWN/throttle-window mechanism** (armed on every publish regardless of direction, `consumer.py:2229-
2261`) that disproportionately absorbs bullish's much rarer survivors given bearish's ~8.6x higher
strategy-gate-clean pass rate (206 vs. 24) on shared tickers. This stateful gap was evidenced directly:
strategy-gate-clean counts (206 bearish, 24 bullish) both exceed Task 46's actual published counts (139
bearish, 0 bullish) — not reconstructable further without a full temporal replay.

**Requirement vs implementation classification**: MACD self-credit = `REQUIREMENT_MISALIGNMENT` (proven,
actionable). RSI's near-unreachable own-leg = `AMBIGUOUS`/leaning `INTENDED_SELECTIVITY` (a product-intent
question, not a code defect). Bullish-exclusive TREND_GATE/HTF_DATA_UNAVAILABLE/CLOSING_BLACKOUT =
`INTENDED_SELECTIVITY` (documented, deliberate LONG_ONLY risk design). The final zero-bullish-published
outcome via stateful cooldown interaction = `INSUFFICIENT_EVIDENCE` (not itself tested).

**Final decision**: `MULTIPLE_INTERACTING_GATES_REQUIRE_FIX` — no single gate explains the zero-bullish
outcome; it is produced by the interaction of symmetric confluence attrition, bullish-exclusive directional
gates, and asymmetric stateful cooldown absorption. Full reasoning: `next_bottleneck.md`.

**No tuning**: confirmed — no threshold, trigger, confluence logic, trend gate, blackout, structural stop,
R:R, symbol, or Task 46 window was changed; no new historical replay run; Task 22 not inspected; no capital
used.

**Next recommended action (not started)**: minimal, bounded correction — remove MACD's confluence
self-credit (require the confirmation leg to be independent of the candidate's own trigger family) in
`_confluence_score`, plus a measurement-only before/after re-check against Task 46's already-saved
`signal_log` (no new engine replay). Does not promise a nonzero bullish trade count — the directional gates
and stateful cooldown remain separate, unresolved contributors requiring their own dedicated diagnostics.

**State**: Task 46 checkpoint committed and pushed (`43f48bb`). This Task 47 ledger entry and all
`results/task47_bullish_attrition/` artifacts — **not committed, not pushed**, per instruction. PR #10
remains draft.

## Task 48 — Bullish Clean-Survivor Publication / Cooldown Trace (2026-08-22)

**Objective**: explain candidate-by-candidate why Task 47's 24 bullish strategy-gate-clean candidates did
not publish. Stateful publication diagnostic only — no confluence/cooldown/threshold changes.

**Task 47 checkpoint**: committed and pushed as `6589974` before Task 48 began. PR #10 confirmed draft/open.

**24-candidate population proof**: reconstructed exactly from Task 46's saved `signal_log` using Task 47's
own strategy-gate-clean definition — **24 bullish / 206 bearish, both validated by assertion.**

**Publication state machine traced from live code** (`talonx_backtest/engine.py:582-718` — the module that
actually produced Task 46's numbers, not the Redis-backed live `consumer.py`): `US_MARKET_SESSION_CLOSED` →
`OPENING_BLACKOUT` → `CLOSING_BLACKOUT`(bullish) → `LOSS_LOCKOUT` → `COOLDOWN`(1st check, pre-confluence) →
`LOW_CONFLUENCE` → `LOW_RISK_REWARD` → `HTF_DATA_UNAVAILABLE` → `TREND_GATE` → `PREMARKET_LIQUIDITY`
(unconditional, no quote feed) → per-bar throttle pool (all 35 symbols) → rank by Composite Opportunity
Score, release top `throttle_max_signals=3` → `COOLDOWN`(2nd check) → revalidate → publish → arm cooldown
(`cooldown_seconds=1200`, any direction, per-symbol).

**Fidelity validation**: a full deterministic replay of all 6,506 candidates in time order reproduced Task
46's 139 published bearish signals **exactly** (139/139, terminal reasons: 139 published, 57
`PREMARKET_LIQUIDITY`, 8 `THROTTLE_ACTIVE`, 2 `COOLDOWN_ACTIVE`) — proving the state-machine reconstruction
is faithful. For bullish: 19/24 resolved cleanly as `PREMARKET_LIQUIDITY` (stateless, unconditional in this
no-quote-feed engine); the remaining 5 (all AMD/STX, regular session) were **not** blocked by
`COOLDOWN_ACTIVE` or `THROTTLE_ACTIVE` in the reconstruction (0/24 stateful suppressions measured) yet
Task 46's actual run published 0 bullish, not 5 — an honestly-reported, unresolved discrepancy. Leading
(unconfirmed) hypothesis: this task's `TREND_GATE`/HTF-SMA200 reconstruction (calendar-aligned resample) does
not exactly reproduce the live `HtfBarAggregator`'s session-anchored bucketing — the one gate that differs
between bullish/bearish and the one not exactly replicated. Classified `INSUFFICIENT_STATE_EVIDENCE`, not
asserted as fact; rebuilding the exact aggregator was judged to exceed this task's LIGHT budget.

**Suppression reasons**: no bullish candidate was classified `COOLDOWN_ACTIVE`, `THROTTLE_ACTIVE`,
`DUPLICATE_SUPPRESSED`, `STATE_MACHINE_SUPPRESSED`, or `PREVIOUS_BEARISH_PUBLISH_STATE` — none of the
requested stateful terminal reasons actually fired for any of the 24.

**Preceding-event attribution**: only 2 candidates in the entire population were ever terminated by
`COOLDOWN_ACTIVE` (both bearish, suppressed by a prior bearish publish on the same symbol, 840s/240s
earlier). Zero bullish suppressions traced to any preceding event — Task 47's "bearish publishes consume
future bullish opportunities" hypothesis is **not supported** by this population.

**Counterfactual measurement**: bullish published count is identical (5) whether cooldown, throttle, or
both are removed — stateful gating was never the constraint for bullish in this sample. Bearish published
count rises modestly (139→149) as constraints relax, confirming those mechanisms bind meaningfully on the
higher-frequency bearish side but have zero measured bearing on bullish. No P&L computed.

**Cooldown contract assessment**: per-symbol, direction-agnostic, armed on any publish (executable or
informational) regardless of direction — architecturally capable of bearish-flat telemetry suppressing a
bullish entry opportunity, but zero such instances observed in this population. Classified `AMBIGUOUS` (not
`ALIGNED` — no requirement affirmatively endorses this; not `REQUIREMENT_MISALIGNMENT` — no measured harm).

**Long-only product interpretation**: bearish publications are exit/telemetry information under LONG_ONLY,
never entries; the design lets that telemetry consume the same per-symbol lock slot a genuine new long
opportunity would need. A real asymmetry-of-consequence, but not proven to have cost a trade here.

**Whether zero bullish is explained**: `ZERO_BULLISH_NOT_EXPLAINED_BY_STATEFUL_GATING` — stateful
publication gating explains 0 of the 24 candidates' non-publication; 19 are stateless-gate explained, 5
remain unresolved with a stateless (not stateful) leading hypothesis.

**Final decision**: `STATEFUL_PUBLICATION_BEHAVIOR_AMBIGUOUS`.

**Next-fix priority**: `FIX_MACD_CONFLUENCE_SELF_CREDIT_FIRST` — the stateful mechanism has no proven
defect to fix (0 confirmed cross-direction suppressions); MACD self-credit remains a proven, large-magnitude,
low-risk-to-fix requirement violation from Task 47.

**No strategy changes**: confirmed — no cooldown/throttle/confluence/volatility/trigger/trend/R:R/threshold
change made; no P&L computed; no extended historical run; Task 22 not inspected; no capital used.

**Next recommended action (not started)**: implement the Task 47-recommended MACD confluence self-credit
correction (require the confirmation leg to be independent of the candidate's own trigger family) plus a
measurement-only before/after re-check against Task 46's saved `signal_log`. The cooldown/throttle
direction-agnostic design remains a flagged, unresolved product question for the owner, not an
implementation task.

**State**: Task 47 checkpoint committed and pushed (`6589974`). This Task 48 ledger entry and all
`results/task48_bullish_stateful_trace/` artifacts — **not committed, not pushed**, per instruction. PR #10
remains draft.

## Task 49 — Minimal MACD Confluence Self-Credit Correction + Bounded Validation (2026-08-22)

**Objective**: correct the proven MACD confluence self-credit requirement violation (Task 47), validate
correctness, measure impact on the existing Task 46 population. Requirement-correctness fix, not an
optimization for more trades.

**Task 48 checkpoint**: committed and pushed as `ed63a52` before Task 49 began. PR #10 confirmed draft/open.

**Proven MACD requirement mismatch**: `_confluence_score()` (`talonx_quant/strategy.py`) awarded a MACD leg
whenever `_macd_crossed_this_bar(s)` was true, with no awareness of which family triggered the candidate —
for a MACD-triggered candidate that condition is always true by construction (it IS the trigger condition),
so the leg always self-credited (100% rate, Task 47).

**Exact code correction**: `_confluence_score` gained one parameter (`signal_type`) and one clause
(`and not own_trigger_is_macd`) on its existing MACD-leg condition — excludes the leg specifically when
`signal_type` is `MACD_BULLISH_CROSS`/`MACD_BEARISH_CROSS`. RSI leg, volume leg, `confluence_score_min`,
and every other gate/threshold byte-for-byte unchanged. One call site (`_build_signal`) updated to pass the
`signal_type` it already had in scope.

**Tests**: 9 new requirement-proving tests (cases A-H + the positive "both legs" case) added to
`tests/test_quant_strategy.py`; 9 pre-existing calls updated for the new signature; 1 pre-existing
`evaluate_signals`-based assertion updated to its corrected expected value (2→1). Result: **75 passed, 0
failed** in that file. `tests/test_backtest_research_telemetry.py`'s fixture needed strengthening (its
volume never cleared the production threshold, so after the fix no candidate in it could reach
`confluence_score_min` at all) — its test-local `volume_surge_ratio_threshold` was lowered to match what the
fixture's own data actually produces; **12 passed, 0 failed**. One **pre-existing, unrelated** failure
identified via `git stash` bisection (fails identically with none of this task's changes applied):
`test_run_historical_regimes.py::test_real_end_to_end_run_against_the_sample_trade_dataset` — its sole
candidate is BEARISH, which can never open a trade under LONG_ONLY regardless of confluence; not fixed here,
flagged as out of scope. Full repository suite result: see Task 49 artifacts' `test_results.txt`.

**Before/after candidate impact**: reconstructed from Task 46's saved `signal_log` (6,506 candidates), BEFORE
state reconciled exactly to Task 47/48's canonical counts. Closed-form AFTER derivation (proven identity:
`confluence_score_after = confluence_score_before - 1` for MACD family, unchanged for RSI/MA) validated
directly against the raw data. Confluence pass count: 844→16 overall; bullish 403→12 (12.53%→0.37%); bearish
441→4 (13.41%→0.12%). MACD family: bullish pass 391→0, bearish pass 438→1.

**RSI/MA no-drift proof**: `confluence_score_before == confluence_score_after` for all 263 RSI/MA candidates
— proven exactly, not sampled.

**Bullish attrition after correction**: LOW_CONFLUENCE remains dominant and becomes MORE dominant —
87.47%→99.63% (all-failure basis) — the expected, correct consequence of removing self-credit from the
family supplying ~95% of raw triggers. No gate tuned in response.

**Unresolved Task 48 five status**: all 5 (AMD ×4, STX ×1) drop from `confluence_score=2` to `1` and are no
longer strategy-gate-clean under the corrected rule. This explains their FUTURE non-publication but does
NOT retroactively explain Task 48's original fidelity gap (measured under the OLD, pre-fix formula, where
they genuinely scored 2) — `INSUFFICIENT_STATE_EVIDENCE` preserved for that original question.

**Whether Task 50 replay is justified**: **Yes.** The corrected population differs materially (bullish clean
24→0, bearish clean 206→2 on this exact historical sample); only a stateless-gate proxy has been measured,
never the actual stateful engine under the corrected rule; replay would now also be cheap given how sparse
the clean population is.

**Final decision**: `MACD_SELF_CREDIT_CORRECTED_AND_VALIDATED`.

**No other strategy changes**: confirmed — RSI confluence semantics, MA logic, `confluence_score_min`,
volatility regime, trend gate, HTF logic, session/blackout, cooldown/throttle, R:R, stop/target all
untouched. No P&L computed. No historical expansion. Task 22 not inspected. No capital used.

**Next recommended action (not started)**: Task 50 — Bounded Corrected-Confluence Engine Replay: re-run the
same Task 46 experimental population (35 symbols, 3 windows) through the actual backtest engine with this
fix applied, measuring real publication/lifecycle behavior under the corrected confluence rule.

**State**: Task 48 checkpoint committed and pushed (`ed63a52`). This Task 49 ledger entry, code change
(`talonx_quant/strategy.py`), tests, and all `results/task49_macd_self_credit_fix/` artifacts — **not
committed, not pushed**, per instruction. PR #10 remains draft.

## Task 50 — Bounded Corrected-Confluence Engine Replay (2026-08-22)

**Objective**: replay Task 49's corrected confluence rule through the actual backtest engine on the exact
Task 46 population, to measure real gate funnel/publication/lifecycle behavior (not a stateless proxy)
before deciding whether the confluence architecture needs redesign.

**Task 49 checkpoint**: committed and pushed as `83aee8b` before Task 50 began. PR #10 confirmed draft/open.

**Exact Task 46 population reuse**: `quant_config_hash=1eb58828ad69` and `backtest_config_hash=7096a993d034`
match Task 46's experimental run exactly; `strategy_version=efd8558ce2a0` intentionally differs (Task 49's
fix is active). Same 35-symbol universe, same 3 frozen windows, same `data/historical_1m/
task46_validation_windows/` directory — no redownload, no substitution, no extension. Data integrity:
105/105 CSVs present, none modified since Task 46 (mtime-verified).

**Pre-run prediction** (recorded before viewing outcomes): LOW_CONFLUENCE expected to dominate; very few
published signals expected; zero/few bullish executable entries expected; no profitability claim.

**Corrected engine funnel**: 309,838 bars (exact match to Task 46), 63.5 min runtime (vs. Task 46's 62.6 min
for the identical pass — no performance regression). Raw candidates generated: 6,506 (exact match to Task
46-49's canonical population). **0 signals published, 0 trades executed** — across all windows, all
symbols, both directions. `LOW_VOLATILITY_REGIME` 150,877 (bar-level, matches Task 46 exactly),
`LOW_CONFLUENCE` 4,861 first-failure (74.7% of signal-level rejections), `US_MARKET_SESSION_CLOSED` 1,265,
`CLOSING_BLACKOUT` 201, `OPENING_BLACKOUT` 160, `LOW_RISK_REWARD` 5, `HTF_DATA_UNAVAILABLE` 3,
`PREMARKET_LIQUIDITY` 2, `TREND_GATE`/`COOLDOWN`/`THROTTLE`/`LOSS_LOCKOUT` all 0 (nothing ever survives far
enough to reach them).

**Task 49 proxy reconciliation**: exact match on every dimension. `confluence_score` distribution
(0=5,432, 1=1,058, 2=16) matches Task 49's closed-form prediction of 16 exactly. Family × direction
confluence-pass counts match the proxy in every cell (bullish RSI 12/MACD 0/MA 0, bearish RSI 3/MACD 1/MA
0). All 16 confluence-qualifying candidates individually traced to their exact real terminal rejection (6
CLOSING_BLACKOUT, 5 LOW_RISK_REWARD, 3 HTF_DATA_UNAVAILABLE, 2 PREMARKET_LIQUIDITY) — zero unexplained. One
apparent discrepancy during reconciliation (a candidate expected to fail R:R that the engine didn't count
there) was traced to its true cause (closing-blackout eliminates it first in the real gate order) and
documented, not hidden.

**Publication/execution counts**: 0 published (0 bullish, 0 bearish-flat), 0 trades — vs. Task 46's pre-fix
139 published (0 bullish) and Task 46 CURRENT_1M's 7 published (0 bullish). Product-frequency comparison:
trades/week, entry days, symbols-with-trades all 0 across all three configurations on this sample.

**Economics**: `ECONOMICS_NOT_MEASURABLE` — 0 trades at every cost level, no figure fabricated.

**Dominant blocker assessment**: `CONFLUENCE_ARCHITECTURE_STRUCTURALLY_OVERSELECTIVE`. Both required
criteria met: (1) essentially no executable opportunity flow — 0 published/trades, and all 16 confluence
survivors eliminated downstream too; (2) LOW_CONFLUENCE dominance is broad (12 distinct tickers, all 3
windows), not one isolated event. Mechanism: MACD (96% of raw triggers) now needs RSI-extreme AND volume
simultaneously (previously either sufficed via self-credit); RSI/MA have too small a raw population to
compensate.

**Correctness invariants**: LONG_ONLY, no-bearish-entry, no-lookahead, structural-stop/R:R/target logic,
and the experimental volatility gate all verified unaffected (trivially, given 0 trades, and via a 147-test
focused regression pass, 0 failures). CURRENT_1M/Monday path not exercised this run (exactly one
experimental pass, per instruction) but its own regression-equivalence test passed.

**MACD fix status**: NOT reverted. Task 47 proved the self-credit removal was a genuine requirement fix;
this task's conclusion is about the broader confirmation-contract design, not a reason to restore invalid
self-confirmation.

**Final decision**: `CONFLUENCE_ARCHITECTURE_REDESIGN_REQUIRED`.

**No tuning**: confirmed — no confluence threshold, confirmation-leg, RSI/MA logic, volatility/trend/HTF/
session/cooldown/R:R/stop/target change, window/symbol expansion, or parameter sweep. Task 22 not
inspected. No capital used.

**Next recommended action (not started)**: Task 51 — Independent Confirmation Contract Redesign
(DESIGN ONLY): separately define valid independent confirmation for RSI-triggered, MACD-triggered, and
MA-triggered candidates, informed by this task's evidence.

**State**: Task 49 checkpoint committed and pushed (`83aee8b`). This Task 50 ledger entry and all
`results/task50_corrected_confluence_replay/` artifacts — **not committed, not pushed**, per instruction.
PR #10 remains draft.

## Task 51 — Family-Aware Independent Confirmation Contract + Monday Candidate Plumbing (2026-08-22)

**Objective**: implement the owner's contract literally (TRIGGER + AT LEAST ONE independent,
directionally-supportive confirmation) for RSI/MACD/MA as one coherent, contract-selectable design;
prepare Monday shadow-comparison plumbing without touching the frozen baseline. Requirement alignment,
not tuning.

**Task 50 checkpoint**: committed and pushed as `671bdc7` before Task 51 began. PR #10 confirmed draft/open.

**Direct code-review findings** (re-verified against live code): post-Task-49 a MACD candidate needed RSI+
volume BOTH (2 confirmations, not 1); MA could draw wrong-direction MACD credit (direction-agnostic bug);
RSI double-required-then-recredited volume; RSI's own state was already structurally self-exclusive
(Task 28/33, unaffected).

**Final family-aware contract**: `talonx_quant.config.ConfluenceContract` (`LEGACY` default / research-only
`INDEPENDENT_CONFIRMATION_EXPERIMENTAL`, fail-closed on unknown values, `QuantScanner` fails fast on
non-LEGACY exactly like `volatility_gate_mode`). One authoritative function,
`strategy.evaluate_independent_confirmations`, reused unchanged by `talonx_backtest.BacktestEngine`. MACD:
own leg excluded, valid confirmations RSI or volume. MA: no own leg to exclude, valid confirmations
same-direction MACD/RSI/volume. RSI: own leg excluded, valid confirmations volume or same-direction MACD.
Eligibility `confirmation_count >= 1` via a new shared `consumer._confluence_eligible` helper — no
threshold sweep, LEGACY's `confluence_score_min` untouched.

**RSI trigger/volume separation**: `_check_rsi_volume_setup` now contract-branches — LEGACY keeps volume
as a hard trigger prerequisite (byte-for-byte unchanged), EXPERIMENTAL fires the curl alone with volume
becoming confirmation-only, never double-counted. Legacy `SignalType.RSI_*_VOLUME_SURGE` enum values
retained unchanged for wire compatibility.

**Directional MACD correction**: new `_macd_bullish_crossed_this_bar`/`_macd_bearish_crossed_this_bar`
helpers fix a real, pre-existing bug — concretely demonstrated a bullish MA + coincident bearish MACD cross
scored `1` under LEGACY (wrong) vs `0` under EXPERIMENTAL (correct).

**Confirmation-count semantics**: `confluence_score` redefined to `confirmation_count` under EXPERIMENTAL
(same field, disambiguated by a new `confirmation_contract` field). Five new always-optional `QuantSignal`
fields added (`confirmation_count/macd/rsi/volume/contract`), all `None` under LEGACY.

**Opportunity Score**: audited, unchanged. The existing `/3.0` normalization is correct despite differing
per-family confirmation ceilings (MACD/RSI max 2, MA max 3) — per-family self-normalization would have
introduced exactly the ranking bias the task warned against. No weights touched.

**Schema compatibility**: no breaking wire change — `SignalType` unchanged, five new fields additive/
optional, proven via round-trip serialization AND an old-payload-with-keys-stripped parse test.

**Legacy zero-drift**: proven exactly via `git stash` on a deterministic 260-bar fixture — SHA-256 digest
over the full engine output byte-identical before/after (`ed973a9677ca63a0` both times). Corroborated by
486 passing focused-regression tests (0 changed) and a full-suite delta of exactly +26 (the new test file
alone).

**Task 46 static rescore**: MACD confirmation pass matches Task 49/50 exactly (391 bullish/438 bearish).
**Sanity guard triggered and reported honestly, not tuned away**: RSI confirmation pass showed 100%
(152/152, 93/93) — flagged as a dataset survivorship-bias artifact (the reused Task 46/50 population was
generated under the OLD volume-required trigger, so every RSI candidate already had volume; NOT
representative of a true EXPERIMENTAL raw population). MACD leg also not reconstructable for non-MACD
families from saved telemetry (macd_prev unavailable) — RSI/MA counts are a lower bound. Strategy-gate-clean
proxy (lower bound, caveated): bullish=34, bearish=263 — explicitly NOT to be read as a Task 52 projection.

**Monday A/B capability**: broker safety reconfirmed — no order-placement code exists anywhere in the
repository. Shadow telemetry (this task's `confirmation_*` fields) is sufficient for Monday post-close
comparison. True dual-portfolio execution needs exactly one small change: a `state_namespace` field threaded
into `consumer.py`'s two hardcoded cooldown/loss-lockout Redis key f-strings (signal channels and paper
`db_path` are already independently configurable).

**Tests**: 26 new requirement-proving tests (cases A-Z), 0 failed. 486-test focused regression, 0 failed.
Full suite: 1836 passed, 1 pre-existing unrelated failure (reconfirmed, same root cause as Task 49/50), 1
skipped, 15 xfailed.

**Final decision**: `IMPLEMENTED_WITH_MONDAY_AB_PLUMBING_PENDING`.

**No tuning**: confirmed — no threshold sweep, no volatility/trend/HTF/session/cooldown/R:R/stop/target
change, frozen provisional regime thresholds untouched. Task 22 not inspected. No capital used.

**Next recommended action (not started)**: Task 52 — Bounded Historical A/B Validation + Monday Candidate
Freeze: replay exact Task 46 validation data under both contracts with a FRESH replay (not reused saved
data, since EXPERIMENTAL's RSI trigger now fires on a materially larger raw population), compare baseline
vs candidate publication/trades/economics/costs, and if sane, freeze both configs for Monday plus finalize
the parallel shadow runbook (including the `state_namespace` plumbing).

**State**: Task 50 checkpoint committed and pushed (`671bdc7`). This Task 51 ledger entry, code change
(`talonx_quant/config.py`, `talonx_quant/schemas.py`, `talonx_quant/strategy.py`,
`talonx_quant/consumer.py`, `talonx_backtest/engine.py`), tests, and all
`results/task51_independent_confirmation/` artifacts — **not committed, not pushed**, per instruction. PR
#10 remains draft.

## Task 52 — Fresh Historical A/B Validation + Conditional Monday Candidate Freeze (2026-08-22)

**Objective**: clean historical A/B comparison of frozen BASELINE (`CURRENT_1M`+`LEGACY`) vs. CANDIDATE
(`MULTITIMEFRAME_EXPERIMENTAL`+`INDEPENDENT_CONFIRMATION_EXPERIMENTAL`) from a FRESH engine replay (not
reused saved candidate logs), reaching a documented GO/NO-GO decision.

**Task 51 checkpoint**: committed and pushed as `393f533` before Task 52 began. PR #10 confirmed draft/open.

**Exact baseline/candidate contracts**: baseline `quant_config_hash=78b656491f2a`, candidate
`fdf4922d0728` — only `volatility_gate_mode`/`confluence_contract` differ. Both ran against byte-identical
raw market data (dataset hashes match Task 46/50's own recorded values exactly), same 35-symbol universe,
same 3 windows (X_early/Y_middle/Z_late, 15 trading days), same engine commit, same execution assumptions.

**Data/window selection rule**: reused Task 46's raw market data and mechanically-selected, out-of-
development windows unchanged — no redownload, no window replacement, no cherry-picking. Data quality:
105/105 CSVs unmodified since Task 50, zero critical corruption.

**Runtime**: estimated 120-130 min (from Task 46/50's measured rate), actual 121.9 min (58.8 baseline +
63.1 candidate) — no mechanical reduction needed.

**Fresh replay confirmed**: candidate raw population 8,607 (fresh) vs. 6,506 (old, saved) — genuinely larger,
not reused, exactly as Task 51's RSI trigger change predicted.

**Full A/B funnel**: baseline 1,295 raw → 1 published → 0 trades. Candidate 8,607 raw → **203 published** →
0 trades. `LOW_VOLATILITY_REGIME` (150,877, bar-level) matches Task 46/50 exactly. `TREND_GATE` fired 0
times in the candidate run (never reached).

**Confirmation distribution / RSI fresh-population result**: confluence/confirmation pass rate is now
DIRECTION-SYMMETRIC and healthy — bullish 618/4,475 (13.8%), bearish 576/4,132 (13.9%). MACD confluence-
eligible counts match Task 51's static prediction exactly (391 bullish/438 bearish) — cross-validated.
**RSI's TRUE fresh pass rate directly resolves Task 51's flagged survivorship-bias gap**: 2,346 raw curls
(vs. 245 in the old volume-pre-filtered dataset), true pass rate 16.1% bullish/14.7% bearish — nowhere near
the misleading ~100% the biased static check showed. 1,981/2,346 curls (84.4%) correctly have zero
confirmation and do not publish.

**Frequency**: 0 long entries, 0 trades/week, 0/15 entry days, 0/35 symbols with a trade — in both modes.

**Economics/cost sensitivity/family economics/symbol concentration/window robustness/attribution**: all
`ECONOMICS_NOT_MEASURABLE`/trivially empty — 0 trades in both modes.

**Correctness checks**: GREEN. 163 focused-regression tests, 0 failed. No invariant violated; several
unexercised only because 0 trades occurred (R:R/blackout gates independently confirmed ACTIVE via real,
nonzero rejection counts).

**Candidate GO/NO-GO rationale — the central finding**: confluence/confirmation is NO LONGER the blocker
(symmetric, healthy pass rates, matching Task 51's predictions exactly). The real blocker: **all 618 bullish
confluence-eligible candidates have `trend_component=None`** — the 15m-200-SMA trend gate never once
produced a valid reading in this entire study. Root cause (direct arithmetic): a 5-trading-day window
supplies at most 130 regular-session 15-min bars; the trend gate needs 200 — structurally guaranteed never
to warm up within one window, for any symbol, under EITHER contract. This is a **pre-existing methodology
limitation of the window width first introduced in Task 46** (mechanical runtime-budget reduction from 10
to 5 trading days), invisible until now because every prior bullish confluence-survivor population (0-24)
was too small to expose it. Not a confluence-contract defect.

**A/B namespace/plumbing**: NOT implemented — gated on the candidate passing the historical credibility
gate, which it did not (criterion B, "nonzero executable long opportunity flow," fails: 0 bullish trades in
both modes).

**Monday frozen SHA/config fingerprints**: NO freeze performed. Monday continues on the BASELINE only
(`CURRENT_1M`+`LEGACY`), already structurally enforced (`QuantScanner` fails fast on any other config).
Reference fingerprints recorded for continuity only, not as a freeze: see `monday_freeze_manifest.json`.

**Monday execution-isolation level**: N/A (candidate not deployed). Had the gate passed, the honest
classification would have been `PARALLEL_DECISION_SHADOW_READY` at best (signal channels/paper `db_path`
already independently configurable; cooldown/loss-lockout key collision remains unresolved).

**Unresolved risks**: the trend-gate/window-warmup limitation affects ALL prior Task 46-52 bullish-trade
measurements identically — every "zero bullish trades" finding since Task 46 should be read with this
caveat in mind, not just Task 52's.

**Final decision**: `VALIDATION_BLOCKED`.

**No tuning**: confirmed — no threshold sweep, no confluence tuning beyond Task 51's frozen contract, no
volatility tuning, no symbol cherry-picking, no window replacement after outcomes, no stop/target/R:R
changes. Task 22 not inspected. No capital used.

**Next recommended action (not started)**: widen the validation windows, or add an HTF lookback preseed to
`talonx_backtest.BacktestEngine` (mirroring live's own historical preseed mechanism), then re-run this exact
same A/B comparison.

**State**: Task 51 checkpoint committed and pushed (`393f533`). This Task 52 ledger entry, the one additive
telemetry-field change (`talonx_backtest/engine.py`'s `candidate_telemetry` dict), and all
`results/task52_historical_ab_freeze/` artifacts — **not committed, not pushed**, per instruction. PR #10
remains draft.

## Task 53 — Causal Backtest Pre-Roll Warmup + Task 52 A/B Revalidation + Monday Candidate Decision (2026-08-23)

**Objective**: add a causal pre-roll/warmup mechanism to `BacktestEngine`, prove continuous-history vs.
pre-roll+evaluation parity, re-run Task 52's exact A/B windows with real HTF/regime warmup, and reach the
actual Monday candidate GO/NO-GO decision Task 52's window-width limitation had blocked.

**Task 52 checkpoint**: committed and pushed as `7c2e4a3` before Task 53 began. PR #10 confirmed draft/open.

> **PREVIOUS** (Task 52): `VALIDATION_BLOCKED` — a 5-trading-day evaluation window, with no preceding
> warmup, structurally could never accumulate the 200 completed 15-minute bars the trend gate needs
> (max ~130 available). All 618 bullish confluence-eligible candidates had zero valid trend readings. Not
> a confluence-contract defect — a validation-methodology limitation.
>
> **NEW EVIDENCE** (Task 53): implemented `BacktestEngine.run(df, warmup_df=...)` — a causal pre-roll that
> reconstructs 1m/15m/60m market-state buffers from 10 preceding trading days, state-only (no candidates/
> rejections/trades/cooldown during warmup), proven to reconstruct EXACTLY the same state a continuous run
> would produce (buffer/indicator/HTF-SMA/pivot/regime equality, not approximate). Pre-run readiness gate:
> 35/35 symbols HTF/regime/1m-ready in all 3 windows before the expensive replay was launched. Re-ran
> Task 52's EXACT windows/symbols/contracts, only adding preceding causal warmup rows.
>
> **UPDATED CONCLUSION**: `HTF_DATA_UNAVAILABLE` fell from 188 (Task 52) to **0** (Task 53);
> `TREND_GATE` went from never-reached (0) to a real, active, discriminating gate (143 rejections,
> 206/466 valid regular-session bullish readings passing). **The candidate now executes 34 real long
> trades** (baseline: still 0) — Task 52's diagnosis is fully confirmed correct, and the underlying question
> ("can the corrected confirmation contract produce executable opportunities at all?") is now answered:
> **yes**. However, economics on this n=34 sample are NOT clean: 0bps expectancy +0.012R (noise-level), 5bps
> expectancy −0.33R (clearly negative at realistic cost), 91% of positive R from the top 3 trades, only 1 of
> 3 windows net positive and that window's result rests on one outlier trade. Final decision:
> `CANDIDATE_FREQUENCY_RECOVERED_ECONOMICS_UNCLEAR` — not a clean GO, not a rejection either.
>
> **REASON**: the Task 52 conclusion (`VALIDATION_BLOCKED`) remains permanently correct as a description of
> THAT run's limitation — it is not overwritten, only superseded by Task 53's methodology fix and its own,
> separate economic finding on the corrected population.

**Pre-roll implementation**: `_feed_market_state` (factored out of pre-existing buffer-feeding code, logic
unchanged) + `_warmup_symbol_bar` (state-only, separate `warmup_bars_processed` counter) + causality
enforcement (`ValueError` if warmup isn't strictly earlier than evaluation). Warmup requirement derived from
actual dependencies (200 completed 15m bars ⇒ ~7.7 trading days floor; chose 10 trading days for boundary
margin, fixed before any coverage was inspected). Backward compatible: `run(df)` with no `warmup_df` is
byte-for-byte unchanged (full regression suite passing with zero test updates needed beyond the new file).

**Continuous vs. split parity — the central proof**: EXACT equality (not approximate) across 1m buffer,
`IndicatorSnapshot`, 15m HTF buffer, `htf_sma_200`, daily pivots, 60m buffer, `VolatilityRegimeSnapshot`,
`evaluate_regime` result, between a continuous run and a warmup+evaluation split run at the same cutoff.
Zero evaluation contamination (bars_processed excludes warmup exactly; zero signals/rejections/trades before
the evaluation boundary; no cooldown/loss-lockout/pending state carries across).

**Pre-run readiness gate**: 10 preceding trading days of raw market data (75/75 fresh Alpaca downloads for
25 non-original symbols, sliced from existing full-year local data for the other 10) — 35/35 symbols reached
HTF-SMA/60m-regime/1m-indicator readiness in all 3 windows. Gate passed; the ~2.5-hour A/B replay was
launched only after this confirmation.

**A/B headline**: baseline 1,418 raw/1 published/**0 trades**. Candidate 10,141 raw/302 published/**34
trades** (≈11.3 trades/week, 12/15 entry days, 16/35 symbols). Runtime 147.4 min total (68.4 baseline + 79.0
candidate), within the 2-3h target including warmup overhead (warmup itself is cheap — state-only, no
`compute_indicators` call).

**Task 52 diagnosis confirmed**: bullish confluence-eligible 618→702 (comparable); valid trend readings
0→466; `HTF_DATA_UNAVAILABLE` 188→0; `TREND_GATE` 0→143 (now a genuinely functioning gate).

**New dominant bottleneck**: `LOW_CONFLUENCE` (`CONFIRMATION`) — 6,315 rejections, unchanged in kind from
every prior task, over 10x the next-largest gate. Not tuned in response.

**Economics/cost sensitivity**: 0bps expectancy +0.012R/trade (PF 1.02, noise-level); 5bps expectancy
−0.33R/trade (PF 0.66, clearly negative); 10bps expectancy −0.68R/trade (PF 0.47). RSI-family trades net
positive (+6.21R); MACD-family trades net negative (−5.78R); MA family 0 trades (too small a raw population,
unchanged). Symbol concentration: top-1 trade-count share 14.7%, but top-1 POSITIVE-R share 57.1%, top-3
91.1%. Window robustness: X_early −9.74R, Y_middle −0.07R, Z_late +10.23R (dominated by one +13.44R ADI
trade — remove it and all 3 windows are flat-to-negative).

**Correctness**: GREEN. All 34 trades BULLISH-only (LONG_ONLY preserved), valid structural/ATR-fallback
geometry, no R:R below threshold. 9 new pre-roll tests + 197-test focused regression + full suite (1845
passed, 1 pre-existing unrelated failure reconfirmed, 1 skipped, 15 xfailed) all green.

**Live/backtest warmup parity**: live already has 3 causal preseed mechanisms (1m/15m/60m); backtest
pre-roll now uses the same buffer/aggregator architecture. One honest gap: live's default 15m preseed
lookback (~1 month) is roughly double Task 53's 10-trading-day choice — both clear the mathematical
readiness floor (35/35 empirically confirmed), so this is a safety-margin difference, not a readiness
failure. No correction made.

**Candidate GO/NO-GO rationale**: 2 of 8 Monday GO criteria explicitly fail (5bps economics turn negative;
extreme concentration/window dependence). Not a clean GO. Not a rejection either — n=34 is too small to
confidently declare the strategy good or bad, and 0bps is genuinely positive.

**Final decision**: `CANDIDATE_FREQUENCY_RECOVERED_ECONOMICS_UNCLEAR`.

**A/B state-isolation plumbing / Monday freeze**: NOT implemented, NOT performed — correctly gated on a
clean GO, which was not reached. Precisely scoped for a future task if the economics gate later clears
(one `state_namespace` field + 4 Redis-key call sites in `consumer.py`).

**No tuning**: confirmed — no confluence/volatility/trend-threshold/R:R/stop-target change; warmup window
width and evaluation windows/symbols fixed before any outcome was viewed. Task 22 not inspected. No capital
used.

**Next recommended action (not started)**: owner decision — either (a) accept decision-shadow risk despite
unclear economics and implement the scoped `state_namespace` plumbing, or (b) gather a larger validation
sample before deciding, still with zero tuning.

**State**: Task 52 checkpoint committed and pushed (`7c2e4a3`). This Task 53 ledger entry, the pre-roll
implementation (`talonx_backtest/engine.py`), new test file (`tests/test_backtest_preroll.py`), doc updates
(`docs/backtesting.md`), and all `results/task53_preroll_ab_validation/` artifacts — **not committed, not
pushed**, per instruction. PR #10 remains draft.

## Task 54 — Overnight Extended Candidate Validation (2026-08-23)

**Objective**: run one larger, frozen, candidate-only historical validation (production-scale, ~60
evaluation trading days across 3 windows) to determine whether Task 53's weak economics (n=34) were
small-sample noise or evidence of no repeatable edge.

**Task 53 checkpoint**: committed and pushed as `a1d0097` before Task 54 began. Clean tracked-tree status
confirmed. Candidate config hash `fdf4922d0728`/strategy fingerprint `2ae6216bca70` — identical to Task 53's
own candidate, confirming the exact same frozen contract.

> **PREVIOUS** (Task 53): `CANDIDATE_FREQUENCY_RECOVERED_ECONOMICS_UNCLEAR` — n=34 trades, 0bps barely
> positive (expectancy +0.012R, noise-level), 5bps clearly negative (−0.33R), 91% of positive R from the top
> 3 trades, only 1/3 windows profitable and that window rested on a single outlier trade.
>
> **NEW EVIDENCE** (Task 54): a fresh, frozen, candidate-only replay over 3 mechanically-selected 20-
> trading-day windows (~60 eval days total, 10-day pre-roll each, same warmup mechanism, 35/35 symbols
> ready before the ~4.6h replay was launched) produced **89 executed trades** — 2.6x Task 53's sample. 0bps:
> expectancy +0.237R, PF 1.37 (genuinely positive point estimate, but bootstrap 95% CI is [−0.19, +0.71] —
> includes zero). 5bps: total R −25.99, expectancy −0.29R, PF 0.73 (still clearly negative in aggregate).
> Outlier sensitivity: removing the top 3 winning trades flips 0bps total R negative. Trade concentration
> improved dramatically (top-3 positive-R share 91.1% → **32.3%**). Window profitability improved (0/3 → 2/3
> windows profitable even at 5bps — only one window, W1, remains a clear net drag at every cost level). A
> genuine, consistent family split persists: RSI trades (39, PF 2.19, positive even at 5bps: +15.30) vs.
> MACD trades (50, PF 0.78, sharply negative at 5bps: −41.29) — the same direction as Task 53's smaller
> sample, now confirmed at scale. Only 1/89 trades (1.1%) exited via TARGET — positive outcomes are
> dominated by END_OF_SESSION/SIGNAL_EXIT, not disciplined target hits.
>
> **UPDATED CONCLUSION**: the larger sample **did not resolve** the core cost-robustness question
> (aggregate 5bps remains solidly negative; bootstrap CI still includes zero) but **substantially de-risked**
> the specific small-sample/outlier-concentration concern Task 53 flagged. Economic classification:
> `EDGE_WEAK_AND_COST_SENSITIVE` (gross near-flat/positive, realistic costs destroy it). Final decision:
> `MONDAY_DECISION_SHADOW_ONLY` — not a clean GO (correctness is GREEN but economics remain unproven), not a
> rejection either (there is a real, larger-than-noise signal, especially in the RSI family, worth
> continued measurement-only observation).
>
> **REASON**: the Task 53 conclusion is not overwritten — it accurately describes what a 34-trade sample
> showed. Task 54 answers the specific question Task 53 raised (is this noise or a real pattern?) with a
> nuanced result: some of Task 53's most alarming specifics (91% concentration, 0/3 windows at 5bps) were
> indeed small-sample artifacts, but the fundamental cost-sensitivity finding was not — it persists and
> strengthens with more data.

**Dataset design**: production-scale 35-symbol universe, 3 windows (W1: eval 2025-09-29→10-24, W2: eval
2025-11-26→12-24, W3: eval 2026-04-21→05-18), each with 10 trading days of causal pre-roll (Task 53's proven
mechanism). Selection rule fixed before any outcome was viewed: 15%/50%/85% marks on the real ET-localized
251-trading-day calendar, searched outward for the nearest 30-day block avoiding Task 37/38/41's development
windows and Task 46/52/53's evaluation slices. **A genuine calendar bug (UTC-date instead of ET-localized
trading-day extraction, spuriously including weekend dates) was found by a sanity check and fixed before any
download** — the two downloads made under the buggy dates were discarded and redone under the corrected
dates; no buggy data reached the replay.

**Data quality**: 75/75 fresh Alpaca downloads (25 symbols × 3 windows) all `FULL` status; 10 original
symbols sliced from existing full-year local data. 35/35 symbols with complete coverage in all 3 windows.

**Runtime**: estimated ~160 min from Task 53's throughput; actual 278.3 min (~4.6h), within the ≤8h budget,
no mechanical reduction needed.

**Readiness gate**: 35/35 symbols HTF-SMA/60m-regime/1m-indicator ready at the first evaluation bar in all 3
windows, confirmed via a cheap state-only preload before the expensive replay was launched.

**Funnel/dominant bottleneck**: unchanged in kind — `LOW_VOLATILITY_REGIME` and `LOW_CONFLUENCE` remain the
two largest gates by far; `HTF_DATA_UNAVAILABLE` stayed at 0 (pre-roll continues working correctly at
production scale); `TREND_GATE` 205 real rejections.

**Correctness**: GREEN. 100% of 89 trades BULLISH-only, 0 invalid geometry, 0 R:R below threshold, 0
warmup-originated economics, no cross-window state leakage (fresh `BacktestEngine()` per window). 95-test
focused regression, 0 failed; full suite not re-run (no code changed since Task 53's 1845-passed baseline).

**Monday A/B plumbing / freeze**: NOT implemented, NOT performed — the "materially strengthens" bar for the
conditional plumbing work was not met (economics remain unresolved at the aggregate level).

**Final decision**: `MONDAY_DECISION_SHADOW_ONLY`. Economic classification: `EDGE_WEAK_AND_COST_SENSITIVE`.

**No tuning**: confirmed — no threshold/parameter/family/symbol change; window selection fixed before any
outcome was viewed. Task 22 not inspected. No capital used.

**Next recommended action (not started)**: continue decision-shadow observation to accumulate live evidence,
particularly on the persistent RSI-positive/MACD-negative family split (confirmed in both Task 53 and Task
54) — consider a future bounded diagnostic isolating family-level economics before any broader claim.

**State**: Task 53 checkpoint committed and pushed (`a1d0097`). This Task 54 ledger entry and all
`results/task54_extended_candidate_validation/` artifacts — **not committed, not pushed**, per instruction.
PR #10 remains draft.

## Task 55 — RSI vs MACD Family Economics Diagnostic (2026-08-23)

**Objective**: determine whether the RSI-positive/MACD-negative family split observed in Tasks 53 and 54
survives fixed composition controls, without changing the strategy or treating a retrospective diagnostic
as causal evidence.

> **PREVIOUS** (Task 54): economic classification `EDGE_WEAK_AND_COST_SENSITIVE`; deployment decision
> `MONDAY_DECISION_SHADOW_ONLY`. Task 54 observed an RSI-positive/MACD-negative family split, but authorized
> no family enable/disable action.
>
> **NEW EVIDENCE** (Task 55): a read-only diagnostic over the committed Task 53 and Task 54 trades, with no
> new backtest, download, tuning, or strategy change. The combined sample contains 123 trades: 56 RSI and
> 67 MACD. RSI produced +34.779R gross, +0.621R/trade gross expectancy, PF 1.94, and +15.846R at 5bps.
> MACD produced −13.268R gross, −0.198R/trade gross expectancy, PF 0.69, and −53.145R at 5bps. RSI exceeded
> MACD in 4/6 windows gross and 5/6 windows at 5bps.
>
> **UPDATED CONCLUSION**: `FAMILY_EFFECT_TENTATIVE`.
>
> **REASON**: the repeated family direction survives multiple prespecified composition controls, but does
> not establish causality or a robust production-grade RSI edge. RSI remains winner-tail sensitive and
> strict matched evidence is too thin.

**Composition controls**: the 17-symbol common-support subset retains 53/56 RSI trades (94.6%) and 62/67
MACD trades (92.5%) and preserves the split: RSI +37.779R gross and +19.739R at 5bps versus MACD −12.110R
gross and −51.353R at 5bps. The dominant mid-session bucket also preserves the split: RSI +37.845R gross
and +21.467R at 5bps versus MACD −19.562R gross and −54.575R at 5bps. Stop rate does not explain RSI's
advantage (RSI 37/56, 66.1%; MACD 42/67, 62.7%), and holding duration alone does not explain it: both
families lose in the ≤15-minute and 15–60-minute buckets and gain in the >60-minute bucket, while RSI's
advantage is concentrated in larger surviving/non-stop winners.

**Outlier and loss-tail sensitivity**: removing RSI's top 3 gross winners leaves only +3.070R gross and
turns the 5bps total negative (−13.738R); removing its top 5 turns gross negative (−8.866R). MACD remains
gross negative after removing its worst 1, 3, or 5 losers (−12.268R, −10.268R, and −8.268R respectively),
so its weakness is not driven by a small extreme gross-loss tail.

**Cost geometry**: MACD bears a higher mean cost in R at 5bps (0.595R/trade versus RSI 0.338R/trade),
consistent with tighter stop-risk geometry (median stop risk 0.331% of entry versus RSI 0.431%). This
amplifies MACD's net weakness but does not create it: MACD is already negative gross.

**Matched evidence**: unweighted common strata are mixed (RSI mean exceeds MACD in 9/20 eligible strata),
while trade-weighted common-support economics materially favor RSI (RSI 24 trades, +25.671R gross and
+18.184R at 5bps; MACD 36 trades, −11.377R gross and −38.299R at 5bps). Loose nearest-time matching also
favors RSI, but its temporal gaps are too large for a causal claim. Strict same-day matching yields only
3 pairs and is classified `MATCHED_SAMPLE_TOO_THIN`.

**Final decision**: `FAMILY_EFFECT_TENTATIVE`. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`. No family
enable/disable action or production behavior change is authorized.

**Limitations**: retrospective reuse of Task 53/54 outcomes; only 123 trades; RSI upper-tail dependence;
cross-trade dependence is not modeled by the descriptive trade-level bootstrap; strict temporal matching
is underpowered. The result supports an independent, outcome-blind holdout replication, not strategy
promotion.

**Evidence**: `results/task55_family_economics_diagnostic/` — `task55_summary.md`, `task55_summary.json`,
`task55_conclusion.md`, `family_economics.csv`, `common_symbol_economics.csv`,
`family_outlier_sensitivity.csv`, `matched_strata.csv`, `matched_common_support_economics.csv`, and the
supporting time/exit/holding/cost/pairing tables.

**Next recommended action (not started)**: Task 56 — Independent Family Holdout Validation, using frozen,
non-overlapping historical windows and the exact Task 54 candidate without tuning.

## Task 56 — Independent Family Holdout Validation (2026-08-23)

**Objective**: test whether Task 55's tentative RSI-positive/MACD-negative family direction reproduces on
the three outcome-blind, independent H1/H2/H3 evaluation windows frozen at commit `8de8d49`, using the exact
Task 54 candidate and no tuning.

> **PREVIOUS** (Task 55): `FAMILY_EFFECT_TENTATIVE` — the RSI-positive/MACD-negative direction repeated
> across Tasks 53/54 and survived multiple retrospective composition controls, but remained non-causal,
> winner-tail sensitive, and insufficient to authorize a family enable/disable or production action.
>
> **NEW EVIDENCE** (Task 56): before any expensive replay, the frozen candidate fingerprints reproduced
> exactly (strategy `2ae6216bca70`, quant config `fdf4922d0728`, backtest config `0c7dd13d75c4`). The first
> declared download was attempted for exactly the 25 additional symbols and H1 package (2025-12-11 through
> 2026-01-26). Alpaca HTTPS requests were forced through an unreachable sandbox proxy (`127.0.0.1:9`), and
> the active execution policy rejected the required network-elevated retry. Zero symbol files and no download
> summary were written. Local inventory reconfirmed full-year coverage for the original 10 and 35/35
> state-only warmup feasibility, but the additional 25 still lacked complete independent evaluation data.
> Per the frozen protocol, no reduced universe, provider substitution, replacement dates, partial replay, or
> fabricated empty economics was permitted. The mandatory dataset-coverage gate failed; data-quality and
> complete-package readiness checks were not runnable; the expensive candidate-only replay was not started.
>
> **UPDATED CONCLUSION**: `VALIDATION_BLOCKED`.
>
> **REASON**: complete frozen 35-symbol holdout data could not be acquired in this execution environment.
> Without passing the mandatory coverage/readiness gates, the Task 55 family direction cannot be independently
> tested. This infrastructure/data-access block is not evidence for or against RSI or MACD economics.

**Diagnostics**: all predeclared RSI/MACD economics, window consistency, common-symbol support, symbol
breadth/concentration, time-of-day, exit/holding, winner/loser sensitivity, cost-in-R/stop-risk geometry, and
MA-activity diagnostics are explicitly `NOT_RUN_VALIDATION_BLOCKED`. The frozen interpretability floor was
applied but is not evaluable because no replay/trade sample exists.

**Correctness/scope**: frozen dates and strategy/config parameters were unchanged; protected strategy files
were not modified; no tuning, family enable/disable action, capital use, PR merge, or deployment change.

**Final decision**: `VALIDATION_BLOCKED`. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`.

**Evidence**: `results/task56_independent_family_holdout/validation_blocker.json`, `task56_summary.json`,
`task56_summary.md`, `task56_conclusion.md`, plus the committed protocol-freeze artifacts.

**Next step**: rerun the exact frozen download gate only in an execution environment that can reach Alpaca;
do not change dates, universe, provider, candidate, thresholds, or classifications in response to this block.

## Task 56 — Independent Family Holdout Validation, resumed completion (2026-08-23)

This entry preserves the earlier Task 56 `VALIDATION_BLOCKED` attempt above as infrastructure history. It
resumes the same protocol frozen at `8de8d49`; it does not replace, redefine, or reinterpret that attempt.

> **PREVIOUS**: Task 55 found a tentative RSI-positive/MACD-negative comparative direction. The first Task
> 56 execution attempt was `VALIDATION_BLOCKED` solely because its environment could not reach Alpaca; no
> holdout economics existed and that block was explicitly neither positive nor negative family evidence.
>
> **NEW EVIDENCE**: Alpaca connectivity became available and exactly the missing 25 symbols x three frozen
> windows (75 symbol-window packages) were acquired with `FULL` provider status. The mandatory pre-replay
> gate passed in every window: 35/35 symbols, the exact 10 warmup and 20 evaluation trading dates, complete
> per-symbol coverage, 35/35 first-evaluation-bar readiness, and zero critical NaN/Inf/OHLC/timestamp,
> duplicate, out-of-order, or future-data corruption. Frozen fingerprints reproduced exactly: strategy
> `2ae6216bca70`, quant config `fdf4922d0728`, backtest config `0c7dd13d75c4`. The unchanged candidate-only
> replay processed 1,231,191 evaluation bars and produced 105 trades (44 RSI, 61 MACD, zero MA).
>
> RSI: 44 trades, 15 wins/28 losses (one flat), gross +0.723R, +0.016R expectancy, PF 1.033; at 5bps
> -10.544R, -0.240R expectancy, PF 0.650. MACD: 61 trades, 19 wins/42 losses, gross -1.258R, -0.021R
> expectancy, PF 0.966; at 5bps -26.058R, -0.427R expectancy, PF 0.542. RSI exceeded MACD overall at both
> costs and in two of three windows at both costs. The interpretability floor passed (105 combined; 44/61
> by family; both families in all three windows and across 17/22 symbols). However, the direction did not
> survive the frozen common-symbol support control, and RSI's advantage did not survive removal of its top
> three winners. RSI was only marginally positive gross and was negative at 5bps.
>
> **UPDATED CONCLUSION**: `FAMILY_EFFECT_WEAKENED`.
>
> **REASON**: both primary comparative hypotheses repeated and the sample was interpretable, so the result is
> neither too thin nor a material reversal. It does not satisfy the stronger frozen replication definition
> because two required robustness conditions failed. Comparative RSI-vs-MACD ordering is distinct from
> absolute edge: the holdout does not establish cost-robust RSI profitability or production readiness.

**Robustness and diagnostics**: the full frozen family/window/symbol/common-support/time-of-day/exit-path/
holding-duration/winner-loser sensitivity/cost-in-R/stop-risk geometry tables are under
`results/task56_independent_family_holdout/`. Trade-count concentration was not confined to one symbol
(RSI top-1/top-3/top-5 shares 11.4%/29.5%/47.7%; MACD 11.5%/29.5%/42.6%). Median 5bps burden was 0.181R
for RSI and 0.285R for MACD; median stop risk was 0.551% and 0.350%, respectively. MA produced zero trades
naturally.

**Correctness/scope**: all 105 trades were bullish long entries; zero duplicate trade IDs, entry-before-
signal, exit-before-entry, invalid stop/target geometry, or sub-1.5 screening R:R cases. Fresh engine state
was used per holdout window. Frozen protocol files and protected strategy/config sources remained unchanged.
No parameter sweep, family disabling, symbol/cost tuning, replacement window, partial replay, capital use,
or outcome-driven filter occurred.

**Final decision**: `FAMILY_EFFECT_WEAKENED`. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`. No live
family enable/disable action and no capital are authorized.

## Task 57 — Execution Friction vs Trade Geometry Diagnostic (2026-08-23)

> **PREVIOUS**: Task 56 classified the independent holdout family comparison as
> `FAMILY_EFFECT_WEAKENED`. RSI remained slightly positive gross but negative at 5bps; MACD remained
> negative at both costs. Deployment stayed `MONDAY_DECISION_SHADOW_ONLY` with no family or capital action.
>
> **NEW EVIDENCE**: a deterministic, analysis-only diagnostic combined the committed Task 53 (34), Task 54
> (89), and Task 56 (105) trade ledgers while preserving task/window provenance. All 228 trades mapped
> exactly to RSI (100) or MACD (128), with zero duplicate source keys and zero MA trades. The declared
> entry/exit/stop formula reproduced the frozen 5bps totals exactly within floating-point tolerance: Task 53
> -11.310R, Task 54 -25.989R, Task 56 -36.603R; Task 56's stored native equivalent matched to 3.8e-12R.
>
> Combined economics were gross +20.976R (+0.092R/trade, PF 1.150) versus 5bps -73.901R
> (-0.324R/trade, PF 0.659). Mean/median cost burden was 0.416R/0.252R. RSI was gross +0.355R/trade and
> 5bps +0.053R/trade, with median stop risk 0.466% and mean/median cost 0.302R/0.215R. MACD was already
> gross -0.113R/trade and fell to -0.619R/trade at 5bps, with tighter median stop risk 0.338% and higher
> mean/median cost 0.505R/0.296R. RSI exceeded MACD within four of six adequately supported predeclared
> stop-risk buckets, but not the 0.15-0.25% or >=0.75% buckets; the approximate geometry control supports a
> non-universal family difference, not a causal or production claim.
>
> Task 56 RSI weakening was not caused by tighter geometry: median stop risk widened from 0.431% to 0.551%
> and mean cost fell from 0.338R to 0.256R. Win rate was effectively unchanged (33.9% to 34.1%), while
> average winning R collapsed from 3.778R to 1.507R; costs then overwhelmed the near-zero gross expectancy
> (+0.016R). Task 56 MACD improved gross (-0.198R to -0.021R) and cost burden (0.595R to 0.407R) versus
> Tasks 53+54 but remained slightly gross-negative. The top 1/3/5/10 cost-R trades contributed
> 15.7%/19.7%/23.0%/29.4% of total cost drag. Removing the ten highest-cost trades left RSI slightly
> negative at 5bps (-0.032R/trade) and MACD decisively negative (-0.458R/trade), so pathology did not
> dominate the failure.
>
> **UPDATED CONCLUSION**: `BOTH_GROSS_AND_COST_WEAK`.
>
> **REASON**: gross quality is weak in aggregate and MACD is gross-negative even before costs, while the
> observed 5bps burden is large enough to erase the modest combined gross expectancy. Reasonable-risk
> trades (>=0.35% stop risk, a descriptive aggregation of frozen buckets rather than an approved filter)
> produced +0.139R gross expectancy but only +0.009R at 5bps—neither a robust gross edge nor a pure
> geometry-only failure. Extreme trades amplify cost drag but do not explain it alone.

**Break-even description**: combined RSI gross expectancy +0.355R exceeded its mean 5bps burden 0.302R by
only +0.053R; implied zero-mean-net maximum was 11.76 round-trip bps under the observed geometry. Combined
MACD gross expectancy was -0.113R against a 0.505R burden, so no non-negative execution cost can make its
observed mean break even. In Task 56 alone, RSI gross +0.016R was far below its 0.256R burden (implied
0.64 round-trip bps); MACD gross was already negative. These are descriptive calculations, not a lower-cost
assumption or recommendation.

**Scope/validation**: no replay, parameter search, threshold/family/stop/cost/symbol change, production
behavior change, or capital use. All 17 artifacts reproduced byte-identically across two runs. Protected
strategy/config files remained unchanged. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; no ex-post
geometry exclusion is authorized as a filter.

## Task 58 — RSI Winner-Magnitude / Payoff Regime Diagnostic (2026-08-23)

> **PREVIOUS**: Task 57 classified the combined execution-friction/geometry evidence as
> `BOTH_GROSS_AND_COST_WEAK`. It isolated Task 56 RSI's change to winner magnitude: Tasks 53+54 averaged
> 3.778R per winner versus 1.507R in Task 56, while win rate was nearly unchanged and stop/cost geometry
> improved. Deployment remained `MONDAY_DECISION_SHADOW_ONLY` with no strategy or capital action.
>
> **NEW EVIDENCE**: a deterministic, observational diagnostic reproduced all 100 committed RSI trades:
> Task 53 17 trades, +6.205R gross (+0.365R/trade), four winners (23.5%), +0.543R at 5bps; Task 54 39
> trades, +28.573R gross (+0.733R/trade), 15 winners (38.5%), +15.303R at 5bps; Task 56 44 trades,
> +0.723R gross (+0.016R/trade), 15 winners (34.1%), -10.544R at 5bps. There were zero duplicate source
> trades. The prior-to-holdout expectancy change (-0.605R/trade) decomposed into +0.030R from frequency,
> -0.774R from winner size, and +0.139R from smaller losses: winner magnitude was decisive.
>
> Prior 2R+/4R+ rates were 17.9%/10.7% versus Task 56's 11.4%/2.3%. Removing only the three largest
> prior winners reduced prior expectancy from +0.621R to +0.058R, close to Task 56's +0.016R; removing
> five made it negative. W3 and Z_late supplied 75.5% of prior 2R+ R. The payoff tail was not a single-name
> artifact: prior 2R+ winners spanned both tasks, four task/windows, and eight symbols, the largest symbol
> supplied 21.9% of 2R+ R, and every leave-one-symbol-out prior expectancy remained positive.
>
> Canonical winner MFE fell from a 4.240R median to 2.200R, while median realized/MFE efficiency stayed
> essentially unchanged (0.708 versus 0.718). Median observational 60-minute forward favorable excursion
> fell from 1.551R to 0.717R and to-session-close excursion from 3.161R to 0.906R. Thus Task 56 generally
> did not offer comparable continuation; the exits did not merely discard an otherwise-present excursion.
> Positive END_OF_SESSION payoffs fell from the prior multi-R scale to 1.199R mean in Task 56, even as the
> EOD share rose from 19.6% to 36.4%, supporting changed continuation magnitude as well as exit mix.
>
> All entries were trend-aligned and regime-ready/eligible under the frozen system semantics. Task 56 was
> somewhat shallower in accepted volatility (median 15m ATR 0.655% versus 0.807%; 60m 1.080% versus
> 1.223%), but this was not a stable large-winner separator: Task 54's 2R+ trades were deeper in volatility,
> while Task 53's two 2R+ trades were not. Task 56 was farther above the 15m SMA200 and had wider median
> stop risk, so neither weak HTF alignment nor tight stop/cost geometry explains the payoff tail. Wider risk
> modestly reduced R scaling, while lower price and R excursions supplied the stronger evidence.
>
> **UPDATED CONCLUSION**: `PRIOR_WINNERS_CONCENTRATED`.
>
> **REASON**: the apparent prior RSI edge depended heavily on a small winner tail concentrated in W3 and
> Z_late. Task 56 preserved winner frequency but did not reproduce comparable 4R+ continuation. Although
> lower accepted volatility is plausible context, it failed the required separate Task 53/54/56
> reproducibility check and cannot support a stable large-winner regime claim or candidate filter.

**Scope/validation**: committed trades and already-downloaded Alpaca bars only; no strategy replay, market
download, new signal, parameter search, ML, filter, or production change. Canonical MFE/MAE was independently
checked against entry-through-actual-exit bars with exit-path-correct bounds; all fixed forward horizons were
clipped before 16:00 ET. The sole price reconstruction difference was 0.0001 from source CSV precision.
Protected strategy/config files remained unchanged. This explanatory result authorizes no strategy action;
any proposed rule requires a new preregistered independent validation. Deployment remains
`MONDAY_DECISION_SHADOW_ONLY`.

## Task 59 — Current Candidate Final Triage + Next Architecture Specification (2026-08-23)

> **PREVIOUS**: Task 57 concluded `BOTH_GROSS_AND_COST_WEAK`, and Task 58 concluded
> `PRIOR_WINNERS_CONCENTRATED`. The current candidate had technically valid causal plumbing but only
> +0.092R/trade gross and -0.324R/trade at 5bps across 228 trades. Task 56's independent RSI result was
> near zero gross and negative after costs; MACD remained gross-negative; the stronger prior RSI result
> depended heavily on a small multi-R payoff tail. Deployment remained `MONDAY_DECISION_SHADOW_ONLY`.
>
> **NEW EVIDENCE**: Task 59 traced the current code path end to end without a replay: deduplicated closed
> bars and causal 1m/15m/60m state; RSI/MACD/MA event triggers; experimental 15m/60m ATR eligibility;
> family-aware same-bar independent confirmation; session, blackout, cooldown, loss-lockout, pivot R:R,
> 15m SMA200, and pre-market gates; composite opportunity ranking and throttle; dynamic/fill-time geometry
> revalidation; next-bar entry; hard bracket, opposite-family, and 15:50 exits. This contract is technically
> coherent, shared between live/research paths where intended, and supported by the correctness evidence.
>
> The economic assumptions layered onto that plumbing are unsupported. Three heterogeneous trigger families
> share confirmation, geometry, ranking, and exits without evidence that they represent one edge. Task54's
> accepted trades all had exactly one confirmation, leaving no accepted-trade contrast for its incremental
> value. MACD combined gross expectancy was -0.113R and -0.619R at 5bps; MA produced zero trades. All Task58
> RSI entries were trend-aligned and volatility-regime eligible, but those states did not distinguish a stable
> large-winner regime. Prior-session structural R:R screened technically valid trades without ensuring realized
> payoff, and execution friction erased the weak aggregate gross edge even outside extreme-cost pathology.
>
> One successor was specified from first principles, not optimized against Tasks53–58:
> `FAILED_PULLBACK_RECLAIM_CONTINUATION_V1`. Its hypothesis is that, inside an established uptrend, a brief
> break below regular-session VWAP followed by an immediate reclaim and next-bar price persistence represents
> absorbed supply and continuation sufficient to clear setup-local invalidation and 5bps friction. RSI/MACD/MA
> and 15m/60m ATR thresholds become telemetry, not eligibility. The stop is one tick below the local pullback
> low, no fixed profit target caps continuation, a completed 5m close back below VWAP expresses thesis failure,
> and estimated/actual-fill 5bps burden must not exceed 0.20R.
>
> The untouched evaluation is preregistered as the first 60 complete XNYS trading days after 2026-07-09,
> three consecutive 20-day windows with causal 10-day pre-roll, the same 35 symbols, Alpaca only, and one
> frozen candidate. Mandatory criteria include >=60 trades, >=15/window, >=10 symbols, >=+0.15R 5bps
> expectancy, PF >=1.25, positive bootstrap lower bound, window/symbol/top-winner robustness, and <=0.20R
> actual-fill cost burden. Any failure after unblinding retires FPRC_V1; no threshold adjustment, sample
> extension, gate change, or variant replay is allowed on those windows. A first pass still requires a second
> untouched 60-day replication before any owner production decision.
>
> **UPDATED CONCLUSION**: `REDESIGN_SIGNAL_ARCHITECTURE`.
>
> **REASON**: the current candidate has enough independent, interpretable evidence to reject continued
> threshold/family iteration, but its causal data, execution, risk-control, and diagnostic infrastructure is
> worth retaining. RSI alone is not sufficiently robust to preserve as the next entry architecture. One new
> hypothesis-specific architecture with cost-aware feasibility is justified; the current candidate itself is
> not production-ready.

**Scope/deployment**: read-only evidence synthesis and specification only. No correlation mining, threshold
search, parameter sweep, backtest, data download, signal generation, implementation, capital, or production
behavior change occurred. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; PR #10 remains draft/unmerged.

## Task 60 — FPRC_V1 Implementation and Freeze (2026-08-23)

> **PREVIOUS**: Task 59 concluded `REDESIGN_SIGNAL_ARCHITECTURE` and preregistered exactly one successor,
> `FAILED_PULLBACK_RECLAIM_CONTINUATION_V1` (`FPRC_V1`). The specification authorized no implementation or
> replay at that time. The current candidate remained economically unsupported but technically coherent;
> deployment remained `MONDAY_DECISION_SHADOW_ONLY` with no capital or production action.
>
> **NEW EVIDENCE**: Task 60 implemented FPRC_V1 as an opt-in, separately namespaced completed-bar state
> machine and no-broker shadow/research execution controller. It adds causal regular-session VWAP; two-or-more
> below-VWAP pullback state; reclaim and exact next-bar persistence; one-tick-below-local-low stop; no target;
> completed-5m-below-VWAP next-open thesis exit; hard stop and 15:50 flatten; estimated and actual-entry-fill
> 5bps feasibility capped at 0.20R; cost-first deterministic capacity; and telemetry-only RSI/MACD/MA/ATR.
> Existing long-only, pre-roll, cooldown, lockout, capacity, and next-bar conventions are preserved.
>
> Twelve focused causality/isolation/parity tests passed. The complete suite produced 1,857 passes, one skip,
> 15 expected failures, and one legacy sample-fixture failure: untouched current-candidate code generated one
> signal but rejected it as `LOW_CONFLUENCE` where the fixture expected one trade. The failure reproduced with
> normal Numba JIT and is unrelated to FPRC_V1. No existing strategy, indicator, consumer, config, backtest
> engine, or execution file differs from base `af3bc97d`; the current strategy fingerprint remains
> `2ae6216bca70`. The frozen FPRC_V1 implementation fingerprint is
> `be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64`.
>
> **UPDATED CONCLUSION**: FPRC_V1 implementation and isolation **PASS** and are frozen for a separately
> authorized future independent validation. Validation has not started, and the current candidate remains
> unchanged.
>
> **REASON**: the frozen Task 59 contract is represented directly in one isolated shared semantic path, its
> eligibility inputs cannot be changed by telemetry, and synthetic tests prove causal sequencing, fill-time
> feasibility, risk/exit ordering, operational controls, state isolation, and shadow/research parity. The
> implementation evidence supports freezing code, not claiming an edge.

**Scope/deployment**: no historical replay, independent validation, data download, capital, broker action,
or production integration occurred. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; PR #10 remains
draft and unmerged.

## Task 61 — FPRC_V1 Independent Validation #1 (2026-08-23)

> **PREVIOUS**: Task 60 implemented and froze the isolated FPRC_V1 research/shadow candidate with
> implementation fingerprint `be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64`.
> Its independent validation had not started, no edge had been claimed, and deployment remained
> `MONDAY_DECISION_SHADOW_ONLY`.
>
> **NEW EVIDENCE**: Using XNYS calendar version 4.13.2, Task 61 mechanically resolved the first 60 sessions
> strictly after 2026-07-09 into N1 (2026-07-10 through 2026-08-06), N2 (2026-08-07 through 2026-09-03),
> and N3 (2026-09-04 through 2026-10-02), with their immediately preceding ten-session causal warmups.
> On the attempt date, 2026-08-23, N1 was complete, N2 had 11 of 20 completed evaluation sessions, and N3
> had zero of 20; N3 also had only one of ten completed warmup sessions. Complete 35-symbol Alpaca coverage
> therefore could not yet exist. The frozen fingerprint and Task 60 zero-drift/isolation/parity proofs still
> passed, and 15 focused FPRC_V1/Task61 tests passed.
>
> **UPDATED CONCLUSION**: `VALIDATION_BLOCKED`.
>
> **REASON**: the preregistered temporal-completeness gate failed before provider access. The protocol
> forbids partial coverage, replacement dates, or a reduced replay, so Task 61 stopped without an Alpaca
> request, strategy replay, outcome unblinding, economic computation, or tuning. This is a calendar/data-
> availability block and provides no evidence for either replication or rejection.

**Scope/deployment**: the exact windows are frozen for a later resume. No market data was downloaded, no
historical validation was run, and no production behavior or capital changed. Deployment remains
`MONDAY_DECISION_SHADOW_ONLY`; PR #10 remains draft and unmerged.

## Task 61R — Corrected Temporal Protocol + FPRC_V1 Independent Validation #1 (2026-08-23)

> **PREVIOUS**: Task 61 was `VALIDATION_BLOCKED` solely because its mechanically frozen N1-N3 evaluation
> extended through future sessions ending 2026-10-02. It made no Alpaca request, ran no replay, and
> unblinded no outcomes. FPRC_V1 remained frozen at implementation fingerprint
> `be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64`.
>
> **NEW EVIDENCE**: Before outcome access, Task 61R corrected only the temporal rule and committed the
> correction at `2020eff`. XNYS 4.13.2 mechanically selected the latest 60 consecutive sessions strictly
> before TalonX's earliest canonical historical exposure on 2025-08-15: V1 2025-05-20 through 2025-06-17,
> V2 2025-06-18 through 2025-07-17, and V3 2025-07-18 through 2025-08-14, each with the immediately preceding
> ten-session state-only warmup. The conservative Task37-58 contamination audit found zero overlap, including
> zero overlap with the Task53-58 evidence used to design FPRC_V1.
>
> Alpaca returned `FULL` packages for all 35 symbols (1,257,750 raw bars). Every mandatory pre-replay gate
> passed: exact 35/35 warmup/evaluation session coverage, zero critical corruption, 35/35 first-bar 1m/VWAP/
> 15m-SMA200/FPRC readiness in V1/V2/V3, frozen fingerprints, code-level causality/isolation/parity proofs,
> and current-candidate zero drift. The one authorized replay produced 205 identical-accounting trades:
> 68/72/65 across V1/V2/V3 and 32 symbols. The interpretability floor passed.
>
> Gross expectancy was -0.003285R/trade. At 5bps per side, expectancy was -0.144367R, PF was 0.537551,
> and the fixed-seed 10,000-resample bootstrap 95% interval was [-0.225457R, -0.055401R]. All three windows
> were negative at 5bps (-0.166139R, -0.026659R, -0.251973R), and removing the top three gross winners left
> -0.187913R/trade. Actual-fill feasibility passed (mean 0.141084R; maximum 0.199563R, within 0.20R).
>
> **UPDATED CONCLUSION**: `FPRC_V1_REJECTED`.
>
> **REASON**: although support, breadth, cost feasibility, concentration, and technical correctness passed,
> the frozen candidate failed the mandatory gross-margin, 5bps expectancy, PF, bootstrap, window-robustness,
> and top-three-winner sensitivity criteria. The preregistered hard rejection rule therefore applies and no
> replication is authorized.

**Scope/deployment**: no rule, threshold, symbol, provider, cost, exit, window, or post-outcome filter was
changed; no variant replay, diagnosis, redesign, capital, or production action occurred. Task 61's blocked
history remains intact. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; PR #10 remains draft and unmerged.

## Task 62 — Define, Implement, and Freeze One New Alpha Candidate (2026-08-23)

> **PREVIOUS**: Tasks 53-58 showed that the mixed RSI/MACD/MA candidate was economically unsupported and
> depended on unstable/concentrated payoff behavior. Task 59 required a new architecture. Task 61R then
> independently rejected FPRC_V1: its broad 205-trade sample had near-zero gross expectancy and materially
> negative 5bps economics. FPRC_V1 cannot be tuned, and deployment remained `MONDAY_DECISION_SHADOW_ONLY`.
>
> **NEW EVIDENCE**: Task 62 specified exactly one materially different candidate,
> `OPENING_RANGE_PARTICIPATION_BREAKOUT_V1` (`ORPB_V1`). Its first-principles hypothesis is that the first
> accepted upside break of the 30-minute opening price-discovery range, on participation strictly above the
> opening six-bar median and immediate 1-minute persistence, represents information-driven demand capable of
> continuation. RSI/MACD/MA, VWAP reclaim, ATR gates, and external telemetry do not affect eligibility.
>
> ORPB_V1 is implemented in a separate opt-in namespace with one shared research/shadow controller. The
> contract freezes six completed opening 5-minute bars, first-break-only participation, exact next-bar
> confirmation/fill, breakout-low-minus-one-tick stop, no target, next-open exit after a completed 5-minute
> close back at/below the opening-range high, hard stop-first handling, 15:50 flatten, 0.20R estimated/actual-
> fill feasibility, long-only safety controls, capacity three, and cost-first deterministic ranking. Twelve
> focused tests passed for causality, first-attempt consumption, next-bar semantics, cost recheck, stop/exit
> ordering, telemetry isolation, state isolation, capacity, lockout, and research/shadow parity.
>
> The full suite produced 1,879 passes, one skip, 15 expected xfails, and the same single untouched legacy
> sample-fixture failure documented in Task 60. No existing strategy, indicator, consumer, config, backtest,
> execution, or FPRC file differs from base `e64288e`; current-candidate zero drift passes.
>
> A future outcome-blind validation is frozen on the latest 60 XNYS sessions strictly before Task61R's
> earliest context access: O1 2025-02-07 through 2025-03-07, O2 2025-03-10 through 2025-04-04, and O3
> 2025-04-07 through 2025-05-05, each with ten-session state-only warmup. The entire package precedes every
> Task37-61R evaluation and Task61R warmup/evaluation. A boundary-only Alpaca audit passed 35/35 without
> persisting bars, instantiating the candidate, generating signals, computing returns, or starting validation.
> The protocol requires positive gross and >=+0.10R 5bps expectancy, PF >=1.20, positive bootstrap lower
> bound, window/symbol/top-winner robustness, <=0.20R fill feasibility, sufficient breadth, and correctness.
> Any failure retires ORPB_V1 without tuning O1-O3.
>
> **UPDATED CONCLUSION**: `ORPB_V1_IMPLEMENTED_AND_FROZEN_FOR_VALIDATION`.
>
> **REASON**: ORPB_V1 supplies one explicit, non-indicator, non-VWAP-reclaim gross-alpha mechanism while
> retaining TalonX's proven causal/execution/safety infrastructure. Implementation and freeze evidence support
> an independent test, not an edge claim. No historical ORPB validation has started.

**Scope/deployment**: no ORPB market replay, signal, trade, return, threshold search, variant, capital, broker
action, or production integration occurred. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; PR #10 remains
draft and unmerged.

## Task 63 — ORPB_V1 Independent Validation #1 (2026-08-23)

> **PREVIOUS**: Task 62 implemented and froze `OPENING_RANGE_PARTICIPATION_BREAKOUT_V1` (`ORPB_V1`) at
> fingerprint `b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f`. Its outcome-blind O1-O3
> protocol required complete Alpaca coverage for all 35 symbols and exactly six completed opening 5-minute
> bars on every evaluation session before any signal generation.
>
> **NEW EVIDENCE**: Alpaca returned and persisted `FULL` date-range packages for all 35 frozen symbols from
> 2025-01-24 through 2025-05-05 (1,307,932 raw bars). Fingerprint/source hashes, current-candidate/FPRC/ORPB
> zero drift, Alpaca-only provider identity, critical-corruption checks, causal warmup state isolation, and
> all 12 focused correctness/causality/parity proofs passed. Session coverage was 35/35 in O1, O2, and O3.
>
> The mandatory opening-range readiness gate did not pass. BKNG lacked at least one entire required opening
> 5-minute bucket on 2025-02-10, 2025-02-11, 2025-03-26, 2025-04-25, and 2025-04-30; KLAC lacked one on
> 2025-02-07. Completeness therefore measured 33/35 symbols in O1 and 34/35 in O2 and O3. The gate failure
> reproduced on a second deterministic audit of the persisted package.
>
> **UPDATED CONCLUSION**: `VALIDATION_BLOCKED`.
>
> **REASON**: the frozen protocol prohibits partial coverage, symbol removal, replacement data, or replay
> when any symbol/session cannot form exactly six completed opening-range bars. Task 63 stopped before ORPB
> signal generation, outcome unblinding, trade construction, return computation, or economic classification.

**Scope/deployment**: no replay, tuning, variant, extra window, post-outcome filter, capital, or production
action occurred. ORPB_V1 remains economically unclassified. Deployment remains
`MONDAY_DECISION_SHADOW_ONLY`; PR #10 remains draft and unmerged.

## Task 63R — Resolve ORPB Alpaca Feed Coverage + Resume Validation (2026-08-23)

> **PREVIOUS**: Task 63 was `VALIDATION_BLOCKED` before signal generation because the persisted Alpaca
> package could not form all six frozen opening 5-minute buckets for BKNG on five evaluation sessions and
> KLAC on one. No ORPB signal, trade, return, or outcome was unblinded; ORPB_V1 remained frozen at
> `b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f`.
>
> **NEW EVIDENCE**: A provider-semantics-only diagnostic reproducibly refetched all six affected cases with
> Alpaca's feed parameter omitted, `feed=iex`, and `feed=sip`. SIP access was available. For every case, the
> persisted Task 63 regular-session payload hash exactly matched both the omitted-feed and explicit-SIP
> payloads; it did not match IEX. Task 63 therefore already used SIP despite the omitted parameter.
>
> The explicit-SIP refetch reproduced every missing opening bucket: BKNG remained incomplete on 2025-02-10,
> 2025-02-11, 2025-03-26, 2025-04-25, and 2025-04-30, and KLAC remained incomplete on 2025-02-07. No bar was
> fabricated or interpolated. A uniform-feed manifest records `feed=sip`, all 35 source hashes, and the
> download/feed-diagnostic hashes. The separate Task 63R full gate rerun passed SIP identity, 35/35 package,
> fingerprint/hash, zero-drift, corruption, state-isolation, and 12 focused causality/parity proof gates,
> but reproduced opening-range completeness of 33/35 in O1 and 34/35 in O2 and O3.
>
> **UPDATED CONCLUSION**: `VALIDATION_BLOCKED`.
>
> **REASON**: the uniform Alpaca SIP source itself does not publish enough 1-minute bars to construct every
> required frozen opening bucket. The protocol forbids interpolation, another provider, symbol removal, or
> a relaxed six-bucket gate, so validation again stops before signal generation and outcome access. Resolving
> the implicit feed was a provider/data-definition correction, not strategy tuning.

**Scope/deployment**: Task 63 history is unchanged. No ORPB replay, trade, return, tuning, variant, extra
window, capital, or production action occurred. ORPB_V1 remains economically unclassified. Deployment
remains `MONDAY_DECISION_SHADOW_ONLY`; PR #10 remains draft and unmerged.

## Task 63P — Correct ORPB Data-Readiness Semantics + Execute Validation (2026-08-23)

> **PREVIOUS**: Task 63 and Task 63R were `VALIDATION_BLOCKED` because global all-symbol/all-session
> readiness was too strict despite genuine isolated Alpaca SIP gaps. Both attempts stopped before ORPB
> signal generation, trades, returns, economic metrics, or outcome unblinding. Task 63R proved a uniform SIP
> source and exactly six incomplete evaluation symbol-sessions.
>
> **NEW EVIDENCE**: Before outcome access, Task 63P froze and committed a production-compatible,
> timestamp-only, per-symbol-session fail-closed readiness layer at `f0f2796`. The 35-symbol universe and all
> ORPB alpha/execution/economic semantics remained unchanged. Of 2,100 expected symbol-sessions, 2,094 were
> clean and the six previously documented BKNG/KLAC cases were `DATA_NOT_READY` (99.714286% clean). No bar
> was fabricated, interpolated, filled, or borrowed; post-10:00 data, prices, signals, and outcomes cannot
> affect readiness. Sixteen focused readiness/ORPB causality tests passed.
>
> Every corrected pre-replay gate then passed with no unexpected readiness exception or broader corruption.
> The one authorized replay produced 46 trades across 26 symbols: 13 in O1, 10 in O2, and 23 in O3. There
> were nine gross winners and 37 losses. Gross expectancy was -0.131247R/trade (PF 0.764276). At 5bps per
> side, expectancy was -0.243162R/trade, PF was 0.625910, and the fixed-seed 10,000-resample bootstrap 95%
> interval was [-0.578847R, 0.151632R]. All windows were negative (-0.384916R, -0.251195R, -0.159547R), and
> removing the top three gross winners left -0.488420R/trade. Actual-fill cost feasibility passed (mean
> 0.111981R; maximum 0.196667R).
>
> **UPDATED CONCLUSION**: `ORPB_V1_REJECTED`.
>
> **REASON**: ORPB_V1 failed mandatory support (total/per-window trades and winner/loss counts), positive
> gross expectancy, gross cost margin, 5bps expectancy/PF, bootstrap lower bound, window robustness,
> top-three-winner sensitivity, and positive-R symbol concentration. Technical correctness, breadth across
> symbols, maximum trade-share concentration, readiness isolation, and cost feasibility passed, but any
> mandatory failure requires rejection and stop.

**Scope/deployment**: the ORPB alpha fingerprint remains
`b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f`. Task 62, Task 63, and Task 63R
history is unchanged. No tuning, variant replay, threshold/date/symbol/provider/exit change, replacement
analysis, capital, or production action occurred. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; PR #10
remains draft and unmerged.

## Task 64 — Paper PIV Readiness (2026-08-23)

> **PREVIOUS**: ORPB_V1 was independently rejected; Task 63P proved reusable per-symbol-session readiness
> semantics with fail-closed isolation and no data synthesis.
>
> **NEW EVIDENCE**: Platform readiness was generalized into a strategy-neutral 30-minute opening-session
> validator. A separately namespaced PAPER-only control plane added immutable Alpaca paper routing,
> positive account verification, persistent idempotent order intents, lifecycle telemetry, explicit cleanup,
> restart reconciliation, kill switch, EOD flatten/reporting, and failure-isolated Telegram projection.
> Twenty-two focused tests passed. Protected strategy files have zero diff and the ORPB alpha fingerprint
> remains `b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f`.
>
> The live non-ordering preflight positively verified the Alpaca PAPER account, zero paper orders, zero paper
> positions, matched internal/broker state, the frozen 35-symbol universe, and Telegram reachability. The
> explicit Alpaca `feed=sip` latest-trade request returned HTTP 403. No order, cleanup, or session start ran.
>
> **UPDATED CONCLUSION**: `PAPER_PIV_BLOCKED`.
>
> **REASON**: SIP accessibility is mandatory and preflight is fail-closed. Paper execution remains disabled
> until an approved release receives `PIV_READY`; IEX/live-money fallback is impossible and prohibited.

**Scope/deployment**: no alpha change, optimization, strategy replay, paper order, cleanup mutation, live
endpoint, or capital action occurred. Real capital remains disabled; PR #10 remains draft and unmerged.

## Task 65 / 65B — Complete Paper PIV: Decision Path, Warmup, Crash Resilience (2026-08-24)

> **PREVIOUS**: Task 64 built the PAPER-only safety harness (preflight, order lifecycle, reconciliation,
> Telegram) but nothing drove it from real market data; `cli.py start` only flipped a session flag. Task 65
> reached `PIV_READY` for live IEX and the 35-symbol universe, but the strategy decision path was
> intentionally left disconnected, so a scheduled session would only have tested feed/readiness/telemetry/
> reconciliation plumbing.
>
> **NEW EVIDENCE**: The decision path was restored via `talonx_piv/decision_engine.py`, which drives the
> real, unmodified `talonx_quant.consumer.QuantScanner` in-process -- its live ingestion entrypoint, its own
> throttle flush, its own confluence/risk-reward/trend-alignment/cooldown gating, observed via a real Redis
> subscription to its own signal channel. ORPB_V1 was never used (rejected/retired at Task 63P; live use
> would be a forbidden replay). A predeclared, disabled-by-default `PIV_LIFECYCLE_PROBE` (15:00 ET cutoff)
> was added to guarantee full order-lifecycle coverage on a zero-natural-signal day.
>
> Before the first live run, tracing the actual runtime path found `WARMUP_DEFECT_FOUND`: `QuantScanner`
> started completely cold (needs 120 1-minute bars; the HTF trend gate drops every regular-session bullish
> candidate while the 200-bar 15-minute SMA is unavailable, which could never warm from live-only
> accumulation within one day). Fixed by reusing `QuantScanner.preseed_symbols()` unmodified before any live
> bar is consumed, with independent per-symbol verification and fail-closed exclusion of any symbol that
> cannot be sufficiently hydrated. Verified live against real yfinance data: causal (zero fetched bars after
> fetch-time), and reached 35/35 symbols ready by the second live run.
>
> The first live run (commit `fbc0a0d`, ~09:31-10:33 ET) crashed on an unhandled `requests.exceptions.
> ReadTimeout` from the Alpaca REST poll -- confirmed live, zero orders/positions open at crash time. Fixed
> (commit `b935588`: an isolated tick failure is now logged and skipped, not fatal), re-tested (75 focused +
> full regression clean), and restarted same-day. The second run (~14:41-15:50 ET) ran to the configured EOD
> flatten with zero further failures and reached 35/35 warmup-ready symbols, but produced zero natural
> strategy signals: `SessionReadinessValidator`'s in-memory readiness state does not survive a process
> restart, so every symbol read `DATA_NOT_READY` for the restarted run despite full warmup, and the decision
> engine never received a readiness-eligible symbol. At the predeclared 15:00 ET cutoff, with no natural
> order lifecycle observed, `PIV_LIFECYCLE_PROBE` fired exactly as designed: one AAPL buy/sell round trip
> through the real PAPER broker (filled 311.47 / 311.40), full submit-ack-fill-position-exit-reconciliation
> path exercised. EOD reconciled clean (`matched=true`, zero residual orders/positions). Both ORPB_V1 and
> FPRC_V1 implementation fingerprints reconfirmed unchanged; zero diff on every protected file across the
> entire day.
>
> **UPDATED CONCLUSION**: `V1_PIV_OPERATIONALLY_VALIDATED`.
>
> **REASON**: live IEX ingestion, readiness/staleness detection, causal warmup, and the real decision engine
> were all active and correctly gated; the isolated `PIV_LIFECYCLE_PROBE` exercised the full broker order
> lifecycle per the predeclared fallback rule after zero natural signals occurred; duplicate protection,
> broker/internal reconciliation, Telegram isolation, and EOD all passed clean; no unexplained orders, no
> real-capital capability, no protected-file drift. Caveat carried forward explicitly: the natural strategy
> decision-to-order handoff was not exercised against a readiness-eligible symbol in live conditions today --
> verified only via tests and standalone smoke tests, not one continuous live run -- because a genuine,
> now-fixed engine defect forced a mid-session restart that exposed a second, real, still-open limitation
> (`SessionReadinessValidator` state does not persist across a restart). Recommended before the next PIV
> session: persist readiness state to disk, or restrict restarts to before 10:00 ET.

**Scope/deployment**: no alpha change, tuning, or ORPB/FPRC replay occurred; both remain rejected and
retired. Every event today (natural-path or probe) is tagged `alpha_evidence=false`; alpha remains
UNPROVEN. Real capital remains structurally unsupported; PR #10 remains draft and unmerged. Next major
task: broad development-only alpha discovery (see `results/task65_piv/next_alpha_discovery_plan.md`).

## Task 66A — Repository Cleanup + Infrastructure Hardening (2026-08-24)

> **PREVIOUS**: Task 65/65B reached `V1_PIV_OPERATIONALLY_VALIDATED` but left two open items: (1) a
> genuine engine defect (an unhandled Alpaca REST timeout crashing the session) was found and fixed
> live, and (2) fixing it required a mid-session restart that exposed a second, real limitation --
> `SessionReadinessValidator` state was in-memory only, so the restart made every symbol read
> `DATA_NOT_READY` regardless of true data quality, and the natural strategy decision path was never
> exercised end-to-end against a readiness-eligible symbol in one continuous live run. Separately, the
> PIV runtime was found to omit the inbound Telegram `/ping` health-check listener that the full
> `run_talonx.py` application already provides.
>
> **NEW EVIDENCE**: `talonx_piv/readiness.py` gained atomic, fail-closed persistence
> (`to_state`/`restore_state`/`save_readiness_state`/`load_readiness_state`,
> `session_readiness_state.json`) restoring a finalized READY/DATA_NOT_READY decision exactly as-is
> across a restart, or a still-PENDING symbol's raw pre-10:00 observations so live accumulation
> continues correctly -- never fabricating a bar, never accepting previous-day or malformed state,
> never letting one corrupt symbol entry become eligible while others in the same file restore
> correctly. 18 focused tests, including one reproducing today's actual incident timeline. The
> existing `talonx_dispatch.telegram_listener.TelegramReplyListener` (already designed for a
> standalone `dispatch_agent=None` degrade path) was wired into the PIV runtime as a concurrent
> background task with a PIV-scoped audit DB -- not a second/duplicate listener -- closing the
> inbound-`/ping` gap; a new `talonx_piv/runtime_manifest.py` documents all 13 expected PIV runtime
> components and a `runtime_parity` preflight check now reports `RUNTIME_PARITY_PASS`/`_FAIL`
> explicitly. A conservative, evidence-based repository review found no file meeting the bar for
> deletion (zero imports/references, confirmed superseded, confirmed generated, confirmed duplicate,
> confirmed unreachable) -- three genuine gaps were fixed instead: an untracked `logs/` directory
> added to `.gitignore`, a Task-64-era handoff doc marked superseded in place (original content
> unchanged) pointing to the current canonical handoff, and README updated to reference `talonx_piv`
> and this ledger, neither of which it previously mentioned. Zero files deleted; zero research
> artifacts moved, renamed, or altered.
>
> **UPDATED CONCLUSION**: `INFRASTRUCTURE_HARDENING_COMPLETE`, `FULL_E2E_PIV_READY`.
>
> **REASON**: both open Task 65B items are now fixed and covered by focused tests (18 for readiness
> persistence, 8 for runtime parity/Telegram inbound), the full regression suite grew from 1958 to
> 1984 passing tests with zero new failures (one known pre-existing failure, unchanged), both ORPB_V1
> and FPRC_V1 implementation fingerprints are reconfirmed unchanged, and every protected
> `talonx_quant/*` file has zero diff. This is infrastructure evidence only -- no live session was
> run as part of this task, so a clean, uninterrupted, full end-to-end PAPER PIV session is not yet
> claimed; that requires the next actual PAPER session (see
> `results/task66a_repo_hardening/next_e2e_piv_handoff.md`).

**Scope/deployment**: no alpha change, tuning, or ORPB/FPRC replay occurred; both remain rejected and
retired. No profitability conclusion is made or implied -- this task is infrastructure/repository
hardening only. Real capital remains structurally unsupported; PR #10 remains draft and unmerged. Next
action: one clean, full end-to-end PAPER PIV session (not started by this task), then broad
development-only alpha discovery.

## Task 66B-PREP — Full Application E2E Readiness Audit + Deterministic Startup Hardening (2026-08-24)

> **PREVIOUS**: Task 66A left the PIV runtime `FULL_E2E_PIV_READY`, and an attempt to run that PIV
> session (Task 66B) found the market had already closed for the day (16:39 ET start, past the 16:00
> ET close) -- deferred to the next trading day. Before that session ran, the validation target
> changed: tomorrow's E2E validation is now the **normal** `run_talonx.py` application (Market ->
> Quant -> Brain -> Core -> Dispatch -> Paper -> Telegram), not the narrower `talonx_piv` harness --
> which had never been audited or preflight-checked as its own runtime, and had one known startup
> race (`WatchlistDrivenQuantPreseed`'s initial preseed racing live market data/`quant_scanner.run()`
> with no ordering guarantee).
>
> **NEW EVIDENCE**: Traced `run_talonx.py`'s `main()` directly and documented all 20 runtime
> components (`talonx_ops/runtime_manifest.py`), including an explicit table of how this runtime
> differs from PIV (market-data provider, broker/paper execution path, Brain/Core/Dispatch
> participation, readiness/staleness architecture, reconciliation architecture) -- the two are not
> merged. Closed the preseed race: `talonx_quant/preseed_ordering.py::run_initial_preseed()` is now
> awaited directly in `main()` before any asyncio task exists, reusing `QuantScanner.preseed_symbols()`
> unmodified and verifying per-symbol readiness against the scanner's own real buffer state and
> configured thresholds; `WatchlistDrivenQuantPreseed` gained `already_preseeded_symbols` so its own
> initial pass doesn't repeat that work, with its reactive loop for later additions unchanged --
> verified against real yfinance data (AAPL/MSFT both reached full hydration) and 12 focused tests. A
> new `talonx_ops/preflight.py` (`FULL_APP_E2E_READY`/`_BLOCKED`, 23 checks, read-only) audits the
> normal application specifically, including a hard requirement (Part 4) that Brain must be genuinely
> operational for tomorrow's validation -- production's own graceful-degrade philosophy is unchanged,
> this is a stricter validation-time bar layered on top. `talonx_ops/provider_status.py` makes the
> configured market-data provider and the local-simulated (never Alpaca) paper execution path
> explicit in logs, the preflight report, and a new best-effort `runtime_metadata.json` that
> `generate_eod_report.py` now optionally surfaces in a new "Run metadata" section. A read-only
> `talonx_ops/comparator.py` reconciles PIV-vs-full-app evidence across 13 pipeline stages (only 4
> ever populable from PIV, the rest correctly reported `NOT_APPLICABLE_TO_PIV`) -- smoke-tested
> against today's real PIV evidence, honestly reporting zero matches since no full-app run has
> happened yet. Telegram inbound `/ping` needed no restoration -- `DispatchAgent` already owns a
> fully-wired `TelegramReplyListener(dispatch_agent=self)`, verified by reading the code, not built.
> Two real defects were found and fixed during this task's own live smoke-testing (both caught by the
> new tooling working as intended, not by inspection): a `SyntaxError` in `generate_eod_report.py`
> introduced while adding the metadata section (unbalanced list literal), and a comparator bug that
> initially attributed hollow "full-app evidence" to every watchlist ticker regardless of actual
> pipeline activity. One stale scheduled job (the previous task's PIV-runtime market-open cron, now
> targeting the wrong runtime per the objective change) was found and removed under this task's
> cleanup authority; zero active TalonX/PIV processes were found.
>
> **UPDATED CONCLUSION**: `FULL_APP_E2E_READY` (once this task's own commit lands -- the only
> preflight blocker at dirty-tree time was `tracked_tree_clean` on this task's own uncommitted work).
>
> **REASON**: 45 new focused tests all pass (preseed ordering, preflight, comparator, provider/
> metadata explicitness), the 101 pre-existing PIV/Task66A tests are unaffected, and the full
> regression suite grew from 1984 to 2029 passing tests with zero new failures (the same one known
> pre-existing failure, unchanged). Both ORPB_V1 and FPRC_V1 implementation fingerprints are
> reconfirmed unchanged, every protected `talonx_quant/*` file has zero diff, and no alpha tuning,
> replay, or reinterpretation occurred. This is readiness/infrastructure evidence only -- no live
> session was run or scheduled as part of this task, so a clean, full end-to-end PAPER validation of
> the normal application is not yet claimed; that requires the next actual session (see
> `results/task66b_prep/tomorrow_full_app_handoff.md`).

**Scope/deployment**: no alpha change, tuning, or ORPB/FPRC replay occurred; both remain rejected and
retired. No profitability conclusion is made or implied -- this task is readiness/infrastructure work
only. Real capital remains structurally unsupported; PR #10 remains draft and unmerged. Next action:
one clean, full end-to-end PAPER validation session using `run_talonx.py` (not started or scheduled by
this task; target ~07:00 ET/~12:00 UK), then broad development-only alpha discovery.

## Task 69P — Full Runtime PIV Session (2026-08-25)

> Ran a full end-to-end PAPER session on `research/talonx-strategy-validation` and classified it
> `V1_PIV_OPERATIONALLY_VALIDATED`: full PAPER runtime works end-to-end, Alpaca IEX live data works,
> warmup/readiness/stale protection works fail-closed, QuantScanner runs, Redis works, Telegram
> inbound/outbound works, PAPER broker lifecycle works, EOD reconciliation finishes flat. 35 configured
> symbols, 17 warmup-ready, 15 session-ready, 14 decision-eligible; zero natural signals; one approved,
> operator-confirmed `PIV_LIFECYCLE_PROBE` exercised the full order lifecycle since no natural one fired;
> zero residual broker state; F6_FADE_V1 not integrated; zero alpha evidence. See
> `results/task69p_full_runtime_piv/` for the full evidence set. (This entry backfilled by Task 69Q,
> which deeply reviewed this evidence — see below — since Task69P did not itself add a ledger entry.)

## Task 69Q — Post-Task69P Evidence Closure + Pre-Market/Runtime Notification Upgrade (2026-08-25)

> **PURPOSE**: Task69P's full-day review exposed observability/data-quality gaps that would weaken
> future PAPER profitability evidence if left unfixed, plus a product gap (TalonX going silent from
> startup until 10:00 ET with nothing to show the operator). This task closed both, without touching
> strategy semantics, F6, or real capital.
>
> **DEEP REVIEW**: All 13 of Task69P's headline claims independently reconfirmed against raw evidence
> (not just its own summaries) — see `results/task69q_evidence_upgrade/task69p_deep_review.{json,md}`.
> Found four previously-undocumented gaps beyond the checklist: no candidate-rejection accounting trail;
> an exit fill emitting a second, misleading `POSITION_OPENED` instead of `POSITION_CLOSED` (broker
> exposure was always correct/flat — a naming/state defect, not a financial one); `piv_events.jsonl`
> silently spanning multiple trading dates in one append-only file with no session/date field; and
> `/ping`'s headline Pipeline status reading an unrelated general-ingest subsystem instead of PIV's own
> feed. All four fixed this task. A fifth (yfinance warmup failing 18/35 symbols) was assessed with a
> verified remediation path (a real, read-only Alpaca API call confirmed the account's existing IEX
> entitlement also covers historical bars, returning hundreds of bars for symbols yfinance failed on)
> but not migrated — the buffer-integration work is deferred (PRG-07).
>
> **NEW EVIDENCE / CODE**: `talonx_piv/events.py` gained `session_id`/`trading_date_et`/
> `notification_class` fields (auto-stamped by `EventBus.emit`) and execution-economics fields;
> `talonx_piv/session_identity.py` (new) gives every session a canonical id/config-hash/runtime-sha;
> `reporting.build_session_report` can now filter to exactly one `trading_date_et` and splits
> `natural_strategy` from `piv_test_traffic` explicitly. `talonx_piv/decision_engine.py` now taps
> QuantScanner's existing `rejected_candidates_channel` alongside `signals_channel` (zero changes to
> protected `talonx_quant/*`) to reconcile `candidates = published + rejected + pending + errored` with
> an explicit `unaccounted_candidates` check, and plumbs `reference_price`/`stop_price`/`horizon` into
> `PaperLifecycle.order_intent()` so `talonx_piv/lifecycle.py` can compute real execution economics
> (slippage, gross/net PnL, gross/net R — only when a stop is actually defined, never fabricated) on
> every fill, alongside the `POSITION_CLOSED` fix. `talonx_piv/premarket_radar.py` (new) adds
> observational, ET-canonical (04:00 ET, never UK-clock-driven) `PREMARKET_WATCH`/`_CLEARED`
> notifications computed only from data already available (gap vs previous close via Alpaca's snapshot
> endpoint) — structurally incapable of placing an order (no import of `broker.py`/`lifecycle.py` at
> all). `talonx_dispatch/telegram_listener.py`'s `/ping` Pipeline headline is now PIV-aware (fixed the
> confirmed general-ingest-conflation finding) and its PIV section shows a live-updated unified view
> (session id, feed health, funnel counts, natural/probe traffic, radar WATCH count). A rate-limited
> (≤1/30min) `STATUS_HEARTBEAT` ("No actionable trades. Engine active.") fires during a quiet regular
> session. `talonx_piv/alpaca_historical_warmup.py` (new, prototype only, not wired into the live warmup
> path) proves the Alpaca-historical-bars fetch works against the real account/entitlement.
>
> **PERMANENT PRODUCT RECORD**: `docs/research/TALONX_PIV_RUNTIME_PRODUCT_TARGET.md` (new) records the
> ET-canonical session clock, the pre-market three-concepts split (system prep + radar analysis live,
> actionable pre-market trading deliberately disabled until a validated strategy exists), the target
> ticker-decision contract shape, and the six-category notification taxonomy, so this direction survives
> across future tasks.
>
> **UPDATED CONCLUSION**: All fixes are additive/non-invasive to `talonx_quant/{strategy,indicators,
> consumer,config}.py` (zero diff, confirmed) and to F6_FADE_V1/ORPB_V1/FPRC_V1 (unchanged, not
> integrated). 29 new focused tests pass; two pre-existing test issues fixed as drive-bys (one fixture,
> one stale assertion predating this task, both confirmed via `git stash` to be independent of this
> task's changes); full regression: 2060 passed, 1 pre-existing unrelated failure (also confirmed via
> `git stash`), 1 skipped, 15 xfailed. No real-capital capability introduced. WATCH cannot submit an
> order (tested at the AST-import level, not just behaviorally). See
> `results/task69q_evidence_upgrade/` for every contract/gap document.
>
> **REASON**: this closes the evidence-quality and operator-visibility gaps Task69P's own review
> surfaced, without touching alpha/strategy content, so the next live PAPER session's data is actually
> trustworthy for profitability measurement. See
> `results/task69q_evidence_upgrade/production_readiness_gaps.json` for every deferred item and
> `next_live_session_plan.md` for the next session's plan (prepared, not started).

**Scope/deployment**: no alpha change, tuning, threshold adjustment, or ORPB/FPRC/F6_FADE_V1 replay
occurred in Task69Q; all three remain exactly as before. Real capital remains structurally unsupported.
Next action: Task70 — accelerated frozen-alpha validation / historical holdout assessment is the
immediate priority; the next live PAPER session (plan recorded, not started) can run in parallel on
market days.
