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

## Run the sample backtest first

Before getting real data, prove the whole pipeline works on your
machine using the deterministic sample dataset checked into the repo:

```powershell
python -m talonx_backtest --data examples\data\sample_AAPL_1m.csv --symbol AAPL --tz America/New_York --out results\sample
```

Then open:

```text
results\sample\backtest_results.html
```

in any browser. **`examples/data/sample_AAPL_1m.csv` is synthetic,
deterministic test data — see [`examples/data/README.md`](../examples/data/README.md).
It does NOT represent real market performance.** Its only job is to
prove data loading, validation, strategy evaluation, trade simulation,
and report generation all work end to end before you invest time
sourcing real data.

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

`talonx_backtest` does not download data itself. Practical options:

- **A broker/data API you already have access to** (e.g. Alpaca,
  Interactive Brokers, Polygon.io, IEX Cloud) — most offer a 1-minute
  historical bars endpoint; export to CSV with the columns above.
- **`yfinance`** (already a project dependency, used elsewhere in
  `talonx_quant` for pre-seeding) — its 1-minute history is limited to
  roughly the trailing 7-30 days depending on the endpoint, which is
  enough for a short validation run but not a multi-year backtest.
- **A paid historical-data vendor** (e.g. Polygon.io's flat files,
  Databento, Tiingo) if you need a multi-year, survivorship-bias-aware
  1-minute dataset.

No specific provider is hard-coded into the engine, and the sample
dataset above needs no API key at all. Whatever the source, the
workflow is the same:

```text
Data provider
    ↓
Download
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
or a flat layout:
```text
data/
    AAPL.csv
    MSFT.csv
```

```powershell
python -m talonx_backtest --data data\ --symbols AAPL,MSFT --start 2024-01-01 --end 2025-12-31 --out results\multi
```

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

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ERROR / BACKTEST ABORTED` | Critical data corruption — read the printed detail, fix the source CSV. |
| `error: no rows loaded after filtering` | `--start`/`--end`/`--symbols` excluded everything, or the file is empty. |
| Zero trades, all `LOW_RISK_REWARD` rejections | The R:R gate needs at least one **completed prior trading session** in the data to derive pivot levels — feed multi-day data. |
| Zero trades, all `PREMARKET_LIQUIDITY` rejections | Expected for pre-market candidates — see "Extended hours" above. |
| Results look shifted by several hours | Check `--tz` against your source data's actual timestamp convention — see the timezone section above. |
