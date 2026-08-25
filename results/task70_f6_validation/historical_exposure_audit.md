# Task70 Historical Exposure Audit

Built on top of Task 67A's own systematic, pre-F6, ledger-wide exposure audit
(`results/task67a_phenomenon_discovery/exposure_boundary_audit.json`), which
already concluded pre-2025-01-24 was the only genuinely untouched territory.
This task verifies that conclusion still holds and resolves two loose ends
that audit surfaced but did not fully chase down.

## F6 lineage (confirmed, not re-derived)

Task67A (Stage 0 data-split contract, declared 2026-08-24 **before any Stage 1
result existed**) → Task67B family screening (development dataset only,
2026-05-15..2026-08-14, 735 events) → Task68A freeze (`f6_fade_v1_spec.json`'s
`development_period` and `development_dataset_identity_or_hash` match that
dataset exactly). F6's threshold was derived **solely** from this window —
confirmed by direct inspection of the spec and family_06 summary files, not
assumed.

## What's new in this audit vs. Task67A's

Task67A's audit found two scripts (`task61r_freeze_temporal_protocol.py`,
`task62_freeze_candidate.py`) referencing the literal string `"2024-01-01"`
but didn't fully resolve what that meant. Direct read of both scripts:
**pure trading-calendar session-date arithmetic** (`exchange_calendars`), used
only to build a long-enough backward-indexable list from which the real
20/60-session evaluation windows are sliced — those windows land entirely in
2025. Zero price data, zero strategy outcome, ever touches 2024 here. This is
strictly *less* exposure than the "EXPOSED_DATA_ONLY" tier — it's calendar
metadata only.

Also newly investigated: `docs/backtesting.md` and `scripts/run_historical_
regimes.py` reference 2024 date ranges as generic backtest-tool documentation/
example configuration (`bull_momentum_2024`, `high_vol_pullback_2024`,
`full_period_2024_2026`). Traced to the `talonx_backtest` engine's founding
commit (2026-08-16) — a general-purpose replay tool for the **current
production momentum/RSI/MACD strategy** (structurally unrelated to F6's fade
logic). No committed evidence anywhere shows this tool actually executed
against real full 2024 data with genuine trade-level results — the only
figures shown are a **data-quality report** (row/gap counts), not a strategy
outcome. Classified conservatively as `EXPOSED_DATA_ONLY` rather than
`CLEAN_UNSEEN`, since I cannot rule out with 100% certainty that the example
numbers derive from some unrecorded real run — but this satisfies all three
conditions the task allows `EXPOSED_DATA_ONLY` for: no strategy outcome was
ever shown, F6's design (independently built entirely from 2026-05-15..08-14
data) could not have been informed by it, and the period is locked (see
`holdout_selection_lock.json`) before any F6 outcome is computed against it.

## Period classification table

| Period | Classification |
|---|---|
| before 2024-01-01 | CLEAN_UNSEEN |
| **2024-01-01 → 2024-12-31** | **EXPOSED_DATA_ONLY** (selected for VALIDATION/REPLICATION) |
| 2025-01-01 → 2025-01-23 | CLEAN_UNSEEN |
| 2025-01-24 → 2025-05-05 | OUTCOME_CONTAMINATED (ORPB_V1) |
| 2025-05-06 → 2025-08-14 | OUTCOME_CONTAMINATED (FPRC_V1) |
| 2025-08-15 → 2026-08-14 | OUTCOME_CONTAMINATED (production momentum strategy, extensively) |
| 2026-05-15 → 2026-08-14 | OUTCOME_CONTAMINATED_FOR_F6 (F6's own development window) |
| 2026-08-15 → 2026-08-24 | OUTCOME_CONTAMINATED (live shadow + live PIV session) |
| 2026-08-25 onward | UNAVAILABLE_NOT_YET_TRADED (today; pre-existing forward-reserved plan can't be materialized) |

No `UNKNOWN` classification was used anywhere.

## Conclusion

2024 is the defensible unseen window. Live Alpaca SIP data availability for
2024 was independently confirmed (read-only API check, AAPL, two sample
weeks, HTTP 200, 5000+ bars each) — a data-availability check, not an outcome
check, per the task's own allowed pre-lock selection factors. See
`holdout_selection_lock.json` for the exact VALIDATION/REPLICATION windows
selected within 2024.
