# EVENT_RESPONSE_MAP_V1: design lock (Gate C)

**Status:** DESIGN_LOCKED, fingerprint `0b3799799c29802711c9ead7daeac5a91cf45fbeea1ecd7feee9ea982508e546` (locked 2026-10-01T00:18:20Z). **No price data exists** for this program at lock time.

| Item | Value |
|---|---|
| Machine-readable lock | `results/event_response_map_v1/design_lock.json`, which holds the fingerprint, per-file sha256, the full SPEC and the data plan |
| Branch / base | `research/event_response_map_v1`, based on `86f7375` (live branch head; the live branch itself is never checked out, committed to or pushed) |
| Single source of truth | `research/event_response_map_v1/spec.py`. Code: `data.py`, `universe.py`, `events.py`, `metrics.py`, `phase_d.py`. Shared code: `research/common/` |
| Verification | Phase D recomputes the fingerprint (`fingerprint.verify`) and the `candidates.json` sha256, and refuses to run on any mismatch |

The program is **discovery only.** Nothing it produces is validated. At most ONE hypothesis may later be nominated, and that one is then frozen and pre-registered in a separate task.

## 1. Periods and guard

**Development:** events dated 2019-01-02 to 2023-12-29. The data lookback starts 2018-11-01.

An event enters a horizon cell only if that horizon's exit session is on or before 2023-12-29. No bar from 2024 is ever needed.

The program's `LockedRangeGuard` (state file: `results/event_response_map_v1/guard_state.json`) locks:
- **YEAR_2024_EXCLUDED:** 2024-01-01 to 2024-12-31. This contains both Task75 reserved windows.
- **FUTURE_CONFIRMATION_2025_ONWARD:** 2025-01-02 onward, open-ended.

The guard is enforced at two layers:
- **DOWNLOAD:** before any request is built.
- **LOAD:** checks the range and also any interior rows.

The Task75 guard state is a different file on a different branch. This program has no transition method, and both properties are tested.

## 2. Universe (C1-UNIVERSE)

**Not survivorship-free.** No free source available to us is truly survivorship-free. The best available source is the union of four candidate sets:

| Source | What | Symbols |
|---|---|---|
| A | Alpaca `/v2/assets`, active **and inactive**: listed exchanges, symbol regex, and instrument-name rules from `talonx_premarket/universe.py` | 6,764 (5,618 active, 1,146 inactive) |
| B | Alpaca name changes 2019–2023: the **pre-rename** ticker | 1,454 |
| C | Alpaca cash/stock mergers 2019–2023: the **acquiree** ticker | 3,242 |
| D | Point-in-time S&P 500 (Task95F, fja05680/Wikipedia): any-day members 2019–2023 | 614 (37 found only here) |
| **Total (frozen)** | `candidates.json`, sha256 `a865fce2…e1f61c` (LF-normalized) | **10,772** |

**How delisted and renamed names enter:**
- **Delisted names** enter through A (inactive) when Alpaca still lists them. Otherwise they enter through C (acquirees) or D (former index members).
- **Renamed names** enter under the old ticker through B and the new ticker through A.
- **A symbol for which Alpaca returns no bars cannot enter.** Bar availability is measured in Phase D, step D0, per year.
- **Today's DTU or ELIGIBLE list is never used.**

**Coverage against a reference.** Metadata coverage (sources A, B and C) of the point-in-time S&P 500, with each year counting any member on any day of that year:

| Year | Members | Coverage | Missing |
|---|---|---|---|
| 2019 | 533 | 93.62 % | 34 |
| 2020 | 524 | 94.47 % | 29 |
| 2021 | 525 | 94.29 % | 30 |
| 2022 | 526 | 94.68 % | 28 |
| 2023 | 521 | 95.20 % | 25 |

- Names missing from Alpaca entirely include K, EA, IPG, HOLX, PXD, SIVB, DISCA and FLT. Source D adds them as candidates, but whether they have bars is unknown until D0.
- There is no free reference for smaller liquid names, so their coverage is presumed **no better**.
- 3,552 of the C/D-only symbols have no known name, so they are not instrument-filtered. They are counted in the integrity report.
- **All results are conditional on this universe.**

**CIK and SIC mapping:**
- Pre-rename tickers follow the rename chain first, because tickers get recycled.
- Otherwise the source is SEC `company_tickers.json`.
- Otherwise, a **unique** exact normalized-name match in `cik-lookup-data.txt` is used.
- A mapping is kept only if that CIK has at least one EDGAR filing dated in the development period.
- If there is no CIK, the symbol gets no 8-K events and its benchmark is SPY.

### Eligibility (point in time, D-1 only): **owner decision required**

The eligibility rule is close ≥ $5 and ADV20 ≥ $20M, using the 20 consecutive market sessions that end at D-1. Liquidity buckets:

| Bucket | ADV20 |
|---|---|
| L1 | $20M–100M |
| L2 | $100M–1B |
| L3 | > $1B |

**The problem.** With `adjustment=all`, historical prices are rescaled by **future** splits and dividends. The CA audit V2 on development 2019–2023 found 3,178 split and spin-off events (2,670 reverse splits). 898 of them fall on 772 candidate symbols. An adjusted $5 floor would therefore be look-ahead.

**The locked rule.** Eligibility uses **as-traded (adjustment=raw)** D-1 close and volume, for the eligibility test only. Raw values never feed returns, features or benchmarks. The download goes through the same single downloader module with `purpose=ELIGIBILITY_ONLY`. Benchmarks are refused raw.

