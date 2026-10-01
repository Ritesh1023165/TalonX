# EVENT_RESPONSE_MAP_V1: design lock (Gate C)

## Revision 3 (owner, 2026-10-01; no data existed, so re-locking was allowed)

Revision 3 makes only the following changes. The frozen list is `candidates_r3.json`, whose sha256 is pinned; it supersedes `candidates_r1.json`.

| # | Change |
|---|---|
| R1-FIX a | Point-in-time S&P 500 members (any day, 2019–2023) are **exempt from R1a**. R1b still applies where a CIK exists. |
| R1-FIX b | **Identity resolution before R1a** (`identity.py`). Sources, in order:<br>1. Dated Alpaca rename chain, forward. Renames processed after 2023 are used **for identity only**, and the Task75 reserved windows were **not queried**.<br>2. SEC `company_tickers` and the submissions `tickers` field, never for a ticker that was later renamed away.<br>3. Rename chain, backward.<br>4. The issuer trading symbol on Form 3/4/5 filings 2019–2023, when it names exactly one issuer CIK.<br>5. A unique normalized name across `cik-lookup-data` and each company's submissions `name` and `formerNames`. |
| R1-FIX c | **Survivorship diagnostic (non-gating).** Phase D also downloads ALL and raw development bars for every symbol still removed by R1a (2,769 symbols, separate archive `alpaca_diag`). It reports how many pass $5/$20M eligibility, by bucket × year. For SCREEN_PASS cells only, it recomputes the cell with those symbols' events added and flags **EXCLUSION_DEPENDENT** if the cell no longer passes. |
| R6 | **Dated attribution.** Each 8-K goes to the one ticker valid for its CIK on the **filing date**, using the dated rename chain. A ticker is valid from the processing date of the rename into it until the rename out of it.<br>• Bar presence on the entry date is a consistency check only.<br>• AMBIGUOUS, NO_VALID_TICKER and DISAGREE filings are excluded and counted.<br>**Audit of every one-ticker-per-CIK use:**<br>1. 8-K attribution: dated rule.<br>2. Sector benchmark: dated symbol→CIK on the entry date, else SPY.<br>3. Form 4 symbol: the dated ticker of the issuer CIK on the filing date. The reported symbol must agree, else the row is excluded and counted.<br>4. The rev-1 `UNMAPPED_INACTIVE_CIK` map is retired. |
| R7 | **Chosen: dated SIC.** R7 is implemented, not written in as a limitation.<br>• SIC comes from the EDGAR filing header of the CIK's last company filing on or before 2023-12-29.<br>• If the CIK filed an 8-K item 5.06 (change in shell company status) in the period, the header SIC of its last company filing before that 8-K applies before the 8-K.<br>• If the CIK has no company filing in the period, the current SIC is used, and this fallback is counted.<br>• R1b removes a symbol whose SIC is 6770 for the whole period, and masks the 6770 days of a symbol that was 6770 for only part of it.<br>**Cost:** about one header per CIK plus one per item-5.06 CIK, 6,000–7,000 SEC requests at ≤ 2.9/s (about 40 minutes off-hours), so it was affordable.<br>**Residual limitation:** an SIC reclassification inside the period without an item 5.06 is not dated. |

### Revision 3 results (metadata only)

The SEC archive holds 13,558 files. Alpaca returned 1,542 post-2023 rename records; 2,667 dated rename edges were used in total.

**R1a removals, by stage:**

| Stage | R1a total | No CIK | CIK without 10-K/10-Q | Source B | Source C | Source D |
|---|---|---|---|---|---|---|
| Rev 2 (no exemption, rev-2 identity) | 3,467 | 3,415 | 52 | 835 | 2,659 | 47 |
| + S&P 500 exemption | 3,420 | 3,368 | 52 | 833 | 2,651 | 0 |
| **+ identity resolution (final)** | **2,769** | 2,628 | 141 | 494 | 2,290 | 0 |

Source counts overlap, because a symbol can come from several sources.

| Count | Value |
|---|---|
| R1b, SIC 6770 for the whole period (dated) | 390 removed |
| R1b, SIC 6770 for part of the period | 46 symbols, those days masked |
| **Kept** | **7,613** (removed 3,159 = R1a 2,769 + R1b 390) |
| Identity methods | SEC_TICKERS 5,628; FORM345_TICKER 1,303; RENAME_CHAIN_FWD 731; UNIQUE_NAME_MATCH 52; RENAME_CHAIN_BWD 14; FORM345_AMBIGUOUS 29; UNMAPPED 3,015 |
| R7 SIC sources (per CIK) | Last-filing header 5,689; current-SIC fallback 1,209; item-5.06 split 299 |

**Point-in-time S&P 500 coverage after revision 3:** 100.0 % in 2019, 2020, 2021, 2022 and 2023 (metadata). Bar availability is measured in D0.

**8-K attribution (R6), metadata stage.** Counts are per (filing, target item):

