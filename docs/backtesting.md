# Backtesting

A quick-start guide for `talonx_backtest` — TalonX's historical
backtesting / quantitative-validation engine. It replays historical
1-minute OHLCV data through the **exact same, frozen** strategy code
`talonx_quant` uses live (same indicators, same gates, same thresholds
— see `talonx_backtest/engine.py`'s own module docstring for the
architecture). This engine never tunes, optimizes, or modifies the
strategy; it only measures it.

You do not need to read any source code to follow this guide.

```text
Fresh repository
      ↓
Install
      ↓
Get historical data
      ↓
Validate data
      ↓
Run first backtest
      ↓
Open report
```

---

## Installation

From the repo root (`C:\workspace\TalonX`):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r talonx_quant\requirements.txt
```

`talonx_backtest` adds no dependencies beyond what `talonx_quant`
already requires (`pandas`, `pandas_ta`, `numpy`, `pydantic`) — there is
no separate `talonx_backtest\requirements.txt`.

Verify the install:

```powershell
python -m talonx_backtest --help
```

---

## Run the sample backtests first

Before getting real data, prove the whole pipeline works on your
machine using the three deterministic sample datasets checked into the
repo — **none represent real market performance, and none should be
cited as evidence of TalonX's real-world profitability.** They are
integration-test fixtures only. Together they exercise the zero-trade
path, a single winning trade, and a full win/loss/EOD-flatten mix. See
[`examples/data/README.md`](../examples/data/README.md) for the full
breakdown.

### `sample_AAPL_1m.csv` — smoke-test dataset (zero-trade path)

```powershell
python -m talonx_backtest --data examples\data\sample_AAPL_1m.csv --symbol AAPL --tz America/New_York --out results\sample
```

Proves data loading, data-quality validation, and report generation
work. **Zero trades is the correct, expected result** here — every
candidate signal this dataset produces is rejected on confluence, and
the report/`trades.csv`/`equity_curve.csv` say so explicitly (headers
only, never an ambiguous empty file — see "Zero-trade output" below).

### `sample_AAPL_trade_1m.csv` — trade/execution dataset (actual-trade path)

```powershell
python -m talonx_backtest --data examples\data\sample_AAPL_trade_1m.csv --symbol AAPL --tz America/New_York --out results\sample_trade
```

Specifically engineered (two synthetic "trading days": the first
establishes pivot levels the R:R gate needs, the second contains an
engineered run-up-then-reversal that naturally produces a
`MACD_BEARISH_CROSS` candidate with confluence 2/3 and R:R comfortably
above 1.5) to clear the **exact, unmodified, frozen production
`QuantConfig`** — no gate was relaxed to make this happen. Produces one
executed trade, exiting via `TARGET`, populating `trades.csv`,
`equity_curve.csv`, and the HTML report's trade metrics/equity curve/
distribution charts.

### `sample_multi_trade_1m.csv` — multi-scenario dataset (TARGET / STOP / EOD-flatten, win+loss statistics)

```powershell
python -m talonx_backtest --data examples\data\sample_multi_trade_1m.csv --symbols TSTW,TSTL,TSTE --tz America/New_York --out results\sample_multi
```

Three independent synthetic symbols in one file, each reusing the SAME
proven signal setup (confluence 2/3, R:R comfortably above 1.5 — again
never relaxed) with a different post-entry price path:

| Symbol | Continuation after entry | Exit |
|---|---|---|
| `TSTW` | keeps declining | `TARGET` (win) |
| `TSTL` | sharp reversal back through the stop level | `STOP` (loss, a clean -1R) |
| `TSTE` | bounded oscillation, held until 15:50 ET | `END_OF_SESSION` (win, via the real EOD-flatten sweep) |

This is the one fixture where profit factor, average loss, drawdown,
cumulative R, and win/loss statistics are all exercised on real,
non-degenerate numbers (2 wins, 1 loss) rather than `n/a`/`inf`
placeholders.

Then open `results\sample\`, `results\sample_trade\`, or
`results\sample_multi\backtest_results.html` in a browser.

### A note on the three R:R fields on a trade record

`trades.csv`/`trades.json` carry THREE R:R numbers, deliberately kept
distinct rather than collapsed into one — each answers a different
question, and none is a bug:

| Field | What it answers | Computed from |
|---|---|---|
| `risk_reward_ratio` / `screening_rr` (identical — `screening_rr` is an explicitly-named alias) | "What R:R did the strategy's own gate approve this candidate on?" | `atr_stop_multiplier × ATR`, measured at the moment the signal was revalidated (an audit trail of the STRATEGY's decision — never recalculated against the executed fill) |
| `execution_rr` | "What R:R was actually available at the price this order filled at?" | `\|target_price − entry_price\| / \|entry_price − stop_price\|`, using the REAL fill price (the next bar's open) against the same fixed stop/target. You can verify this yourself directly from the `entry_price`/`stop_price`/`target_price` columns sitting right next to it. Fixed at entry time — independent of `exit_reason` (a STOP or an EOD-flattened trade still has an `execution_rr`, same as a TARGET one would have). |
| `gross_R` / `net_R` | "What did this trade ACTUALLY realize?" | The real exit price against the real fill price — depends on `exit_reason`; only equals `execution_rr` when the trade happens to exit at exactly the target price |

Price can (and, in `sample_AAPL_trade_1m.csv`/`sample_multi_trade_1m.csv`,
deliberately does) move between "signal published" and "order filled" —
entry is always the NEXT bar's open, never the same bar the signal
fired on — so `screening_rr` and `execution_rr` are expected to differ;
neither is recalculated to match the other.

### Zero-trade output is never an ambiguous empty file

An equity curve is inherently anchored to trade *exits* — with zero
trades there's no real observation to report, so rather than fabricate
a `0.0 at the start` reading that never happened, `talonx_backtest`
writes a **header-only, zero-row CSV** for both `trades.csv` and
`equity_curve.csv` when nothing executed. A zero-byte file would be
ambiguous (crashed run? truly zero trades?); a headers-only file is
not. The HTML report and `summary.txt`/`summary.json` state explicitly
when zero trades occurred and point you at the rejection funnel to see
why.

---

## Data requirements

### Format

`talonx_backtest` consumes **1-minute OHLCV** bars. A CSV needs at
least these columns (case-insensitive, any order):

```csv
timestamp,open,high,low,close,volume
2025-01-02 09:30:00,100.10,100.50,99.90,100.40,123456
2025-01-02 09:31:00,100.40,100.60,100.20,100.35,98211
2025-01-02 09:32:00,100.35,100.55,100.10,100.50,110044
```

A `symbol` column is optional — if absent, pass `--symbol AAPL` (single
file) or use the directory layouts below (the symbol is inferred from
the folder/file name).

### Timestamps and timezone (read this carefully)

This is the single most common source of a wrong backtest. `--tz` tells
`talonx_backtest` how to interpret **naive** timestamps (no UTC offset
in the file) — it does NOT change already-timezone-aware timestamps,
which are always converted straight to UTC regardless of `--tz`.

| Your CSV's timestamps look like... | Use |
|---|---|
| `2025-01-02 09:30:00` and that's exchange-local wall-clock time (e.g. exported from a US broker/data vendor as "market time") | `--tz America/New_York` |
| `2025-01-02 14:30:00` and that's already UTC | `--tz UTC` (the default — you can omit `--tz`) |
| `2025-01-02T09:30:00-05:00` (has an explicit offset) | `--tz` is ignored for this file; the offset in the data wins |

Getting this wrong silently shifts every bar by hours relative to the
real market session — a bar timestamped 09:30 ET would be evaluated as
if it happened at 09:30 UTC (04:30 ET, hours before the market opens),
which corrupts session classification (pre-market/regular), the
opening/closing blackout windows, and the 15:50 ET EOD-flatten sweep.
**When in doubt, check a few known-time bars in your source (e.g. the
09:30 market open) against what `--tz` would produce.**

Internally, everything is normalized to **UTC** the moment it's loaded
(this is the "internal timezone" — always UTC, not configurable). The
US-equities session classification the strategy itself uses (pre-
market/regular, 09:30-16:00 ET) is separately fixed to
**America/New_York** — that's the market's own timezone, not something
you configure. The generated report shows all three (input / internal /
session timezone) explicitly so you can verify them at a glance.

### Extended hours

Pre-market bars (04:00-09:30 ET) are supported and evaluated with the
strategy's stricter pre-market thresholds — but the pre-market
liquidity and news-catalyst gates are **fail-closed** with no quote/news
feed (which this engine doesn't have by default), so pre-market
candidates are always dropped in a backtest. This matches live
behavior under a permanently-missing-data condition, not a
backtest-only relaxation — see the "Known limitations" section below.

---

## Validate your data

Every run prints a data-quality report before touching the strategy:

```powershell
python -m talonx_backtest --data data\AAPL_1m.csv --symbol AAPL --out results\AAPL
```

```text
Data-quality report: AAPL
  Rows:                    391,040
  Range:                   2024-01-02 09:30:00+00:00 -> 2025-12-31 16:00:00+00:00
  Timezone:                UTC
  Inferred bar interval:   60.0s
  Duplicate timestamps:    0
  Out-of-order timestamps: 0
  Missing bars (total):    198,432 (612 gap(s))
    Expected (session closed):    198,201
    Unexpected (inside session):  231
  Invalid prices (<=0):    0
  Invalid OHLC relations:  0
  Negative volume:         0
  NaN values:              0
  Infinite values:         0
  CRITICAL CORRUPTION:     no
