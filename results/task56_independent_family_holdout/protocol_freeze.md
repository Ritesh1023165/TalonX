# Task 56 — Independent Family Holdout Validation Protocol Freeze

**Status:** `FROZEN_PENDING_EXPLICIT_REPLAY_APPROVAL`
**Deployment:** `MONDAY_DECISION_SHADOW_ONLY`
**Capital:** none authorized

## Scientific question

Does the Task 55 RSI-positive/MACD-negative family direction reproduce on genuinely independent historical
evaluation data under the exact frozen Task 54 candidate?

This is a replication test, not tuning. No download or replay has started.

## Prior-window exclusions

The full machine-readable calendar is in `exclusion_calendar.csv`. Evaluation dates used by Tasks 37/38/41
(development/calibration), Tasks 46/52/53 (validation), and Task 54 (validation) are excluded. Task 53 and
Task 54 pre-roll dates are inventoried separately because pre-roll creates market state only and produces no
candidates, rejections, signals, trades, cooldowns, or economics.

## Outcome-blind selection rule

The selection used only the 251 ET-localized trading dates in the local full-year AAPL Alpaca file
(2025-08-15 through 2026-08-14):

1. Mark all 105 dates previously used for development or evaluation as excluded.
2. Enumerate starts with 20 consecutive unused evaluation dates and 10 preceding trading dates.
3. Target evaluation centers at 1/6, 1/2, and 5/6 of the calendar.
4. Choose the nearest eligible start to each target; the earlier start wins a tie.

There were 17 eligible start indices, clustered at 92–100, 130, and 205–211. The frozen starts are 92, 130,
and 205. No price, signal, trade, or P&L outcome from a proposed evaluation date was inspected.

A stricter rule requiring the warmup as well as the evaluation to avoid every prior development/evaluation
date leaves zero eligible 30-day packages. Therefore evaluation independence is frozen, while some pre-roll
dates may be reused strictly through Task 53's proven state-only warmup path.

## Frozen holdout windows

| Window | State-only pre-roll | Independent evaluation | Evaluation days |
|---|---|---|---:|
| H1_early | 2025-12-11–2025-12-24 | 2025-12-26–2026-01-26 | 20 |
| H2_middle | 2026-02-06–2026-02-20 | 2026-02-23–2026-03-20 | 20 |
| H3_late | 2026-05-27–2026-06-09 | 2026-06-10–2026-07-09 | 20 |

The evaluation windows are mutually disjoint and do not overlap any prior development or evaluation window.

## Frozen candidate

- Strategy fingerprint: `2ae6216bca70`
- Quant config hash: `fdf4922d0728`
- Backtest config hash: `0c7dd13d75c4`
- `MULTITIMEFRAME_EXPERIMENTAL` volatility
- `INDEPENDENT_CONFIRMATION_EXPERIMENTAL`
- 15-minute threshold 0.329%; 60-minute threshold 0.839%
- 10-trading-day causal pre-roll
- `LONG_ONLY`
- Existing RSI/MACD/MA parameters, trend gate, structural-primary stop, ATR fallback, R:R,
  sessions/blackouts, cooldown/loss-lockout/throttle, and execution/cost assumptions

No family disabling, parameter sweep, symbol tuning, or cost tuning is authorized. The protected production
strategy/config files remain out of scope.

## Frozen hypotheses

Primary comparative replication hypotheses:

- H1: RSI gross expectancy > MACD gross expectancy.
- H2: RSI 5bps expectancy > MACD 5bps expectancy.

Separate absolute-edge questions, which must not be conflated with replication:

- Is RSI gross expectancy > 0?
- Is RSI 5bps expectancy > 0?
- Is MACD gross expectancy < 0?
- Is MACD 5bps expectancy < 0?

## Frozen classification

Exactly one final classification is permitted:

- `FAMILY_EFFECT_REPLICATED`: H1 and H2 hold; the interpretability floor passes; the direction appears in at
  least two of three windows at both costs, survives common-symbol support and removal of RSI's top three
  winners, and is not confined to one symbol.
- `FAMILY_EFFECT_WEAKENED`: direction partially repeats, but one comparative hypothesis or an important
  robustness condition fails.
- `FAMILY_EFFECT_NOT_REPLICATED`: independent results materially reverse or contradict the Task 55 direction.
- `INCONCLUSIVE_TOO_THIN`: sample or family coverage cannot discriminate the hypotheses.
- `VALIDATION_BLOCKED`: data, readiness, correctness, or reproducibility prevents a valid evaluation.

The prespecified interpretability floor is at least 60 combined RSI/MACD trades, at least 20 per family, and
each family appearing in at least two windows and five symbols. Replication does not prove RSI profitable and
does not authorize a family enable/disable action.

## Prespecified diagnostics

For RSI, MACD, and any observed MA activity, report N, wins/losses, gross total/expectancy/PF, 5bps
total/expectancy/PF, window consistency, symbol breadth, common-symbol support, time of day, exit path,
holding duration, top-1/top-3/top-5 winner sensitivity, worst-loser sensitivity, cost-in-R burden, and
stop-risk percentage geometry. Task 55's controls are prespecified replication diagnostics; no new filter may
be introduced after outcomes are observed.

## Local coverage and readiness feasibility

The original 10 symbols have full local coverage for all three 10+20-day packages. Their row counts are:

| Window | Warmup rows | Evaluation rows | Trading-date coverage |
|---|---:|---:|---|
| H1_early | 69,530 | 145,307 | 10/10 warmup and 20/20 evaluation days for all 10 |
| H2_middle | 76,031 | 147,010 | 10/10 warmup and 20/20 evaluation days for all 10 |
| H3_late | 81,546 | 160,139 | 10/10 warmup and 20/20 evaluation days for all 10 |

Existing local slices provide all 35 warmups. A state-only preload confirmed 35/35 symbols ready in every
window. Each passed the direct dependency thresholds: at least 120 1-minute bars, 200 completed 15-minute
bars, and more than 14 completed 60-minute bars. Minimum retained observations were 200/210/60 respectively.

The additional 25 symbols lack complete evaluation packages. After explicit approval, the reproducible plan
is 75 fresh Alpaca requests covering the entire warmup+evaluation range for each window:

- H1_early: 2025-12-11–2026-01-26
- H2_middle: 2026-02-06–2026-03-20
- H3_late: 2026-05-27–2026-07-09

The original 10 require no download. Before replay, all requests must be `FULL`, 35/35 symbols must pass data
quality and first-evaluation-bar readiness, and dataset hashes must be recorded.

## Expected workload

- Warmup: 611,975 bars
- Evaluation: approximately 1,219,322 bars
- Total: approximately 1,831,297 bars
- Candidate-only runtime estimate: 287.8 minutes (4.8 hours); practical allowance 4.5–6 hours

## Planned implementation and outputs after approval

The replay driver will be `research/scripts/task56_independent_family_holdout.py`, with protocol tests in
`tests/test_task56_independent_family_holdout.py`. Market data will live under
`data/historical_1m/task56_independent_family_holdout/{H1_early,H2_middle,H3_late}/`. Results will include
data quality/readiness, funnel, family/window/symbol/common-support/time/exit/holding/outlier/cost tables,
raw replay evidence, summary JSON/Markdown, and the final conclusion.

The Task 54 replay driver was not preserved as a committed script, so Task 56 must reconstruct that workflow
and verify all three frozen fingerprints before any expensive replay.

## Stop condition

Do not download or launch the multi-hour replay without explicit approval of this frozen protocol. No capital;
deployment remains `MONDAY_DECISION_SHADOW_ONLY`.
