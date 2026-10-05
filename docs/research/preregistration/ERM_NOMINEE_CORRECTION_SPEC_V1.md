# ERM nominee correction specification V1 (DRAFT, uncommitted): GAP_UP_10|SHORT|H10|L1

**Status.** Draft for owner review. It is **not frozen and not committed**. No profitability, return, CI, screen or ranking has been computed under it.

**Scope.**
- The existing nominee only.
- The development period only: gap days 2019-01-02..2023-12-29.

**What this spec does not do:**
- It does not touch Gate D: rev 3.2 `7ad102a`, fingerprint `12a909e7…cb8ad`, outputs `06c2ece`.
- It does not choose window A/B.
- It does not consume the Task75 reserved windows.
- It does not lift any guard.

**Basis.** A metadata, data-lineage and fixture audit, 2026-10-05:
- Worktree `C:\workspace\TalonX-erm-audit`, branch `research/erm-nominee-integrity-audit` @ `06c2ece`.
- Scripts: `research/erm_nominee_audit/`.
- Artifacts: `results/erm_nominee_audit/`.
- Fixtures: `tests/test_erm_nominee_accounting_fixtures.py`.

## 1. Verified technical findings (evidence-based; not for approval)

| # | Finding | Evidence |
|---|---|---|
| F1 | **Provider symbol semantics.** Bars were requested without `asof`, and the provider default is the download day. For a symbol held by a listed entity on that day, the provider returns that entity's history including predecessor tickers, **relabelled** to the current symbol (documented: "Querying META … will also yield FB data"). A symbol with no current holder returns raw-symbol history, which can splice issuers that used the ticker at different times. | Alpaca `stockbars` reference (`asof`). 115 byte-identical volume series in the population. HCP: traded until 2019-11-04 (HCP Inc), then 528 zero rows, then traded from 2021-12-09 (HashiCorp). |
| F2 | **Provider placeholder bars.** Zero-volume rows exist where no trade occurred: before listings (XM: 562 rows from 2018-11-01 to 2021-01-27; MSP: 495), across ticker gaps (HCP) and on halts (exit rows). The frozen pipeline treats them as bars, so a listing-day "gap" compares the IPO open with a non-traded placeholder close, and a new listing becomes "eligible" with 19 zero-volume days in its ADV20 window. The frozen spec says "synthetic_bars: NONE". | `lineage_events.csv` (`vol0_*` columns); run-length check of the archived raw volumes |
| F3 | **JAMF.** The candidate came from source B: the pre-rename ticker of an older security that traded sporadically under JAMF and was renamed JNMF on 2020-01-13. The series then shows placeholder rows until Jamf Holding's IPO on 2020-07-22. The frozen mapping (Form 3/4/5 ticker → Jamf Holding, CIK 1721947) is right for the post-IPO trades, but the event is spurious because its gap reference is a placeholder. **Classification: reused ticker + provider placeholders; issuer mapping correct; event invalid by F2.** | `_renames_2019_2023.json`; volume runs |
| F4 | **XM.** Placeholder rows from the request start until the Qualtrics IPO (2021-01-28). There is no predecessor and the mapping (Qualtrics, CIK 1747748) is correct. **Classification: provider placeholders only; event invalid by F2.** | volume runs |
| F5 | **Duplicate observations.** 115 pairs of nominee rows are the same traded series under two symbols, with identical raw volume on all 21–22 compared sessions. In 110 pairs the frozen issuer is the same, e.g. COHR/IIVI, AXON/AAXN, BODI/FRX, TKO/WWE. In 5 pairs it differs: GDI/IR, ACY/MPU ×2, RBC/ROLL and ATYR/LIFE, all ticker-reuse mis-mappings. The frozen dedup is per symbol, so both copies were counted. | `duplicates.csv` |
| F6 | **Issuer-mapping classes** across all 2,711 rows (2,695 valid). Classes are defined in `classify.py`, with precedence top-down. See the table below. Overlaps among the valid rows: 39 carry placeholder flags; 227 are in identical-series pairs. | `classification_summary.json` |
| F7 | **R1a uses future filings.** Frozen R1a admits an unnamed symbol if its CIK filed a 10-K/10-Q anywhere in 2019–2023. Of 7,613 kept symbols, R1a governs 654 (unnamed, not S&P-exempt). After issuer correction, nominee rows with no qualifying filing by D are **TRIL 2020-09-09 and WEJOQ 2021-11-18**. The 2 PVAC rows were artefacts of a future holding-company CIK: the point-in-time issuer is Penn Virginia (CIK 77159), a 10-K filer. | `pit_events.csv` |
| F8 | **The S&P exemption uses future membership.** It applies if the ticker was a member on any day of 2019–2023. Three nominee rows lose it under "member on or before D". Two still pass R1a; **SBNY 2020-11-09** fails (FDIC filer, no SEC CIK; S&P entry 2021-12-20). | `pit_events.csv`; fja05680 PIT file (1996-01-02..2026-06-30) |
| F9 | **SIC paths are not point in time.** (i) The 6770 mask and R1b use R7 `sic_end` = the header SIC of the last company filing ≤ 2023-12-29, with an earlier SIC only before an 8-K item 5.06. (ii) **The sector ETF uses the current (download-time) submissions SIC** (`phase_d.bench_of`, `cur_sic`), falling back to SPY when the dated ticker interval does not cover the entry (263 valid rows). Under point-in-time SIC (header of the latest company filing with filing date ≤ D), **73 valid rows were SIC 6770 (blank-check/SPAC) on D**; the frozen R7 missed them, e.g. BODI/FRX, BFLY, STEM, THCB, ACHR. 214 kept valid rows would use a different ETF. | `sic_pit.csv`; 2,254 headers fetched (0 failures) + 21 already archived |
| F10 | **The adjustment is multiplicative.** ALL/raw stayed constant on 146,972 of 148,731 tested day-pairs, versus constant RAW−ALL on 5,615. Inside nominee windows (2,703 rows with entry and exit bars): 2,310 had no adjustment; 280 a factor change ≤ 0.2 %; 104 a larger unlisted change (57 > 1 %, 13 > 5 %: MAC ×3 about 40 %, IVR ×2 about 11 %, OMF 7.9 %, FBC 7.4 %, CEQP 5.4 %, …); 1 a listed split (ACMR 3:1); 8 had no raw pair. | `adjustment_summary.json` |
| F11 | **Accounting** (9 fixture tests pass). The ALL-ratio return equals fixed-position cash accounting **exactly** with no action, for splits, and for adjustments after the window (under the multiplicative convention). It **approximates** cash dividends and ETF distributions (ratio − cash = d(C_cum − d − S_exit) / ((C_cum − d) S_entry); +5.0 bps in a 1 % example; −0.97 bps for the ETF). It **diverges** for special dividends (125 bps in a 20 % example) and for spin-offs (ratio +5 % versus −6 % with the spinco obligation held in kind). | `tests/test_erm_nominee_accounting_fixtures.py` |

