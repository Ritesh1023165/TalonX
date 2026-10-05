# ERM nominee correction specification V2 (DRAFT for freeze review, uncommitted): GAP_UP_10|SHORT|H10|L1

**Status.** Draft for **freeze review**. It is not frozen and not committed. No return, CI, screen, ranking or profitability has been computed under V1 or V2.

**What V2 changes.** It supersedes V1 (`ERM_NOMINEE_CORRECTION_SPEC_V1.md`, sha256 `bb97e2ff…a4c9`, preserved unchanged). V1's metadata prediction of 2,502 valid events is **withdrawn**: V1 accepted identities that V2 treats as unverified.

**Scope.**
- The existing nominee only.
- The development period only: gap days 2019-01-02..2023-12-29.

**What this spec does not do:**
- It does not touch Gate D: rev 3.2 `7ad102a`, fingerprint `12a909e7…cb8ad`, outputs `06c2ece`.
- It does not choose window A/B.
- It does not consume the Task75 reserved windows.
- It does not change any guard.

**Basis.**
- Worktree `C:\workspace\TalonX-erm-audit`, branch `research/erm-nominee-integrity-audit` @ `06c2ece`, uncommitted.
- Rules: `research/erm_nominee_audit/v2_rules.py` (pure functions; the single source for the manifest and the fixtures).
- Manifest builder: `v2_manifest.py`.
- Fixtures: `tests/test_erm_nominee_v2_rules.py` (19) and `tests/test_erm_nominee_accounting_fixtures.py` (9).

## 1. Principles

1. **Retrospectively retrieved evidence may establish a historical fact only if the fact applied on D.** Examples: a rename record, a Form 3/4/5 filed by D, an 8-K item 5.06 showing the issuer was a shell on D.
2. **Admission never depends on a fact that came into existence after D,** such as a later filing, later index membership or a later SIC.
3. **The following are never identity or instrument evidence:** a current name, a current CIK, a current SIC, an uncontradicted future mapping, or price similarity alone.
4. **Unresolved cases are excluded from the primary sample** with a reason code, kept in a separate manifest and **never scored**. Unresolved means not established, not proven bad.
5. **No rule uses returns, benchmark performance or outcome availability.** Exit-bar presence is used only for the frozen DATA_MISSING_EXIT status.

## 2. Rules and evidence hierarchy (exact; implemented in `v2_rules.py`)

### 2.1 Bars (C1, unchanged from V1)
- A bar counts only if its **raw volume > 0**.
- The gap needs traded bars on D−1 and D (`C1_NO_GAP_PLACEHOLDER`).
- Eligibility needs traded bars on all 20 sessions ending D (`C1_NOT_ELIGIBLE_PLACEHOLDER`).
- An entry placeholder means missing entry.
- An exit placeholder or absent exit bar means `DATA_MISSING_EXIT` (flagged; excluded from metrics; counts in G4).

### 2.2 Identity at D: series → ticker → issuer
**Series lineage (`ticker_at`).** Bars were requested without `asof`, so the provider returns the download-day holder's history, with predecessor tickers relabelled.
- The ticker the series traded under on D is found by walking dated rename records (provider corporate actions, with CUSIPs) **backwards from the requested symbol through renames dated after D**.
- A predecessor edge must be dated **before** the edge it feeds. A later rename into a vacated ticker is a reuse and is not followed.
- A symbol renamed away after its last rename-in has no download-day holder; its raw-symbol history is used, with no relabelling.
- Ambiguous or cyclic chains → `CONTRADICTORY`.

**Issuer.** The issuer of the **latest dated Form 3/4/5 observation** (issuer trading symbol; 2018Q1–2023Q4) of that ticker, filed on or before D. It is accepted only if all of the following hold:
1. the latest filing date names exactly one issuer;
2. the ticker was not renamed away between that filing and D;
3. the series shows no trading break (≥ 5 consecutive zero-volume sessions) between that filing and D.

**Classes:**

