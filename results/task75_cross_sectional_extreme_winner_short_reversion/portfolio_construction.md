# Task75A Part 5 -- Portfolio Construction

- **Sizing:** equal notional per position (research-only, no real capital)
- **Per-position allocation:** 5% of reference capital
- **Max concurrent positions:** 20
- **Max gross short exposure:** 100% of reference capital
- **Max per-symbol exposure:** 1 open position per symbol at a time
  (no pyramiding, no re-shorting an already-short symbol)
- **Overlapping cohorts:** expected and normal (rolling daily entries,
  3-day holds) -- bounded by the capacity rule, not left unbounded

**Capacity-constrained selection (deterministic):** if qualifying new
signals + already-open positions would exceed 20, rank new signals by
Day0 cross-sectional rank percentile descending (most extreme first)
and admit until capacity is reached; excess signals are rejected
(`CAPACITY_EXCEEDED`), never partially sized or queued.

**Portfolio kill-switch:** NOT defined for V1 -- explicitly recorded as
a gap for a future PAPER-integration task (after validation AND
replication both pass), not a DEVELOPMENT-freeze concern. Task75B's
validation reports portfolio-level statistics with no kill-switch
intervention (the conservative assumption).