**F6 mapping classes:**

| Class | All rows | Valid rows | Symbols |
|---|---|---|---|
| VERIFIED_CONTINUITY | 1,919 | 1,908 | 1,013 |
| FUTURE_ASSISTED_MAPPING | 675 | 671 | 331 |
| VERIFIED_DIFFERENT_SECURITY | 70 | 69 | 41 |
| UNRESOLVED | 47 | 47 | 24 |

The 69 valid DIFFERENT_SECURITY rows break down as: Form 3/4/5 conflict 61; ticker renamed away by D 10; identical to a better-evidenced row 2 (overlapping).

**Class definitions (F6):**
- **VERIFIED_CONTINUITY:** a Form 3/4/5 filed on or before D by the assigned issuer reports this ticker, and no contrary evidence exists.
- **VERIFIED_DIFFERENT_SECURITY:**
  - the latest Form 3/4/5 ticker observation on or before D names another issuer;
  - **or** the ticker had been renamed away from the assigned entity on or before D;
  - **or** the series is identical to another row whose issuer has dated evidence while this one has none.
- **FUTURE_ASSISTED_MAPPING:** an issuer is assigned and no contrary evidence exists, but no evidence dated on or before D links the ticker to that issuer. The link rests on the 2026 SEC ticker file, later renames or the provider's relabelling.
- **UNRESOLVED:** no issuer CIK, or a cross-issuer identical pair with no dated evidence on either side.