**This deviates from "all downloads adjustment=all".** Phase D refuses to run without `--eligibility-raw-approved`. If you do not approve it, V1 is not run. A V1.1 lock would instead derive as-traded values from the all-adjusted bars plus corporate-action factors, and that lock would also be written before any data exists.

## 3. Data (C-DATA)

- **One downloader** (`data.py`) for everything: Alpaca SIP `1Day`, with equities, SPY, XLE, XBI, XLV, XLK, XLI and XLF all using identical parameters and `adjustment=all`.
- **Rate:** at most 37.5 requests per minute.
- **Off-hours only, enforced in code:** weekdays 13:00–20:30Z are refused for both Alpaca and SEC.
- **Archive:** gzip-archived response bytes plus a sha256 manifest. The archive is authoritative.
- **SEC sources:** EDGAR submissions JSON (items plus `acceptanceDateTime`), and Form 3/4/5 quarterly bulk files 2019Q1–2023Q4.

## 4. Events, entry, horizons

**13 event types** (dedup key: event type, symbol, entry session):

| Event type | Definition |
|---|---|
| GAP_UP / GAP_DOWN 3, 5, 10 | \|open_D / close_D-1 − 1\| at ≥ 3 %, 5 % or 10 % on ALL bars. The thresholds are **nested**. A gap is observable only at D's opening print, so **entry is the D+1 open** under the strict rule. |
| 8-K items 2.02, 1.01, 5.02, 7.01, 8.01 | Form 8-K only (8-K/A excluded). One cell per item. Filings outside the development period are dropped before any field is read. |
| FORM4_CLUSTER | The V2@1 `detect_episodes`, unchanged (task107a parser → `form4_source.from_rows`). Causal time is the end of the activation filing day. Labelled **KNOWN_UNSUPPORTED_BASELINE**: never nominatable. |
| NO_EVENT | Control. For each (entry date, bucket) with k event names, draw k eligible names of that bucket on that date that have no event within ±2 sessions. Seed 670067. Never nominatable. |

**8-K timing (CONSERVATIVE_DUAL_INTERPRETATION).** The causal time is the **later** of two readings of `acceptanceDateTime`: as UTC and as ET. EDGAR surfaces have been inconsistent about its zone, and the later reading is causal under either.

**Entry:** the OPEN of the first session whose 09:30 ET open is **strictly after** the causal instant. An event after 16:00 or on a non-session day therefore goes to the next session.

**Exits:** the close of entry+0, +1, +3, +5 and +10 sessions. The SHORT direction is a sign-flipped research reference.

## 5. Metrics, costs, screen

**Metrics per cell:**
- n, distinct dates, distinct symbols;
- mean and median raw return;
- mean SPY-relative and sector-relative return (SIC_ETF_MAP_V1);
- hit rate and standard deviation;
- date-cluster bootstrap CI (`research.common.research_stats.bootstrap_ci_clustered`, byte-identical; group is the entry date; 10,000 resamples; 95 %; seed 670067);
- the mean after removing the top 1, 3 and 5;
- per-year means for 2019–2023.

**Costs** (round-trip, by bucket; these are research assumptions):

| Bucket | Cost |
|---|---|
| L1 | 30 bps |
| L2 | 20 bps |
| L3 | 12 bps |

**SCREEN_PASS requires all of:**
- n ≥ 300;
- distinct dates ≥ 150;
- mean sector-relative gross **in the cell's direction** ≥ 2× bucket cost;
- the CI excludes 0 on the side of the mean;
- the yearly sign matches the overall sign in at least 4 of 5 years (a year with n < 20 counts as not stable);
- removing the top 5 doesn't flip the sign.

**Cells:** 13 × 2 directions × 5 horizons × 3 buckets = **390**. LONG and SHORT cells are mirrors, so this is **195 independent sign tests** and a mirrored pair can pass at most once. Every cell is entered in the trial ledger, including empty ones.

## 6. Integrity tolerances (locked before data)

- **Synthetic bars:** none. No interpolation and no forward fill.
- **Missing entry or exit bar** (stock or benchmark): the event is dropped from that horizon and counted as DATA_MISSING or BENCH_MISSING.
- **Duplicate symbol-session rows:** the symbol-session is removed entirely and counted.
- **Any \|daily close change\| > 75 % inside the window:** the event is kept, flagged SUSPECT_ADJUSTMENT and counted. A non-gating sensitivity that excludes these events is reported.
- **No as-traded D-1 bar:** the name is not eligible that day.
- **Cent rounding:** not applicable. This program never compares RAW and ALL prices, so nothing is carried over from Task75.
- **Changes:** none after data exists. Any change means a new version.

## 7. Data plan (Phase D, after "go")

| Source | Requests | Minutes |
|---|---|---|
| Alpaca RETURNS pass (ALL; 10,772 equities + 7 ETFs; 108 batches of 100; 2018-11-01 to 2023-12-29) | 756–1,404 | 20–37 |
| Alpaca ELIGIBILITY_ONLY pass (raw; equities only; **needs approval**) | 756–1,404 | 20–37 |
| SEC: company_tickers, cik-lookup-data, 20 Form 345 zips, submissions (about 8,000–11,000 including older pages) | about 8,000–11,000 at ≤ 2.9/s | 45–65 |

**Schedule:** start at or after 21:00Z on a weekday evening, or on a weekend. Total worst case is about 2.5 hours, finishing well before 13:00Z. The `run` stage reads only the archive. D0 then reports per-year bar coverage, including for the point-in-time S&P reference, before metrics are computed in the same single run.