| Class | Definition |
|---|---|
| VERIFIED_HISTORICAL_IDENTITY | the above holds, and the issuer equals the frozen CIK |
| VERIFIED_DIFFERENT_SECURITY | the above holds, but the issuer differs from the frozen CIK. **Correction:** the verified issuer is used for R1a, the S&P exemption, SIC and the benchmark. |
| UNRESOLVED_IDENTITY / ABSENT | no dated observation by D |
| UNRESOLVED_IDENTITY / CONTRADICTORY | ambiguous or cyclic chain; two issuers on the latest date; renamed away after the evidence; or a trading break after the evidence |

Both UNRESOLVED classes are excluded with flag `ID_UNRESOLVED`.

### 2.3 Duplicates (replaces V1's volume-only C2)

| Step | Rule |
|---|---|
| Candidate generation | Same entry session; identical raw volume, > 0, on D−1, D and the entry session, and identical on every shared session of the 20-session window. |
| Data corroboration (`same_series`) | ≥ 20 common positive-volume sessions in the window, with raw open **and** close equal within **$0.005** on every one of them (`SAME_DATA`). Different prices → `NOT_DUPLICATE`: both rows are judged separately. Fewer common sessions → unresolved. |
| Lineage corroboration (`duplicate_link`) | `SAME_DATA` **and** both rows have VERIFIED identities with the **same ticker on D and the same issuer** → `VERIFIED_DUPLICATE`. Otherwise → `UNRESOLVED_DUPLICATE`. Share classes trade under different tickers, so they are never merged by issuer alone. |
| Groups | Connected components of candidate links. A group is accepted only if **every** pair in it is VERIFIED; otherwise **all members are excluded** (`DUP_UNRESOLVED`). There is no chaining through partial links. |
| Representative | (1) the member requested under the security's own ticker on D; (2) more positive-volume sessions in the window; (3) lexically smallest symbol. The others get `DUP_NOT_REPRESENTATIVE`. |

### 2.4 R1a (availability, no recency)
- Applies to unnamed candidates that are not exempt under §2.5.
- The **verified** issuer must have a 10-K, 10-K/A, 10-Q or 10-Q/A with EDGAR filing date ≤ D, any year.
- Sources: the master.idx archive plus the archived submissions history, rows ≤ 2023-12-29.
- Fails → `R1A_NOT_AVAILABLE`.
- Named candidates keep the frozen instrument-name rules. The issuer still has to be verified (§2.2), and the instrument resolved (§2.6).

### 2.5 S&P exemption, tied to the security
The exemption is **VERIFIED** iff all of the following hold:
1. the ticker the verified series traded under on D is on a point-in-time S&P 500 list dated t, with 2018-01-01 ≤ t ≤ D;
2. a dated Form 3/4/5 links that ticker to the **same** issuer within [t − 365 d, D];
3. no other issuer reported that ticker within [t, D];
4. the ticker was not renamed away within (t, D].

Membership of a reused ticker string is therefore not evidence.

### 2.6 Instrument status on D (first applicable)

| # | Evidence | Status |
|---|---|---|
| 1 | 8-K item 5.06 filed ≤ D and after the SIC source filing (explicit de-SPAC) | OPERATING (sector known unless the SIC is 6770) |
| 2 | 8-K item 5.06 filed **after** D, with none ≤ D: the issuer was a shell on D, a contemporaneous fact | **SPAC** |
| 3 | Dated SIC 6770: header of the latest company filing ≤ D | **SPAC** |
| 4 | Dated SIC known and not 6770 | OPERATING_SECTOR_KNOWN |
| 5 | No dated SIC, but the S&P evidence (§2.5) is VERIFIED | OPERATING_SECTOR_UNKNOWN |
| 6 | Otherwise | **UNRESOLVED_INSTRUMENT** (excluded) |

SPAC → `INSTRUMENT_SPAC` (excluded).

### 2.7 Point-in-time benchmark (part of the corrected primary definition)
- The frozen `SIC_ETF_MAP_V1` is applied to the dated SIC from §2.6.
- A known SIC outside the mapped ranges → SPY (the frozen map default).
- OPERATING_SECTOR_UNKNOWN → **SPY**, an explicit fallback.
- The frozen 2026-SIC benchmark is kept **only** for original-rule parity and provenance. **It is not a selectable alternative.**