**Remaining unknowns (not resolvable from the archive):**
- The provider's stable security identifier: the bar archive carries symbols only.
- The provider's exact behaviour for symbols with no current holder. It is inferred from the data, not documented.
- Cash-dividend records: the development corporate-action metadata covers splits and spin-offs only.
- Whether the 536 kept FUTURE_ASSISTED_MAPPING rows are all correct. They are retrospectively plausible and uncontradicted, but not proven by dated evidence.

## 2. Principle

**Retrospective verification of a contemporaneous fact is allowed.** Example: which listed security a series represents on D, or which issuer it belonged to then. Such facts existed at D, even if our archive learned them later.

**Admission may not depend on a fact that did not yet exist at D**, such as a later filing, a later index membership or a later SIC.

Bars that do not represent trades are not bars.

## 3. Proposed rules (exact)

### 3a. Minimal correctness fixes

Each fix enforces an existing frozen intent: "no synthetic bars", "one observation per event", "eligibility from data as of D", "blank checks excluded".

| ID | Rule |
|---|---|
| **C1 TRADED_BAR** | A daily bar counts only if its **raw volume > 0**; otherwise it is absent. A gap needs traded bars on D−1 and D. Eligibility needs traded raw bars on **all 20 consecutive sessions ending D**; the price and ADV formulas are unchanged. An entry bar absent → DATA_MISSING_ENTRY (dropped). An exit bar absent → DATA_MISSING_EXIT (flagged; excluded from metrics; counts in G4). |
| **C2 SERIES_DEDUP** | One observation per (traded series, entry session). Two rows are the same series iff their raw volumes are identical and > 0 on D−1, D and the entry session, and identical on every shared session of the 20-session window. Keep the row whose ticker has a Form 3/4/5 observation dated on or before D for its issuer; on a tie, keep the lexicographically smaller symbol. The choice affects only metadata (issuer, SIC, benchmark), not the bars. |
| **C3 ISSUER_AT_D** | The issuer is the assigned CIK, except for VERIFIED_DIFFERENT_SECURITY rows. Those are re-mapped to the issuer of the latest Form 3/4/5 observation of the ticker dated on or before D. If there is none, the issuer is unknown. An unknown issuer means: a **named** symbol is kept, with SPY benchmark and no SIC mask; an **unnamed** symbol is excluded, because it cannot satisfy R1a. FUTURE_ASSISTED_MAPPING rows are kept and reported. |
| **C4 R1A_AVAILABLE** | Applies to unnamed symbols that are not exempt under C5. The issuer must have a 10-K, 10-K/A, 10-Q or 10-Q/A with **EDGAR filing date ≤ D**: any year, **no recency limit**. Sources: archived `master.idx` 2019Q1+ and the archived submissions history, rows ≤ 2023-12-29. **Insufficient metadata** (history pages not archived and no qualifying filing found) → excluded and counted METADATA_INSUFFICIENT; there are 0 such rows in development. The form list and the unnamed scope are unchanged, so **only the temporal application changes, not the instrument classification.** |
| **C5 SP_PIT** | The S&P exemption applies iff the ticker appears in the point-in-time S&P 500 list on **some date ≤ D**. |
| **C6a SIC6770_PIT** | SIC on D = the SIC in `-index-headers.html` of the issuer's latest company filing (identity.COMPANY_FORMS) with EDGAR filing date ≤ D. SIC 6770 on D → that symbol-day is not eligible. **Unresolved SIC** (no issuer, no company filing by D, or a header without SIC) → no mask, counted. |

**Why availability and not recency (C4).** The frozen purpose of R1a is instrument type: is this the common stock of an SEC-reporting operating issuer? That is established by any prior periodic report. A recency window would be a new rule with no basis in that purpose. In development it removes **0 additional rows**.

**Why "membership on or before D" (C5).** The exemption's purpose is evidence of operating common stock.
- Current membership on D is narrower than that purpose: a removed member is still common stock.
- Membership anywhere in the window uses future facts and makes eligibility depend on where the window starts.
- "On or before D" uses only past facts and does not depend on the window boundaries.

