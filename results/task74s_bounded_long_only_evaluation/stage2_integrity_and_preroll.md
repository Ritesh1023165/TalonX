# Task 74S — Stage 2: Full causal pre-roll and integrity checks

## 1. Pre-existing control tests (run BEFORE the historical replay, per this task's own requirement)
`tests/test_task73s_control_fixture.py` (Task 73S's 3 labeled `TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE`
control cases — eligible/rejected/readiness-blocked): **3 passed** in 114.31s, zero code changes made.
This confirms the harness is still reachable and correct at the current HEAD before committing ~4
hours to the historical replay.

## 2. Data quality — all 10 symbols
`talonx_backtest.data.check_data_quality` run directly against each symbol's CSV (see
`stage2_data_quality_report.csv`): zero duplicate timestamps, zero out-of-order timestamps, zero
critical corruption for all 10 symbols. `unexpected_intra_session_gap_bars` (3,906-4,775 per symbol)
is the pre-documented cosmetic false-positive (Task 7B's own recorded caveat: no holiday calendar
exists in the repo, so exchange holidays are misclassified as unexpected gaps by this report; the
strategy itself never consults this classification for gating) -- not a correctness issue.

## 3. Causal pre-roll
No synthetic pre-roll is manufactured and no complete minute grid is forced. The full downloaded
history for each symbol IS its own pre-roll: RSI(14)/MACD(12,26,9)/ATR(14) warm up naturally within
the data itself (`compute_indicators` returns `None` during warm-up, both live and backtest fail
closed identically per `talonx_quant/indicators.py`). The 200-bar/15-minute HTF trend gate
(`_trend_gate_applicable`, RTH-only) warms up within roughly the first 8 trading days of this
~1-year window per symbol -- immaterial for a window this long (Task 73S already established
`HTF_DATA_UNAVAILABLE` never appeared across a 4.5-month AAPL-only window; this window is over twice
that length for every symbol). Existing gaps in the source data (holiday/session boundaries) are
preserved as-is, not filled or interpolated.

## 4. Config/dataset identity re-verified at replay launch time
- `talonx_quant.config.QuantConfig()` default `confluence_score_min == 2` (unchanged).
- Protected files (`talonx_quant/{strategy,indicators,consumer,config}.py`,
  `talonx_piv/{eod_lifecycle,session_runner,cli,events}.py`) have zero diff since `848de0d`
  (re-confirmed via `git diff 848de0d..HEAD -- <protected files>`, empty).
- Dataset: `data/historical_1m/task7b_alpaca_long_history`, provider `alpaca`, feed `SIP`,
  dataset hash `5e5412a960bf` (unchanged from Task 72O/73S/the broader ledger history).

## 5. Replay launch (see `stage3_replay_launch_manifest.json`)
Launched as a single background process (no re-launch, no scope change) at
`2026-08-27T07:13:10Z`, all 10 symbols in one `talonx_backtest` CLI invocation, `--research-telemetry`
enabled, primary cost config (5/5/10bps), no `--start`/`--end` clipping (each symbol uses its own full
downloaded range independently -- the strategy warms up and operates per-symbol, so no cross-symbol
date alignment is required for correctness; this matches how the ledger's Task 26/36 canonical
baseline runs were also described, "the full Task 26 dataset", without per-symbol date clipping).
Estimated runtime ~234 minutes per Task 36's own recorded figure for an identical-size dataset.

**Stage 2 verdict: PASS.** Proceeding to Stage 3 once the replay completes.
