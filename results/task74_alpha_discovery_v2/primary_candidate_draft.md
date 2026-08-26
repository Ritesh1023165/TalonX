# Task74B -- Primary Candidate Draft (NOT frozen, NOT validated)

## CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION

**State: PRIMARY_CANDIDATE_READY_TO_FREEZE**

**Mechanism:** On Day0 close, rank each universe symbol's market-adjusted
3-trading-day cumulative return (stock minus SPY, same window) cross-
sectionally. Symbols in the top 10-20% (extreme past outperformers) are
SHORTed at Day1 open, held for a fixed 2/3/5-trading-day horizon, and
exited at that day's close.

**Direction: SHORT_ONLY.** The mirror LONG side (extreme losers,
betting on a bounce) is materially weaker and does not corroborate --
disclosed honestly as a known weakness, not hidden by pooling.

**Recommended anchor cell:** loose band (top/bottom 20%), 3-day horizon
-- 1000 trades, 35 symbols, 125 distinct days, gross +0.607%, net@10bps
**+0.507%**, net@15bps +0.457%, net@20bps +0.407%, PF@10bps 1.305,
friction absorption ratio 6.07x. The ONLY cell where both the symbol-
cluster CI [0.068, 1.271] and the day-cluster CI [0.034, 1.201] exclude
zero.

**Why this clears the (stricter) Task74B promotion bar:**
net@10bps required >=0.15% -- achieved 0.507% (3.4x the bar). Friction
absorption required >=2.5x -- achieved 6.07x. Preferred net@15bps
>=0.10% -- achieved 0.457%. Positive at 20bps -- achieved 0.407%.

**Robustness:** all 6 predeclared cells (2 bands x 3 horizons) share the
same sign -- a genuine plateau. Removing the 5 best trades or the best 3
days never flips the expectancy negative (+0.129% and +0.223%
respectively) -- a materially stronger outlier-robustness result than
the rejected residual-momentum candidate, which DID flip negative under
the identical test.

**Known weaknesses (disclosed, not hidden):**
- SHORT-only; no symmetric LONG counterpart.
- 1 of 4 development regimes (2025 Q3, FPRC era) is negative.
- EARLY time segment is slightly negative; edge concentrates in
  MIDDLE/LATE.
- Stop is `STOP_UNRESOLVED` -- MAE/MFE recorded for a future freeze,
  not chosen here.
- SIP-vs-IEX daily-price parity at the rank-threshold boundary is
  unverified.
- Genuinely new mechanism -- no live precedent in this codebase.

**Horizon product mapping: MULTI_DAY** (not intraday -- must not be
relabeled).

**Not frozen, not validated, not integrated. Runtime untouched.**

**Next task:** freeze exact parameters + a DEVELOPMENT-only stop rule +
pre-register a validation protocol (with explicit day-cluster emphasis,
mirroring the residual-momentum candidate's own lesson) + lock a
genuinely untouched holdout, then validate exactly once.