**Filing-date convention.** EDGAR assigns filing date = acceptance date (ET) before 17:30, otherwise the next business day. A filing date ≤ D therefore implies the document was public before the D+1 09:30 entry.

### 3b. Optional modelling change (owner decision B1)

**C6b BENCHMARK_PIT.** The sector ETF comes from SIC_ETF_MAP_V1 applied to the C6a SIC of the C3 issuer. Unresolved SIC → SPY.

| Option | Description |
|---|---|
| Frozen (if not adopted) | Current submissions SIC of the dated-interval CIK; SPY when the interval does not cover the entry |
| Effect in development | 214 kept valid rows change ETF |
| Recommendation | Adopt. The frozen path uses a 2026 classification and a symbol interval that the provider's relabelling breaks (F1). |

## 4. Accounting interpretation (no metric replacement)

**Primary metric unchanged.** `pair_gross = −(C_exit/O_entry − 1)_stock + (C_exit/O_entry − 1)_ETF` on provider multiplicative back-adjusted bars.

**Correct label: an adjusted-return research proxy.** It is a total-return-with-reinvestment approximation.
- **Exact:** for no-action windows and splits.
- **Approximate:** for cash dividends and distributions.
- **Divergent:** for special distributions, stock dividends and spin-offs (F10, F11).
- **Not** a reproduction of executable short P&L.

**Executable-accounting validation would require:**
- raw bars;
- per-event dividend and distribution records (ex date, pay date, amount, type);
- spin-off terms and spinco prices;
- manufactured-dividend obligations on the short;
- borrow fees and locate;
- a fixed-share position ledger per event, compared with the proxy event by event.

That is not part of this spec.

**Optional descriptive addition (owner decision B2).** Report, without gating, the metric on the subset with **no in-window adjustment** (factor unchanged ≤ 1e-4) and the count of rows with factor change > 1 %. This would be fixed before any scoring.

## 5. Expected metadata-only event-set changes (development)

Rules are applied in the order C1 → C2 → C3 → C4/C5 → C6a. Each row is attributed to the first rule that changes it.

| Original valid (2,695) | Rows |
|---|---|
| Unchanged | 2,451 |
| Kept, issuer re-mapped (C3) | 51 |
| C2 duplicate dropped | 107 |
| C6a SIC 6770 on D | 41 |
| C1 not eligible (placeholder in window) | 17 |
| C1 no gap (placeholder D−1/D) | 14 |
| C1 exit → missing exit | 6 |
| C4 R1a not available by D | 3 (TRIL, WEJOQ, SBNY) |
| C3 no issuer, unnamed | 3 (MSPR ×3) |
| C1 missing entry | 2 |

- **Original missing exits (8):** 6 unchanged; 2 dropped as duplicates.
- **Additions: 0.** 35 candidate rows from frozen-R1a-removed symbols (diagnostic archive) were checked; none has qualifying evidence by D.
- **A 365-day recency variant** would remove 0 further rows and add 0.
- **Predicted corrected development set: 2,502 valid + 10 missing exits.** This is 890 distinct entry dates versus 898, and 1,280 symbols. By gap year: 2019 271, 2020 900, 2021 597, 2022 396, 2023 338.
- Full overlapping hit counts and the row-level attribution are in `reconcile_summary.json` and `reconciled_events.csv`.
- **This prediction is the acceptance target for §7 check 2. It is not a claim that only these rows can change.** Any difference stops the run.

## 6. Data sources and availability conventions

| Input | Source (archived) | Availability used |
|---|---|---|
| Bars, raw and ALL | Phase D archive `4f6aa4c1…`, diagnostic `6a9e6f12…` | bars ≤ D for eligibility; entry/exit as frozen |
| Traded flag | raw volume | same bar |
| Form 3/4/5 tickers | SEC insider data sets 2019Q1–2023Q4 (archived) | filing date ≤ D |
| Periodic filings | master.idx 2019Q1–2023Q4 plus archived submissions history ≤ 2023-12-29 | filing date ≤ D |
| SIC | `-index-headers.html`: 21 from the Phase D archive, 2,254 fetched 2026-10-05 into `results/erm_nominee_audit/_sec_pit/` (manifest with sha256) | header of the latest company filing with filing date ≤ D (retrieved retrospectively; public at its filing date) |
| S&P 500 PIT | fja05680 CSV (sha256 `39a9202c…e717`) | list dated ≤ D |
| Renames | Alpaca name changes 2019–2023 + post-2023 (archived) | used only for F-class evidence (renamed away by D) |