```

"Missing bars" is split into **expected** (overnight/weekend/outside
the 04:00-16:00 ET trading window — completely normal for equities) and
**unexpected** (a hole inside a session that WAS supposed to have data —
worth investigating). Don't panic at a large "expected" number; do
investigate a nonzero "unexpected" one.

### Critical corruption aborts the run

NaN values, infinite values, non-positive prices, an impossible OHLC
relationship (e.g. `high < low`), negative volume, or an unusable/
unparseable timestamp (including an ambiguous timestamp under a DST
fall-back transition) **abort the backtest with a nonzero exit code**
before any strategy logic runs:

```text
ERROR
BACKTEST ABORTED
Critical data corruption detected -- backtest aborted. Fix the source data before retrying.
  AAPL: invalid_prices=3 invalid_ohlc_relationship=0 negative_volume=0 nan_values=0 infinite_values=0
```

None of this is auto-repaired. Fix the source data and re-run.

### Recoverable issues

Duplicate or out-of-order timestamps are the one class of issue this
engine can mechanically fix (`sort_and_dedupe`) — but it never does so
implicitly. Pass `--auto-dedupe` to opt in:

```powershell
python -m talonx_backtest --data data\AAPL_1m.csv --symbol AAPL --auto-dedupe --out results\AAPL
```

Without `--auto-dedupe`, the run proceeds with a loud warning and the
dataset is left untouched.

---

## Where to get historical 1-minute OHLCV data

`talonx_backtest` itself does not download data — but the repo has a
companion downloader, `scripts/download_historical_1m.py`, that writes
straight into the CSV layout the engine expects (see "Automating
downloads" below). Practical sources it supports:

- **Polygon.io REST** (`POLYGON_API_KEY`) — multi-year 1-minute
  aggregates, paginated automatically.
- **Alpaca Markets** (`APCA_API_KEY_ID` + `APCA_API_SECRET_KEY`) —
  same idea, Alpaca's `/v2/stocks/{symbol}/bars` endpoint.
- **`yfinance` fallback** (already a project dependency, used elsewhere
  in `talonx_quant` for pre-seeding; needs no account/key) — its
  1-minute history is limited to roughly the trailing 30 days, enough
  for a short validation run but not a multi-year backtest. Yahoo also
  caps any single 1-minute request at ~8 days, so
  `scripts/download_historical_1m.py` chunks a wider range into 7-day
  sliding windows automatically and stitches them back into one
  deduplicated, sorted series — you never need to chunk a request by
  hand.
- **A broker/data API you already have access to, used manually**
  (Interactive Brokers, IEX Cloud, etc.) or **a paid vendor's flat
  files** (Databento, Tiingo) if you need a multi-year,
  survivorship-bias-aware dataset the downloader script doesn't cover —
  export to the same CSV schema by hand.

No specific provider is hard-coded into the backtest ENGINE, and the
sample datasets above need no API key at all. Whatever the source, the
workflow is the same:

```text
Data provider
    ↓
