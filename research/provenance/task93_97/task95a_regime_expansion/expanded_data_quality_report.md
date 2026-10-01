# TASK 95A — Phase 5 — Expanded Data Quality Report

**Dataset:** `task95a_expanded_v1` — 35 symbols, **25,806,723 bars** (19,585,109 regular-session),
2020-01-01 → 2026-08-14, Alpaca **SIP** feed, `adjustment=raw` (unadjusted), extended hours, UTC
tz-aware. Fingerprint `sha256 8333c1001e28ee18…` (`expanded_dataset_manifest.json`). Machine audit:
`_quality_audit.json`.

## Structural integrity — Task 93 check battery, all 35 symbols

| Check | Result | Class |
|---|---|---|
| Duplicate timestamps | **0** / 25.8M | EXPECTED (clean) |
| Out-of-order timestamps | **0** | EXPECTED |
| Invalid OHLC relations (`h<l`, `h<o`, `h<c`, `l>o`, `l>c`) | **0** | EXPECTED |
| Non-positive prices (`<= 0`) | **0** | EXPECTED |
| Negative volume | **0** | EXPECTED |
| NaN in OHLCV | **0** | EXPECTED |
| Infinite values in OHLCV | **0** | EXPECTED |
| Session alignment (bars inside 04:00–20:00 ET window) | ✓ per-symbol `frac_in_extended_window` reported | EXPECTED |
| Benign intra-session gaps (Alpaca omits zero-volume minutes) | present, same pattern as Task 93 / Task 26 | EXPECTED |

**No BLOCKING issue. No MATERIAL_NONBLOCKING issue.** The expanded dataset is at least as clean as
Task 93's canonical set.

## Cross-year checks

### DST
The 09:30-ET session-open bar carries exactly **two** UTC offsets across the whole 6.6-year sample:
`-04:00` (EDT) and `-05:00` (EST). No third offset, no mis-localized bars — DST handling is correct
across all seven spring/fall transitions in range. Session classification is done by the engine in
`America/New_York`, unchanged from Task 93.

### Stock splits (unadjusted data → single-bar step on the split date)
21 consecutive-regular-bar moves > 20% were detected. **11 are known stock splits** (unadjusted
prices step at the ex-date open):

| Symbol | Split date (ET) | Step | Ratio |
|---|---|---:|---|
| AAPL | 2020-08-31 | −74.5% | 4-for-1 |
| TSLA | 2020-08-31 | −80.0% | 5-for-1 |
| NVDA | 2021-07-20 | −75.2% | 4-for-1 |
| ISRG | 2021-10-05 | −66.3% | 3-for-1 |
| AMZN | 2022-06-06 | −94.9% | 20-for-1 |
| GOOGL | 2022-07-18 | −95.0% | 20-for-1 |
| TSLA | 2022-08-25 | −66.1% | 3-for-1 |
| PANW | 2022-09-14 | −66.6% | 3-for-1 |
| NVDA | 2024-06-10 | −90.1% | 10-for-1 |
| AVGO | 2024-07-15 | −89.9% | 10-for-1 |
| LRCX | 2024-10-03 | −90.2% | 10-for-1 |

**Handling:** intraday forward-return features (`fwd_5m/15m/30m/60m`, `fwd_eod`) are computed as
*within-continuous-series* percentage changes; a split step falls between the split date's prior-day
last bar and that day's first bar, so it can only contaminate forward-return values that *span that
one boundary* (≈ the last ≤ 60 regular bars of the pre-split day). The feature builder additionally
**nulls all forward returns on the split-date session** for the six largest-cap splits; the remaining
five affect ≈ 300 forward-return rows out of 19.6M (< 0.002%) and are classified **MINOR**. Any
candidate that survived to promotion would be re-tested with every split-date session excluded — moot
given the outcome (§ FINAL_REPORT).

### Large earnings / news gaps (real moves, not corruption)
The other **10** > 20% moves are genuine overnight repricings: META −25% (2022-02-03) and −24%
(2022-10-27), NFLX −21% (2022-01-21) and −29% (2022-04-20), PYPL −22% (2022-02-02), NVDA +24%
(2023-05-25, AI guidance), INTC −26% (2024-08-02), PANW (2024-02-21, 2024-12-16), AMD +34% (2025-10-06,
OpenAI deal). These are **EXPECTED** — real market data from the exact bear/high-volatility regime
Task 95A set out to capture. They are left unmodified (a `1.5×ATR` breach stop caps their downside
contribution to −1 R in the event-study model regardless).

### Listings / delistings
All 35 symbols traded continuously before 2020-01-01 (no IPOs inside the window); none delisted.
Per-symbol `bars_by_year` in `_quality_audit.json` shows every symbol present in every year 2020–2025
(the 25 non-deep names stop 2025-08-14 by design — see `target_history_spec.md`, COMMON_UNIVERSE).
No impossible pre-listing history was fetched or backfilled.

## Seam verification (2025-01-24 splice boundary)

The dataset is `_raw_expanded/` (this task, 2020-01-01 → 2025-01-23) + Task 93 canonical
(2025-01-24 → 2026-08-14). To confirm the splice introduces no discontinuity, 2025-01-24 → 2025-01-31
was **re-fetched fresh** for 5 probe symbols and compared bar-for-bar against the Task 93 canonical
slice (`_seam_check.json`):

| Symbol | Canonical bars | Fresh bars | Matched | Max abs diff (O/H/L/C/V) |
|---|---:|---:|---:|---:|
| AAPL | 5,155 | 5,155 | 5,155 | **0.0** |
| NVDA | 5,754 | 5,754 | 5,754 | **0.0** |
| STX | 2,405 | 2,405 | 2,405 | **0.0** |
| TSLA | 5,598 | 5,598 | 5,598 | **0.0** |
| PYPL | 2,917 | 2,917 | 2,917 | **0.0** |

**Byte-identical.** Alpaca SIP `adjustment=raw` is deterministic and the acquisition path
(`download_historical_1m.py`) is the same one that built Task 93's canonical set → no feed/provider/
adjustment seam.

## Classification summary

| Class | Findings |
|---|---|
| BLOCKING | **none** |
| MATERIAL_NONBLOCKING | **none** |
| MINOR | 5 non-mega-cap split dates not day-nulled by the feature builder (≈ 300 / 19.6M forward-return rows); left in and documented |
| EXPECTED | 0 dup / 0 OOO / 0 invalid OHLC / 0 bad price / 0 bad volume / 0 NaN / 0 Inf; benign zero-volume-minute gaps; 2 DST offsets; 11 split steps; 10 real earnings gaps |

**Verdict: the expanded dataset is fit for the Phase 8–13 event studies.** No alpha study is run over
materially contaminated data.