## 7. Future corrected development run (separately authorised; NOT executed here)

**Scope.**
- One cell: `GAP_UP_10|SHORT|H10|L1`, development 2019–2023 only.
- No other cell is evaluated; no re-nomination or ranking.
- Gate D outputs are preserved byte-exact.

**Code.** New code in an isolated branch implements C1–C6a, plus C6b and B2 if adopted. It is fingerprinted before the run. The frozen rev 3.2 code is not modified.

**Required tests (fixtures, before any scoring):**
1. **C1:** a placeholder at D−1, D, entry, exit and inside the eligibility window, each giving the specified outcome.
2. **C2:** identical-series detection, the keep rule and the tie-break; non-identical same-issuer rows are kept.
3. **C3:** re-map to the dated issuer; unknown issuer for named vs unnamed symbols.
4. **C4:** a filing dated D (admit), D+1 (reject), pre-2019 (admit), truncated history (METADATA_INSUFFICIENT).
5. **C5:** membership before, on and after D.
6. **C6a:** SIC from the latest filing ≤ D, a 6770 mask, the unresolved path. **C6b** (if adopted): ETF mapping and the SPY default.
7. **Guards:** no 2024+ bar is read; the archive sha256 is verified.
8. **Accounting fixtures:** the existing 9.

**Checks (in order):**
1. **Original-rule parity.** With every correction off, the code reproduces Gate D's `cells.csv` row for the nominee **exactly**: n 2,695; 898 dates; 1,370 symbols; mean, median, ci_low, ci_high, top-k, per-year and missing-exit values bit-identical.
2. **Corrected-rule reconstruction.** With corrections on, the row-level event set and statuses equal `reconciled_events.csv` **exactly** (2,502 valid + 10 missing exits). Exact parity of metrics with the original row is **not** required.
3. **Scoring.** Only after checks 1–2 pass: compute the frozen per-cell metrics and apply the **frozen screen unchanged** (n ≥ 300; dates ≥ 150; mean directional sector-relative gross ≥ 2 × 30 bps; date-cluster 95 % CI excluding zero on the side of the mean; sign stable in ≥ 4 of 5 years; top-5 removal keeps the sign; missing exits ≤ 2 %).
   - Also recompute the frozen survivorship diagnostic for this cell only (EXCLUSION_DEPENDENT).
   - Neighbour support is **not** re-evaluated, because that would score other cells. This is stated as a limitation.
4. **Reporting.** Every row change with its rule; original vs corrected metrics side by side; benchmark changes; FUTURE_ASSISTED_MAPPING and adjustment-class counts.

**Stop conditions:**

| Condition | Outcome |
|---|---|
| Check 1 fails | STOP: implementation defect |
| Check 2 fails | STOP: unexplained event-set difference; review |
| Any 2024+ access, guard violation or archive hash mismatch | ABORT |
| The corrected cell fails any frozen screen criterion, or is EXCLUSION_DEPENDENT | **This candidate's validation stops pending owner review.** The project does not stop; there is no re-nomination. |
| Otherwise | The corrected development result is recorded. The pre-registration (r5+) is then completed against the corrected rules before any validation data. |

## 8. Owner decisions in this spec

| ID | Decision | Notes |
|---|---|---|
| A1 | Adopt C1–C6a as a protocol amendment | Required for a defensible protocol; the alternative is validating rules known to admit placeholder, duplicate, SPAC and future-assisted rows |
| B1 | Benchmark: point-in-time SIC (C6b) or frozen current SIC | Optional; recommend C6b |
| B2 | Descriptive no-adjustment subset | Optional; recommend yes, non-gating |
| A2 | Authorise the one development-only corrected run of §7 | |
