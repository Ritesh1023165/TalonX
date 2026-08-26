# Task75A Part 3 -- Canonical Market-Calendar Correction

**Problem:** Task74B's `family_b_multiday.py` indexed each symbol's OWN
available daily-bar sequence positionally (`iloc[i+1]` for Day1). A
symbol-specific data gap could silently shift its Day1/exit to a later
true calendar date than other symbols, without ever being flagged.

**V1 policy:** Day0/Day1/exit are positions in SPY's own canonical
trading-day calendar. A symbol must have a valid session on EVERY
required canonical day between Day0 and the exit day; if any is
missing, the row is REJECTED (`SYMBOL_MISSING_REQUIRED_SESSION`) --
never shifted, never filled/synthesized.

## Impact audit (DEVELOPMENT data only, no new download, no 2024 read)

Compared every symbol's trading-day set against SPY's, per slice:

| Slice | SPY days | Symbols with any mismatch |
|---|---|---|
| 2026 Q3 (F6 era) | 63 | 0 |
| 2025 Q1 (ORPB era) | 29 | 0 |
| 2025 Q3 (FPRC era) | 28 | 0 |
| 2025 Q4 (Task46-56 era) | 29 | 0 |

**Zero mismatches across all 35 symbols in all 4 slices.** The old and
new methods are mathematically identical on this data --
**the Task74B nomination is unchanged; development population NOT
materially changed.**

The correction is still made mandatory for V1 going forward: this only
confirms the (very clean) DEVELOPMENT data, not the not-yet-inspected
2024 validation/replication data, which could plausibly contain a real
gap.

Additional frozen semantics: America/New_York timezone throughout, one
signal per symbol per decision day, holidays/half-days governed
entirely by SPY's own session list, duplicate/out-of-order bars
rejected upstream by the existing data-quality gate, minimum 10 valid
symbols required for a day's cross-sectional rank to be computed at
all.