| Outcome | Count |
|---|---|
| Assigned | 195,210 |
| **Excluded: NO_VALID_TICKER** | **14,099** |
| **Excluded: AMBIGUOUS** (dual share classes and similar) | **5,530** |
| Assigned to an R1-removed symbol | 1,212 |

DISAGREE is the bar-consistency check, so it is counted in Phase D.

**Form 3/4/5 dated-symbol audit** (all 1,007,910 filing observations): MATCH 777,164; DISAGREE 12,396; AMBIGUOUS 16,813; NO_VALID_TICKER 36,510; CIK_NOT_IN_UNIVERSE 165,027.

**Residual limitation:** Alpaca renames processed inside the Task75 reserved windows were not queried. Those identities rely on EDGAR sources only.


## Revision 2 (owner, Gate C, 2026-10-01; no data existed, so re-locking was allowed)

The owner approved decisions 1–4 at Gate C:
1. Raw as-traded D-1 data is used **for ELIGIBILITY ONLY**. Returns stay `adjustment=all`.
2. Gaps enter at the D+1 open.
3. 8-K acceptance time is read conservatively (the later of the UTC and ET readings).
4. The cost test is directional.

Revision 2 makes only the following changes:

| # | Change |
|---|---|
| R1 | **Instrument filter**, applied before any price download and frozen as `candidates_r1.json` (sha256 pinned):<br>• R1a: a candidate with no known name is kept only if it maps to a CIK with a 10-K, 10-K/A, 10-Q or 10-Q/A filed 2019–2023 (EDGAR `master.idx`, 2019Q1–2023Q4).<br>• R1b: any candidate whose CIK has SIC 6770 (blank checks; current EDGAR SIC) is excluded. |
| R2 | **Null calibration.** If any NO_EVENT cell is SCREEN_PASS, the map is classified MAP_MISCALIBRATED and every nomination is blocked until that is explained. The NO_EVENT pass count is the **first line** of `report.md`. |
| R3 | **Missing exits.** Each cell reports its missing-exit rate (entry bar present, exit bar absent). A cell above **2 %** cannot be SCREEN_PASS. Cells at or below 2 % also get a **non-gating** bound sensitivity that fills missing exits two ways: (LONG −100 %, SHORT 0 %) and the mirror (LONG 0 %, SHORT −100 %). |
| R4 | **Coverage.** The D0 report breaks out by **liquidity bucket × year**: eligible symbol-days, distinct symbols, ALL-bar present rate and missing-exit rate. This is in addition to the source and point-in-time S&P 500 breakdowns. |
| R5 | **Off-hours guard.** Alpaca and SEC calls are refused on weekdays between **09:00 and 16:30 America/New_York**, using `zoneinfo` so it follows DST (US DST ends 2026-11-01). |
| Schedule | Phase D runs on **Sat 2026-10-03 or Sun 2026-10-04**, while the live engine is in CLOSED phase, with `--go --eligibility-raw-approved`. |

### R1 result (metadata only: SEC archive of 5,844 files, 185 MB, fetched 2026-10-01 07:23–08:02Z)

| Count | Value |
|---|---|
| Candidates in | 10,772 |
| R1a removed: no known name | **3,467** |
| … of which no CIK | 3,415 |
| … of which a CIK with no 10-K or 10-Q in 2019–2023 | 52 |
| R1b removed: SIC 6770 | **279** |
| Removed by both rules | 1 |
| **Removed in total** | **3,745** |
| **Kept** | **7,027** |
| Kept with no known name (they passed R1a) | 85 of 3,552 |
| Kept with a mapped CIK but unknown SIC | 170 |
| CIK methods | SEC_TICKERS 5,638; RENAME_CHAIN 592; UNIQUE_NAME_MATCH 197; UNMAPPED 4,345 |

**Side effect: R1a removes former S&P 500 members.** It removes **47 of the 614** point-in-time S&P 500 members (any day, 2019–2023), every one of them as R1A_UNNAMED_NO_CIK. Examples: BK, MMC, AVB, EQR, EA, HES, WBA, K, ATVI, TWTR, SIVB, FRC, PXD and JNPR.

These are common stocks. They fail R1a only because their ticker changed or they were delisted after 2023: BK is now BNY and MMC is now MRSH, so neither SEC's current ticker map nor Alpaca carries the old symbol.

Point-in-time S&P 500 coverage after R1:

| Year | Coverage |
|---|---|
| 2019 | 91.74 % |
| 2020 | 92.94 % |
| 2021 | 92.95 % |
| 2022 | 93.35 % |
| 2023 | 94.82 % |

Before R1 it was 93.6–95.2 % (metadata). This is a survivorship bias against names renamed or delisted after 2023. It is recorded here and raised to the owner.


**Status:** DESIGN_LOCKED, **revision 3**. The fingerprint is in `design_lock.json` and the commit message. This supersedes rev 2 `8a57c33` / `bdf4a160…` and rev 1 `067ed29` / `0b379979…`. **No price data exists** for this program at lock time.

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