### 2.8 Exclusion precedence (mutually exclusive first reason)
`BEYOND_WINDOW` → `C1_NO_GAP_PLACEHOLDER` → `C1_NOT_ELIGIBLE_PLACEHOLDER` → `C1_ENTRY_PLACEHOLDER` → `ID_UNRESOLVED` → `DUP_UNRESOLVED` → `DUP_NOT_REPRESENTATIVE` → `R1A_NOT_AVAILABLE` → `INSTRUMENT_SPAC` → `INSTRUMENT_UNRESOLVED`.

Every row also carries all of its flags, so overlaps are reported.

## 3. Accounting (frozen metric preserved)

**Primary metric unchanged.**
- `pair_gross = −(C_exit/O_entry − 1)_stock + (C_exit/O_entry − 1)_ETF` on provider back-adjusted bars.
- It is an **adjusted-return research proxy**, not executable short P&L.
- Fixtures: exact with no action and for splits; approximate for cash distributions; divergent for special distributions and spin-offs.
- **Corrected wording:** "Multiplicative adjustment factors cancel in a return ratio when the same factor applies to both endpoints. This does not establish invariance to ticker remapping, provider revisions or all download dates."
- Empirically, ALL/raw behaved multiplicatively on 146,972 of 148,731 tested day-pairs.

**Fixed descriptive sensitivity: no in-window adjustment on BOTH legs.** It is **never gating** and never changes the primary verdict.

| Leg | Rule | Source / tolerance |
|---|---|---|
| Stock | NO_ADJUSTMENT iff, for **every** session from entry to exit, both open and close satisfy \|ALL − m·RAW\| ≤ **0.0051**, where m = median(ALL/RAW) over the interval. A change that later reverses still fails. A missing raw/ALL pair → UNKNOWN. | archive raw + ALL bars. Tolerance = half-cent raw rounding (≤ 0.005·m) + 0.0001 ALL rounding. |
| ETF | NO_ADJUSTMENT iff no provider cash-dividend record for that ETF has an ex-date in (entry, exit]. No records for the ETF → UNKNOWN. | provider corporate actions `cash_dividend`, 2019–2023, 7 ETFs, 129 records, fetched 2026-10-05 (`_alpaca_v2/`). The archive has no raw ETF bars. |
| Subset | both legs NO_ADJUSTMENT; any UNKNOWN → UNKNOWN, not in the subset | |

**Predicted subset among the 1,999 valid events:** 1,459 IN, 540 OUT, 0 UNKNOWN. The stock leg is adjusted in 273 events and the ETF leg in 309.

## 4. Metadata-only sample prediction (development; deterministic)

**Populations:**

| Population | Definition | Rows |
|---|---|---|
| **A** | Gate D pre-return population | 2,711 |
| **B** | GAP_UP_10/L1 events of frozen-R1a-removed symbols (diagnostic archive) | 35 |
| **C** | events on frozen R7 SIC-6770-masked symbol-days | 6 |

Out of boundary: R1b whole-period-6770 symbols (no bars archived) and symbols outside the frozen candidate list.

**Proposed primary sample: 1,999 valid + 2 DATA_MISSING_EXIT.**
- 1,047 symbols and 806 entry dates.
- By gap year: 2019 240, 2020 721, 2021 455, 2022 300, 2023 283.
- Benchmarks: SPY 729, XBI 412, XLK 284, XLI 217, XLF 210, XLV 76, XLE 71.
- Also: 7 beyond the window, 0 missing entry, 744 excluded.

**Original (frozen) status → V2 status, population A:**

| Frozen status | V2 VALID | V2 MISSING_EXIT | V2 EXCLUDED | V2 BEYOND |
|---|---|---|---|---|
| VALID (2,695) | 1,997 | 0 | 698 | 0 |
| DATA_MISSING_EXIT (8) | 0 | 2 | 6 | 0 |
| DATA_MISSING_ENTRY (1) | 0 | 0 | 1 | 0 |
| BEYOND_DEV_END (7) | 0 | 0 | 0 | 7 |