Download (scripts/download_historical_1m.py, or by hand)
    ↓
Convert to required CSV format (timestamp,symbol,open,high,low,close,volume)
    ↓
talonx_backtest data-quality validation (automatic, on every run)
    ↓
Backtest
```

---

## Directory layouts (multiple symbols / multiple files)

```text
data/
    AAPL/
        2024.csv
        2025.csv
    MSFT/
        2024.csv
        2025.csv
```
or a flat layout (what `scripts/download_historical_1m.py` writes):
```text
data/
    AAPL.csv
    MSFT.csv
```

```powershell
python -m talonx_backtest --data data\ --symbols AAPL,MSFT --start 2024-01-01 --end 2025-12-31 --out results\multi
```

---

## Automating downloads and multi-regime runs

### `scripts/download_historical_1m.py`

```powershell
pip install -r scripts\requirements.txt   # requests + polygon-api-client -- optional, only needed for those two providers
python scripts\download_historical_1m.py --symbols AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AMD,PYPL,STX --start-date 2024-01-01 --end-date 2026-08-01 --output-dir data\historical_1m
```

Picks a provider automatically (Polygon if `POLYGON_API_KEY` is set,
else Alpaca if both `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY` are set,
else `yfinance`) — or force one with `--provider {polygon,alpaca,yfinance}`.
`--symbols` also accepts a path to a text file (one ticker per line).
Retries each provider call with jittered exponential backoff
(`talonx_ingest.common.backoff`, the same helper the live ingest
pipeline uses) and fails soft PER SYMBOL — one bad ticker doesn't abort
the batch. Writes `<output-dir>/<SYMBOL>.csv` and prints a
`check_data_quality` report for each symbol immediately after writing
it, so a broken download is visible right away, not just when you later
try to backtest it.

### `scripts/run_historical_regimes.py`

```powershell
python scripts\run_historical_regimes.py --data-dir data\historical_1m --symbols AAPL,MSFT,NVDA --out-dir reports
```

Runs the SAME frozen strategy (via real `python -m talonx_backtest`
subprocesses — full process isolation between runs, nothing shared)
across four pre-configured historical date ranges:

| Regime | Period |
|---|---|
| `bull_momentum_2024` | 2024-01-01 → 2024-06-30 |
| `high_vol_pullback_2024` | 2024-07-15 → 2024-09-30 |
| `range_chop_2025` | 2025-01-01 → 2025-12-31 |
| `full_period_2024_2026` | 2024-01-01 → 2026-08-01 |

Each regime's full report set lands in `reports/regime_<name>/`
(`--cost-sensitivity` is included by default; `--no-cost-sensitivity` to
skip it), and a consolidated `reports/regime_comparison.md`/`.json`
compares Total Trades, Win Rate, Profit Factor, Expectancy, Max
Drawdown, and Sharpe/Sortino across all of them side by side. Use
`--regimes name1,name2` to run a subset.

This is **empirical measurement across time windows, not parameter
search** — the exact same `QuantConfig` runs in every regime; nothing
is tuned between them, and a regime with a favorable-looking number is
never used to justify changing anything. A regime with too few trades
to be meaningful reports `n/a`, never a fabricated figure — see
"Statistical confidence" above.

---

## Your first real backtest

```powershell
python -m talonx_backtest `
  --data data\AAPL_1m.csv `
  --symbol AAPL `
  --tz America/New_York `
  --start 2025-01-01 `
  --end 2025-12-31 `
  --out results\AAPL
