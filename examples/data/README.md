# DETERMINISTIC TEST DATA — NOT MARKET DATA

`sample_AAPL_1m.csv` is a synthetically generated 1-minute OHLCV series
(780 rows, two "trading days" of regular-session bars). It does **not**
represent real AAPL price action or any real market performance.

**Purpose:** verify your `talonx_backtest` installation end to end
without needing real historical data —

```
clone repository
    ↓
run sample backtest
    ↓
verify installation
    ↓
verify report generation
```

**Do not** draw any conclusion about the TalonX strategy's real-world
performance from this dataset. It exists purely to prove the pipeline
(data loading → data-quality validation → strategy evaluation → trade
simulation → report generation) works on your machine.

## Format

Timestamps in this file are **naive** (no timezone suffix) and
represent **America/New_York local time** (the file starts at
`2025-01-02 09:30:00`, the US equities regular-session open). Run it
with `--tz America/New_York` — see [`docs/backtesting.md`](../../docs/backtesting.md)
for why that flag matters.

## Regenerating this file

Generated deterministically (fixed seed price, fixed arithmetic pattern
— no randomness) by a short script; see `docs/backtesting.md`'s
"Sample data" section for the generation logic if you need to
regenerate or extend it.
