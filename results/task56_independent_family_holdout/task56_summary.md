# Task 56 — Independent Family Holdout Validation (resumed)

**Classification:** `FAMILY_EFFECT_WEAKENED`

This completed run resumed the exact protocol frozen at `8de8d49` after the earlier infrastructure-only `VALIDATION_BLOCKED` attempt. The earlier blocker remains historical evidence and is not interpreted as a strategy result.

## Family results

| Family | Trades | W/L | Gross total R | Gross expectancy | Gross PF | 5bps total R | 5bps expectancy | 5bps PF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| RSI | 44 | 15/28 | 0.723 | 0.016 | 1.033 | -10.544 | -0.240 | 0.650 |
| MACD | 61 | 19/42 | -1.258 | -0.021 | 0.966 | -26.058 | -0.427 | 0.542 |

## Comparative replication vs absolute edge

RSI exceeded MACD in 2/3 windows gross and 2/3 windows at 5bps. Common-symbol support: False. RSI top-three-winner removal comparative survival: False.

Absolute edge: RSI gross positive=True, RSI 5bps positive=False; MACD gross negative=True, MACD 5bps negative=True. Comparative replication does not make RSI production-ready.

## Interpretability and deployment

Interpretability floor: PASS. MA trades: 0. Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; no capital or family enable/disable action is authorized.

## Correctness

Replay integrity checks found zero duplicate trade IDs, non-bullish trades, timestamp-order violations,
invalid stop/target geometry, or sub-1.5 screening R:R trades. The focused execution/data/reproducibility
regression suite passed 71/71 tests.