**First reason for the 698 excluded original-valid rows:**

| First reason | Rows | Detail |
|---|---|---|
| ID_UNRESOLVED | 562 | 533 ABSENT: 361 Section-16-exempt foreign private issuers (160 symbols); 142 domestic filers with no ticker observation by D (79); 30 with no CIK (14). 29 CONTRADICTORY: 25 trading break; 2 cyclic; 1 ambiguous chain; 1 renamed away. |
| DUP_NOT_REPRESENTATIVE | 64 | |
| INSTRUMENT_SPAC | 25 | the 42 original-valid rows flagged SPAC (any order): 38 by dated SIC 6770, 4 by a later 8-K 5.06 |
| C1_NOT_ELIGIBLE_PLACEHOLDER | 17 | |
| DUP_UNRESOLVED | 16 | |
| C1_NO_GAP_PLACEHOLDER | 10 | |
| INSTRUMENT_UNRESOLVED | 4 | |

**Further detail:**
- **Additions: 2** from population B: MIC 2021-06-07 and CTIC 2023-05-10. The frozen identity found no CIK; V2 verified the issuer and an available periodic filing. Population C: all 6 are excluded (4 SPAC, 2 placeholder/duplicate).
- **Duplicates:** 65 verified groups (130 rows; every representative chosen by OWN_TICKER_ON_D); 106 rows in unresolved duplicate links (excluded).
- **Re-mapped:** 62 kept valid events carry a verified issuer different from the frozen CIK.
- **Benchmark:** 143 kept valid population-A events change ETF versus Gate D.
- **Unresolved manifest:** 618 rows (ID 598, duplicate 16, instrument 4), preserved and never scored.

**Why V2 differs from V1 (2,502 valid).** V1 kept rows whose identity rested on future or uncontradicted mappings; V2 requires dated evidence.
- 492 V1-valid rows are now ID_UNRESOLVED.
- 9 are now unresolved duplicates.
- 7 are SPAC by the later-5.06 rule.
- 5 have a different representative.
- 4 have an unresolved instrument.
- 12 V1-excluded rows are now valid:
  - 5 representatives now chosen by the ticker on D (e.g. WWE, HFC, MOXC, ROLL);
  - 3 MSPR rows whose issuer is now verified;
  - 3 rows (DBGI ×2, APVO) that V1 flagged using split-**adjusted** volume, which rounds small traded volumes to 0; V2 uses **raw** volume as specified;
  - 1 former V1 SIC-6770 row.

**Determinism.** Two full runs produced the identical manifest, sha256 `1a1fd666ed3c453197b86e87235a6356da17350b31908d7e473f2d5c1a860040`.

## 5. Inputs, acquisitions and provenance

| Input | Source | Note |
|---|---|---|
| Bars, raw + ALL | Phase D archive (`4f6aa4c1…`), diagnostic (`6a9e6f12…`) | read only; sha256-verified by the frozen loader |
| Form 3/4/5, 2019Q1–2023Q4 | Phase D archive | |
| Form 3/4/5, 2018Q1–Q4 | **acquired 2026-10-05**, `_sec_v2/` (manifest `83be9d2e…`) | targeted: early-2019 evidence |
| Submissions JSON, 36 issuers (49 files) | **acquired 2026-10-05**, `_sec_v2/` | verified issuers never archived by Phase D |
| Filing headers (point-in-time SIC) | Phase D archive + `_sec_pit/` (2,254) + `_sec_v2/` (74) | header of the latest company filing ≤ D |
| ETF cash dividends 2019–2023 | **acquired 2026-10-05**, `_alpaca_v2/` (manifest `469aabb2…`, data `89ea0197…`) | descriptive sensitivity only |
| Renames 2019–2023 + post-2023 | Phase D archive | Task75 reserved windows not queried (frozen limitation) |
| S&P 500 point-in-time lists | fja05680 CSV `39a9202c…` | |

