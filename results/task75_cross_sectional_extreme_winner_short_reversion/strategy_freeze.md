# Task75A Part 2 -- Frozen Strategy: CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION_V1

See `strategy_freeze.json` (the exact `research/task75_v1/contracts.py`
contract dict) for the machine-readable version.

- **Direction:** SHORT_ONLY -- no LONG leg, no MOMENTUM hypothesis
  implemented in V1 at all (Task74B's rejected code paths are preserved
  unmodified as historical evidence, not reused).
- **Universe:** the canonical 35-symbol TalonX universe + SPY, fixed.
- **Feature:** causal 3-trading-day cumulative close-to-close return,
  stock minus SPY, over identical canonical sessions.
- **Rank:** `pandas.Series.rank(pct=True, method="average")` --
  ties share the mean percentile rank.
- **Threshold:** top 20% (`rank >= 0.80`, inclusive boundary).
- **Minimum cross-sectional breadth:** 10 valid symbols/day, else the
  day is skipped entirely (never ranked on a degenerate small sample).
- **Decision:** Day0 close (session complete).
- **Entry:** the FIRST canonical SPY session strictly after Day0, at
  that session's regular-session OPEN. SHORT.
- **Exit:** close of the 3rd canonical session counting the entry day
  as day 1 (i.e. entry_day + 2 further canonical sessions).
- **Calendar:** SPY's own observed session list is the ONLY calendar
  ever indexed against (`calendar_session_contract.json`) -- a symbol
  missing any required session is rejected, never shifted or filled.
- **Timezone:** America/New_York throughout.
- **One signal per symbol per decision day.** Overlapping positions
  across symbols/entry-days are governed by `portfolio_construction.json`.
- **Missing-data/fail-closed:** explicit rejection reasons
  (`DATA_NOT_READY`, `INSUFFICIENT_CROSS_SECTIONAL_BREADTH`,
  `THRESHOLD_NOT_MET`, `SYMBOL_MISSING_REQUIRED_SESSION`,
  `SPY_CALENDAR_NOT_ESTABLISHED`) -- never a synthesized/filled bar.
- **Corporate actions:** raw/unadjusted data -- see
  `corporate_action_policy.json`; Task75B is BLOCKED pending a
  corporate-action-safe dataset.
- **Stop:** 15% catastrophic stop (`risk_policy.json`).
- **Costs:** 25bps primary all-in (`execution_cost_contract.json`), 0/5/10/15/20bps diagnostics retained.
- **Provider:** Alpaca SIP research / IEX live, parity unproven.

No development P&L optimization was performed at freeze time -- every
parameter was read directly from already-existing Task74B artifacts or
derived from a single pre-existing percentile diagnostic (the stop).
