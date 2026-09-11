# Task 58 — RSI Winner-Magnitude / Payoff Regime Diagnostic

**Final classification:** `PRIOR_WINNERS_CONCENTRATED`

Read-only analysis of committed Task 53/54/56 RSI trades and already-downloaded Alpaca bars. No replay, download, signal generation, tuning, filter, or production change occurred.

## Payoff change

Tasks 53+54: 56 RSI trades, gross expectancy +0.621R, win rate 33.9%, mean winner 3.778R, 2R+ rate 17.9%, 4R+ rate 10.7%.
Task 56: 44 RSI trades, gross expectancy +0.016R, win rate 34.1%, mean winner 1.507R, 2R+ rate 11.4%, 4R+ rate 2.3%.
The expectancy change decomposes into frequency +0.030R, winner-size -0.774R, and loser-size +0.139R per trade; winner magnitude is dominant.

## Excursion and regime evidence

Among winners, median canonical MFE fell from 4.240R to 2.200R; median realized/MFE stayed similar at 0.708 versus 0.718. Median 60-minute forward favorable excursion changed from 1.551R to 0.717R.
Median accepted 15m ATR% moved 0.807% to 0.655%; 60m ATR% 1.223% to 1.080%. All entries retain the engine's existing trend-aligned and regime semantics; no new indicator contract was invented.

## Robustness and interpretation

Prior 2R+ winners appeared across 2 tasks, 4 task/windows, and 8 symbols; the largest symbol supplied only 21.9% of prior 2R+ R, but W3 plus Z_late supplied 75.4%. Removing the top three prior winners cuts expectancy from +0.621R to +0.058R, close to Task56's +0.016R. Leave-one-symbol-out results remain descriptive and authorize no exclusion.
The prior payoff tail was concentrated in a few high-continuation windows/trades, while Task56 lacked comparable 4R+ continuation. Higher accepted volatility is only tentative context because its separation did not reproduce in Task53. No regime rule or new edge is established.

Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; strategy action: **NONE**.