All network calls went through frozen clients with the R5 off-hours rule. Nothing from 2024+ market data was read.

## 6. Remaining limitations (handled; not an open backlog)

| Limitation | Handling |
|---|---|
| **Coverage dependence.** The sample is conditional on the evidence types used. Foreign private issuers and domestic issuers without insider-filing tickers are excluded as ABSENT. **The population therefore changes: nearly all foreign private issuers leave the primary sample.** | Disclosed; the rows are in the unresolved manifest. A future spec version could add 20-F/10-K cover-page ticker evidence; not proposed here. |
| Share-class rename records can misdirect the relabelling walk (e.g. COHR/IIVI 2019 → IIVIP) | Outcome is ABSENT → excluded, never a wrong inclusion through that path |
| A Form 3/4/5 ticker can be misreported by a filer | Mitigated by the latest-observation, rename-away and trading-break checks; residual |
| Renames processed inside the Task75 reserved windows were not archived | Chains through them stay ABSENT or CONTRADICTORY → excluded |
| The provider has no stable security ID in the archive; the provider's behaviour for symbols with no holder is inferred | Rules depend only on archived records |
| Events of symbols outside the frozen candidate list, or removed by R1b whole-period 6770, are not evaluated | Out of boundary |
| ETF distribution records cover cash dividends only | Other ETF actions would be invisible to the descriptive sensitivity |

## 7. Future one-cell development run (separately authorised; NOT executed)

**Scope.**
- One cell: `GAP_UP_10|SHORT|H10|L1`, development 2019–2023 only.
- Gate D preserved byte-exact. No other cell, no re-nomination, no ranking.

**Checks (in order):**
1. **Code.** An isolated branch imports `v2_rules.py` unchanged. All 28 fixtures pass. The code is fingerprinted before any scoring.
2. **Original-rule parity.** With all corrections off, the code reproduces the Gate D `cells.csv` nominee row **exactly** (n 2,695; 898 dates; mean, median, CI bounds, top-k, per-year and missing-exit values bit-identical).
3. **Corrected-manifest check.** The scoring code rebuilds the V2 manifest independently. Its sha256 must equal **`1a1fd666…0040`** (or a re-frozen value if the owner amends a rule before the freeze). The scored set is exactly the rows with `v2_status ∈ {VALID, DATA_MISSING_EXIT}`, using `benchmark_v2`.
4. **Scoring (once).** Frozen metrics and the **frozen screen unchanged**: n ≥ 300; dates ≥ 150; directional sector-relative mean ≥ 2 × 30 bps; date-cluster 95 % CI excluding zero on the side of the mean; ≥ 4/5 stable years; top-5 removal keeps the sign; missing exits ≤ 2 %. Also the frozen survivorship diagnostic for this cell (EXCLUSION_DEPENDENT). The descriptive sensitivity of §3 is reported. **Neighbour support is not re-evaluated** (limitation).
5. **Reporting.** Original vs corrected side by side; every row change with its first reason; unresolved rows listed but never scored.

**Stop conditions:**

| Condition | Outcome |
|---|---|
| Check 2 fails | STOP: implementation defect |
| Check 3 fails | STOP: manifest mismatch; review |
| Any 2024+ access, guard violation or archive hash mismatch | ABORT |
| Corrected cell fails any frozen screen criterion, or is EXCLUSION_DEPENDENT | **This candidate's validation stops pending owner review.** The project does not stop; there is no re-nomination. |
| Corrected PASS | Supports further research only: the pre-registration may be completed against V2. It does not prove executable profitability or validate the map. |

## 8. Owner decisions for the freeze

| ID | Decision |
|---|---|
| A1 | Adopt V2 (§2–§4) as the correction amendment, including the point-in-time benchmark (§2.7) |
| A2 | Accept the coverage-dependence consequence (§6, first row): unresolved identities are excluded rather than investigated further |
| A3 | Authorise the one development-only run of §7 |

Window A/B, the Task75 acknowledgement and the other pre-registration decisions remain pending in the draft (r6).