```

(PowerShell line continuation is a backtick `` ` ``, not a backslash —
drop the line breaks entirely if pasting into a different shell.)

This uses the **frozen production strategy** — no CLI flag can change
RSI/volume/ATR/R:R/confluence/cooldown/throttle thresholds or the
opportunity-score weights. The only flags that affect anything are
execution-mechanics ones (below).

---

## Execution assumptions and cost-free baselines

Every report prominently shows the execution assumptions it was run
with:

```text
Execution assumptions
----------------------
Entry slippage:       0 bps
Exit slippage:        0 bps
Spread:               0 bps
Same-bar resolution:  STOP_FIRST
EOD flatten:          ENABLED
```

The default is **zero-cost** (no slippage, no spread) — useful as a
debugging/upper-bound baseline, but the report will show, prominently,
in the HTML, `summary.txt`, and `summary.json`:

```text
*** COST-FREE BASELINE ***
These results do NOT represent realistic execution costs.
```

Set realistic costs explicitly:

```powershell
python -m talonx_backtest --data data\AAPL_1m.csv --symbol AAPL `
  --entry-slippage-bps 5 --exit-slippage-bps 5 --spread-bps 10 --out results\AAPL
```

### Cost-sensitivity mode

Rather than guessing one cost assumption, run the SAME backtest across
several at once:

```powershell
python -m talonx_backtest --data data\AAPL_1m.csv --symbol AAPL --cost-sensitivity --out results\AAPL
```

This evaluates 0/5/10/20 bps (entry slippage = exit slippage = spread,
per scenario — a simple, uniform, documented cost model, not a
calibration to any specific venue), writes `cost_sensitivity.csv`, and
shows a table in `results.html`. It is **sensitivity analysis only** —
it never picks, highlights, or recommends a "best" scenario.

### Same-bar stop/target resolution

When a single bar's range touches both the stop and the target, which
is assumed to have happened first matters a lot for backtest realism.
Default `stop_first` (conservative — never overstates performance);
`--same-bar-resolution target_first` is available for sensitivity
comparison, never as a "better" default.

### EOD flatten

Mirrors `talonx_paper`'s real 15:50 ET daily flatten sweep — any open
simulated position is force-closed at that time each day
(`exit_reason=END_OF_SESSION`). `--no-eod-flatten` disables it (trades
then only close on stop/target/data-end). The report always states
which mode was used.

---

## Reading `results.html`

This is the primary way to review a backtest — you shouldn't need to
open the CSV/JSON files by hand. It contains, in order:

1. **Overview** — period, symbols, bars processed, signals
   generated/published, trades, throttle fidelity.
2. **Cost-free-baseline warning**, if applicable.
3. **Performance** — win rate, profit factor, expectancy, total R, max
   drawdown, Sharpe/Sortino, MFE/MAE (including win/loss-split MFE/MAE)
   — toggle gross (before costs) vs. net (after costs).
4. **Equity curve** and **drawdown** charts.
5. **Trade return distribution** (histogram).
6. **Exit reasons** (TARGET/STOP/END_OF_SESSION/DATA_END) and the
   **rejection funnel** (which gate dropped how many candidates).
7. **Breakdowns**: by symbol, confluence, R:R bucket, volume bucket,
   session, time-of-day, direction, trend alignment.
8. **Cost sensitivity** table, if `--cost-sensitivity` was used.
9. **Execution assumptions**, **timezone**, and **reproducibility**
   metadata (git commit, strategy/backtester version fingerprints,
   config hash, run timestamp) — everything needed to reproduce this
   exact run later.
10. **Data quality** summary.
11. **Research limitations** (portfolio-sizing and survivorship-bias
    disclaimers — see below).
12. The full, sortable **trade table**.

---

## Reproducibility

Every `summary.json`/`results.html` records:

```json
{
  "git_commit": "…or \"UNKNOWN\" if this isn't a git checkout",
  "backtester_version": "0.1.0",
  "strategy_version": "…sha256 fingerprint of talonx_quant's strategy/indicator/config/session source, first 12 hex chars",
  "config_hash": "…sha256 fingerprint of the full effective QuantConfig+ExecutionConfig, first 12 hex chars",
  "run_timestamp": "…UTC ISO-8601"
}
```

Two runs with the same `config_hash` used the exact same effective
configuration. This project defines no semantic version number for
either the strategy or the backtester, so both "version" fields are
content fingerprints — they change if and only if the underlying code
actually changes, rather than being an invented number that could
silently drift out of sync with reality.

---

## Causal pre-roll/warmup (Task 53)

`BacktestEngine.run(df, warmup_df=None)` — an optional second frame, causally strictly earlier
than `df` (evaluation), that reconstructs 1m/15m/60m market-state buffers
(`RollingBarBuffer`/`HtfBarAggregator`) BEFORE the first evaluation bar, via the same buffer/
aggregator objects and update path evaluation itself uses (`_feed_market_state`).

**Evaluation-window vs. warmup-history — an important distinction, not interchangeable.**
`df` is the sample being measured: every trade, rejection, and frequency/economics statistic comes
from it, and only it. `warmup_df` exists ONLY to make indicator/HTF/regime state honestly ready at
the first evaluation bar — it is fed through a state-only path (`_warmup_symbol_bar`) that never
generates a candidate, rejection, signal, trade, or cooldown/loss-lockout event, and is counted in
a wholly separate `warmup_bars_processed` metric, never mixed into `bars_processed` or any
trade/economics figure. **No economic conclusion should ever be drawn from warmup data** — it
produces no trades by construction.

**Why an isolated short evaluation window is invalid for 200-period 15-minute SMA readiness**: the
trend gate needs `htf_sma_period=200` completed 15-minute regular-session bars —
`200 × 15min ÷ (6.5h/day × 60min/h) ≈ 7.7 trading days`. A backtest run over a window narrower than
that, with no preceding warmup, can NEVER produce a valid trend reading for any symbol — the HTF
buffer simply hasn't accumulated enough bars yet, regardless of strategy quality. This was
discovered in Task 52 (a 5-trading-day evaluation window produced 0/618 valid bullish trend
readings) and confirmed as the true cause once resolved: Task 53's 10-trading-day warmup, added to
the SAME 5-day evaluation windows, brought that to 466/702 valid readings and enabled the first
executed trades that population had ever produced. See `results/task52_historical_ab_freeze/` and
`results/task53_preroll_ab_validation/` for the full before/after evidence.

`run(df)` with no `warmup_df` (the default) remains byte-for-byte the pre-Task-53 behavior — see
`tests/test_backtest_preroll.py`.

---

## What this backtester does NOT do

- **Portfolio-level simulation**: no starting capital, position sizing,
  max exposure, concurrent-position limits, or buying power are
  modeled. Every metric is trade-level (R-multiples). The report
  states this explicitly — do not read aggregate R as a realistic
  portfolio return.
- **Survivorship-bias-free universes**: this is an individual-security
  backtest. If you test today's well-known large-caps against a long
  historical window, you're implicitly using a survivorship-biased
  universe (delisted/acquired names are absent). Point-in-time universe
  construction isn't implemented.
- **Tick-level throttle fidelity**: the live 15-second throttle window
  can't be reproduced exactly from 1-minute OHLCV — candidates sharing
  one bar-close minute are ranked and flushed as a single window
  instead. The report labels this `LIMITED`.
- **Automatic optimization**: there is no `--optimize` flag and never
  will be in this engine. It measures the frozen strategy; it does not
  search for a better one.

---

## Sample data generation

All three `examples/data/*.csv` files are generated by short, fixed-seed
scripts — deterministic (identical output every regeneration), never
randomness without a fixed seed.

**`sample_AAPL_1m.csv`**: two full regular sessions (09:30-16:00 ET) of
mild, purely arithmetic price drift (`+0.05`/`-0.03` alternating) —
deliberately simple, no RNG at all. Warms up the indicator buffer and
produces a handful of candidate signals, all of which land below
`confluence_score_min` — proving the validation/reporting pipeline
without ever needing to satisfy the R:R gate.

**`sample_AAPL_trade_1m.csv`**: two full regular sessions built from a
`numpy.random.default_rng(42)` (fixed-seed) small random walk for
realism, with a deliberate structure layered on top:
1. **Day 1** — random-walk only. Its high/low/close become the prior
   session's floor-trader pivot levels (P/R1/S1) the R:R gate measures
   reward against.
2. **Day 2, first ~20 bars** — random-walk only (clears the 09:30-09:45
   ET opening blackout).
3. **Day 2, ~30-bar run-up** — a deliberate upward drift on top of the
   random walk, pushing RSI toward/above 70 and MACD's fast line above
   its signal line.
4. **Day 2, reversal** — a handful of down bars flip the MACD cross;
   the second reversal bar's own RSI (>70) and the MACD cross together
   score confluence 2/3 under the **unmodified** `_confluence_score`
   formula in `talonx_quant/strategy.py` — no threshold was touched to
   make this land at 2, it's a property of where the run-up peaked.
5. **The rest of day 2** — continued decline, giving the resulting
   `MACD_BEARISH_CROSS` short a clean path down to the prior day's
   pivot support (`TARGET`) rather than back up through its stop.

This was found by iterating the fixed-seed random walk against the
REAL `talonx_quant.strategy.evaluate_signals`/`indicators.compute_indicators`
pipeline (not by predicting RSI/MACD values by hand) until a candidate
naturally cleared every frozen gate — see `tests/test_backtest_sample_data.py::test_trade_dataset_signal_satisfies_the_frozen_strategy_naturally`,
which asserts the resulting trade's `confluence_score`/`risk_reward_ratio`
against the live `QuantConfig` defaults, not a relaxed test config.

**`sample_multi_trade_1m.csv`**: three symbols, each independently built
with the SAME day-1/day-2/run-up/reversal recipe as
`sample_AAPL_trade_1m.csv` (two are even the exact same fixed seed) —
they diverge only in what happens to price AFTER entry:
- `TSTW` — the shared reversal simply continues declining → `TARGET`.
- `TSTL` — after the shared decline, price reverses sharply upward for
  12 bars (`+1.5`/bar) — enough to climb back past entry AND past the
  stop level (entry + 1.5×ATR), not just back to breakeven → `STOP`.
- `TSTE` — after the shared decline, price holds in a tight, non-
  compounding oscillation around its own last close (anchor + small
  noise each bar, not a running random walk, so it can't accidentally
  drift into the stop or target over a long tail) for ~340 bars, until
  the real 15:50 ET EOD-flatten sweep force-closes it → `END_OF_SESSION`.

Because the three symbols are independent buffers processed in one
chronological multi-symbol pass, `TSTE`'s much longer bar sequence also
demonstrates that EOD-flatten checks EVERY currently-open position at
each global timestamp, not just symbols with a bar at that instant —
`TSTL`'s own bar sequence is much shorter, but its position (if still
open) would be swept by the same global 15:50 ET check.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ERROR / BACKTEST ABORTED` | Critical data corruption — read the printed detail, fix the source CSV. |
| `error: no rows loaded after filtering` | `--start`/`--end`/`--symbols` excluded everything, or the file is empty. |
| Zero trades, all `LOW_RISK_REWARD` rejections | The R:R gate needs at least one **completed prior trading session** in the data to derive pivot levels — feed multi-day data. |
| Zero trades, all `PREMARKET_LIQUIDITY` rejections | Expected for pre-market candidates — see "Extended hours" above. |
| Results look shifted by several hours | Check `--tz` against your source data's actual timestamp convention — see the timezone section above. |
