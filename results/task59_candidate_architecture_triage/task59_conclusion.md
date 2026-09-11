# Task 59 Conclusion

`REDESIGN_SIGNAL_ARCHITECTURE`

The current experimental candidate is technically correct but economically unsupported. Across 228 trades it
produced only +0.092R gross expectancy and -0.324R at 5bps; MACD was gross-negative, MA produced no trades,
and RSI's prior payoff depended heavily on a concentrated winner tail that did not repeat independently.
Execution friction is material, but reasonable-cost trades also fail to establish robust gross edge.

Retain the causal data, execution, risk-control, and diagnostic infrastructure. Do not retain the current
indicator-family entry architecture. The sole proposed successor is the preregistered
`FAILED_PULLBACK_RECLAIM_CONTINUATION_V1`, a sequential price-reclaim continuation hypothesis with setup-local
invalidation and explicit cost feasibility. It is specification-only: no implementation, replay, capital, or
production change is authorized.

Deployment remains `MONDAY_DECISION_SHADOW_ONLY`.
