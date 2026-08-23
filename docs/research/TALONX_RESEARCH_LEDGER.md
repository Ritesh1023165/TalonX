Warning: truncated output (original token count: 94416)
Total output lines: 5484

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
`reports/live_session_2026-08-18_po…64416 tokens truncated… 46 — Fast 35-Symbol Experimental Regime Validation, using a
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

