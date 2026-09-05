# Task 60 — FPRC_V1 Implementation Freeze

## Outcome

- Implementation: **PASS**
- Current-candidate zero-drift: **PASS**
- FPRC_V1 state isolation: **PASS**
- Historical validation started: **NO**
- Deployment: `MONDAY_DECISION_SHADOW_ONLY`; no capital or production change
- Base: `af3bc97d47b3216f053a09fce533f51509b0c695`
- Frozen implementation fingerprint: `be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64`

## Frozen implementation

`talonx_quant/fprc_v1.py` is a separate completed-bar state machine and
`talonx_quant/fprc_v1_shadow.py` is its no-broker shadow/research execution
controller. Neither module is imported by the current candidate. The implementation freezes:

- causal America/New_York regular-session typical-price VWAP (`HLC3 * volume / volume`), reset each session;
- the exact 35-symbol universe declaration and the existing 09:30–09:45 / 15:30–16:00 entry blackouts;
- latest-price and completed-15m-close alignment above SMA200, with SMA200 non-declining versus four completed 15m bars earlier;
- two-or-more consecutive 1m closes below VWAP, local low through reclaim, first reclaim above VWAP and prior high, and exact immediate-next-bar persistence;
- one-cent minimum tick for this frozen liquid-US-equity universe, with stop one tick below the setup-local low and no profit target;
- first completed 5m close below VWAP scheduling `THESIS_FAILURE` at the next available 1m open, hard stop active from the entry bar, and mandatory 15:50 ET flatten;
- candidate-reference and actual-entry-fill 5bps feasibility at no more than 0.20R;
- cost-first ordering, then confirmation timestamp and ticker, maximum-three capacity, one position per symbol, 20-minute cooldown, and 75-minute post-loss lockout;
- RSI14, MACD(12,26,9), SMA10/50, relative volume, and frozen 15m/60m ATR readings as observational telemetry only;
- state-only pre-roll, long-only, completed bars, and next-symbol-bar-open fills.

The implementation is opt-in and paper-only. It has no broker, publisher, production configuration, or current-candidate integration.

## Causality, isolation, and parity evidence

Twelve focused synthetic tests cover the complete pullback/reclaim/confirmation sequence, no grace period,
next-open actual-fill rejection, same-entry-bar stop-first handling, next-open 5m thesis exit, no target,
cost formulas, cost-first capacity, cooldown/loss-lockout/session flatten behavior, state-only pre-roll,
telemetry invariance, independent state namespaces, and identical shadow/research adapter behavior.

The base/current Git blob for `talonx_quant/strategy.py` is identical
(`37a06f69a43b112ddc103afa045586b20f31997d`), the existing strategy fingerprint remains
`2ae6216bca70`, and `git diff` from the base is empty for the existing strategy, indicators,
consumer, config, backtest engine, and execution files. The reproducible freeze checker reports no current-candidate diff.

## Tests

- Focused: `12 passed`.
- Full suite: `1857 passed, 1 skipped, 15 xfailed, 1 failed` across all 1,874 collected tests.
- The sole failure is the untouched legacy fixture
  `tests/test_run_historical_regimes.py::test_real_end_to_end_run_against_the_sample_trade_dataset`:
  it expects one trade, while the unchanged base/current candidate generates one signal and rejects it as
  `LOW_CONFLUENCE`. It reproduces with normal Numba JIT and is independent of FPRC_V1; changing the fixture,
  current strategy, or configuration would violate Task 60's zero-drift boundary.
- The full suite used the repository-declared development dependencies and a Task60-local pytest temp root.
  `NUMBA_DISABLE_JIT=1` was used for the full run only to avoid an environment-specific pandas-ta/Numba import
  compilation loop; the sole failure reproduced separately with normal JIT.
- Import/compile checks and `git diff --check` passed. The freeze checker reproduced the fingerprint and zero-drift result.

No strategy replay, historical evaluation, signal generation from market data, data download, or independent validation occurred.
