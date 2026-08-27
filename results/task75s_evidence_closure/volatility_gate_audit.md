# Task 75S — Stage 4: LOW_VOLATILITY Gate Correctness Audit

**No threshold, formula, or code was changed. This is a read-only audit plus deterministic boundary
tests using the existing, unmodified functions.**

## Formula and documented intended rule
`talonx_quant/consumer.py::_fails_min_volatility` (read-only inspection):
```
atr_pct = (snapshot.atr / snapshot.price) * 100
return atr_pct < config.min_atr_pct
```
Documented intent (the function's own docstring): filter out low-beta/income names whose ATR-scaled
range is too small to ever reach a stop/target -- deliberately does NOT fail-closed on missing ATR
(warm-up), since every downstream RSI/MACD/MA trigger check already requires ATR independently
(`_clears_atr_move`), so an unwarmed symbol produces zero signals regardless of this gate's answer.

## Units
`snapshot.atr` and `snapshot.price` are both raw price units (dollars); `atr_pct` is a **percentage**
(ATR as % of price, e.g. ATR=$0.50 on a $200 stock → `atr_pct=0.25`). `config.min_atr_pct` (default
**0.25**) is stated in the SAME percentage units -- confirmed by the shared literal comparison and by
`task74s_10symbol_full_research_volatility_telemetry.csv`'s own `volatility_threshold` column, which
records `0.25` for every row alongside `atr_pct` values in the same 0-few-percent range. No
fraction-vs-percentage unit mismatch exists.

## Indicator timeframe / input provenance
ATR(14) computed by `talonx_quant/indicators.py::compute_indicators` on the same 1-minute bar stream
the strategy operates on (not a different timeframe) -- confirmed by `_fails_min_volatility` taking the
already-computed `IndicatorSnapshot.atr` field directly, with no independent recomputation. This is the
SAME snapshot object used for every other 1-minute-timeframe check (RSI/MACD), so there is no
timeframe mismatch between the volatility gate and the rest of the strategy.

## Provider/feed and adjustment settings
Data provenance for this evaluation: Alpaca, SIP feed (per `data_manifest.csv`) -- unchanged and
unrelated to this gate's own logic (the gate operates purely on already-loaded OHLCV bars regardless
of provider). No adjustment/split/dividend handling is performed anywhere in this pipeline for either
live or backtest (out of scope for this gate specifically).

## Threshold source
`config.min_atr_pct` = `_env_float("TALONX_QUANT_MIN_ATR_PCT", 0.25)` (`talonx_quant/config.py:355`) --
a configurable, environment-overridable default of 0.25, unchanged by this or Task 74S's work
(confirmed via `git diff 848de0d..HEAD -- talonx_quant/config.py`, empty).

## Boundary comparison semantics
Strict less-than (`atr_pct < config.min_atr_pct`): a bar with `atr_pct` **exactly equal to** the
threshold **passes** (does not fail) the gate -- confirmed two ways (see `boundary_test_results.txt`):
1. **Real production telemetry** (1,901,855 rows, unmodified): nearest real rows just below 0.25
   (0.245001-0.245004) are all `passes_volatility=False`; nearest real rows just above
   (0.254997-0.254999) are all `passes_volatility=True`. Consistent with the code's own comparison.
2. **Direct, labeled synthetic check** (`TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE`) calling
   `_fails_min_volatility` directly at `atr_pct` values of 0.2449 (below), exactly 0.25, and 0.2501
   (above): results `True, False, False` -- exactly matching the documented semantics, including the
   exact-boundary case no real row happened to land on.

## NaN / missing-input handling
`if snapshot.atr is None or not snapshot.price: return False` -- missing ATR (warm-up) or a
falsy/zero price does **not** fail this specific gate (returns "does not fail," i.e., lets the bar
continue toward the strategy's own signal checks, which independently require ATR and will produce no
signal anyway during warm-up). This is a deliberate, documented design choice, not an oversight --
confirmed consistent with `talonx_quant/indicators.py::compute_indicators` returning `None` outright
during warm-up (both live and backtest paths already fail closed one layer up, at signal generation).

## Production/replay agreement
`talonx_backtest/engine.py` imports `_fails_min_volatility` **directly** from `talonx_quant.consumer`
(line 103) -- the same function object, not a reimplementation or copy. Agreement is guaranteed by
construction, not merely by testing.

## Verdict
**No implementation/specification mismatch found.** The gate behaves exactly as documented, at and
around its threshold, in both real production telemetry and direct synthetic verification. The very
high (93.63%) bar-level rejection rate observed in Task 74S is **not, by itself, evidence of a
defect** -- it reflects the threshold's own strictness applied correctly and consistently across
1,903,044 bars, not an implementation error. This audit does not recommend lowering the threshold to
produce more trades.
