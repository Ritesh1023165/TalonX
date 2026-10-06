# FINAL PROTOCOL: GAP_UP_10|SHORT|H10|L1_V1 (window B; LOCKED by ERM_NOMINEE_PROTOCOL_LOCK.json; NOT A GO)

**Status (2026-10-06).** This is the final protocol.
- **Owner decisions are recorded:** D1 window B, D2, D4, D5, D6, D6a and D7 (`ERM_NOMINEE_OWNER_DECISION_RECORD_B.md`; config fields in `ERM_NOMINEE_OWNER_DECISIONS_B.json`).
- **Locked:** this protocol and the reviewed implementation, by `ERM_NOMINEE_PROTOCOL_LOCK.json` and `ERM_NOMINEE_IMPLEMENTATION_LOCK.json` (verifier: `python -m research.erm_nominee_validation.lock verify`).
- **NOT A GO.** No release is active and no guard is lifted.
- **No data has been touched.** No 2024+ data has been read for this hypothesis, and no validation-window input has been acquired.
- **Task75 reserve:** no consumption entry exists. Consumption happens only at the later authorised acquisition (D2).
- **Guard:** the EVENT_RESPONSE_MAP_V1 guard (EXCLUDED_2024; FUTURE_CONFIRMATION from 2025-01-02) stays locked. Releasing it needs a separate, explicit GO that names the exact scope with an instantiated reference date R, followed by the reviewed scoped activation (`release.py`, with the ERM and Task75 audit records).

Historical validation needs that separate GO.

**Authoritative rules.** Eligibility and identity are governed by correction spec V2.1:
- `docs/research/preregistration/ERM_NOMINEE_CORRECTION_SPEC_V2_1.md` sha256 `b805ce415fb067d6e0fad90859ddc7d35a31e3195c946cbe3460172c7a72ded2`
- `docs/research/preregistration/ERM_NOMINEE_CORRECTION_V2_1_FREEZE.json` sha256 `8581e3d3c37e661d3554071b2217a537d51234c8b6c1af7b38fbcc28825b31f5`
- `research/erm_nominee_audit/v2_rules.py` sha256 `a4e3b82d3d9da1d624a9539e4636cb5945253b9785fb45fb425f3ba5730548ef`

They are restated in §2 and §4 without amendment. Where any wording here and the V2.1 sources differ, V2.1 governs.

**Basis (verified 2026-10-05).**
- **Gate D:** `research/event-response-map-v1` @ `06c2ece`. Design lock rev 3.2, fingerprint `12a909e7…cb8ad`.
- **Correction spec V2.1 (authoritative; supersedes V1 and V2, both preserved):** `research/erm-nominee-integrity-audit` @ `aab578e`.
  - Spec sha256 `b805ce415fb067d6e0fad90859ddc7d35a31e3195c946cbe3460172c7a72ded2`.
  - Freeze record `8581e3d3…31f5`.
  - Manifest `9ed45652ff1ddf4237a71ad920e7b30d506133f774ac7e3f760aa092f0e8579d`.
  - Rules `v2_rules.py` (`RULES_VERSION = ERM_NOMINEE_CORRECTION_V2.1`) sha256 `a4e3b82d…48ef`.
- **Corrected development run:** `research/erm-nominee-corrected-dev-run` @ `b91dc0a`. Verdict **CORRECTED_DEVELOPMENT_SCREEN_PASS**; marker `RUN_COMPLETE.json`; `corrected_cell.json` `da63533d…cc9e`.
- **Validation plumbing and workflow (review, not locked):** branch `research/erm-nominee-validation-plumbing` (§10). r8 (`99566b58…0751`) is preserved.
- Earlier drafts r1–r9 are preserved unchanged: r1–r7 outside the repository (r7 `7fdbad17…e24f`); r8 and r9 (`fa59a9ca…a3a32b`) in the repository.
- **r10 changes procedure only** (§4 T5 and T8–T11, §7 step 0 wording, §9, §10, §11, §12). §1–§3, §5, §6, §8 and every rule, gate, cost, estimator and threshold are unchanged from r9.
- **This final protocol = r10 (`e6385dd0…9929`, preserved) + the recorded owner decisions + procedural precision only** (status tags, the S&P snapshot semantics in T11, T12 byte representation, the exact D6a rule in §10). §12 lists every change.

**Rule tags:**

| Tag | Meaning |
|---|---|
| [MAP] | Frozen before discovery (design lock rev 3.2 / nomination protocol) |
| [MAP→W] | [MAP] rule with the validation window's dates substituted |
| [V2.1] | Frozen correction rule (owner-adopted A1, 2026-10-05) |
| [R1] | Draft rule written after Gate D, before any validation data |
| [AMEND] | Amendment; **approved by the owner 2026-10-06 (D4/D6)** |
| [ASSUME] | Modelling assumption; **accepted by the owner 2026-10-06 (D5)** |
| [PREREQ] | Implementation prerequisite |

---

## 0. Provenance

| Item | Value |
|---|---|
| Design lock | rev 3.2, `7ad102a`; fingerprint `12a909e795986ff3abeac9ca92906a64c3387a5e3c64734f2b72031b781cb8ad` |
| Gate D scoring | Phase D attempt 2, 2026-10-04, offline; outputs `06c2ece` (`cells.csv` `bd8fd486…`, `trial_ledger.json` `6c987f67…`) |
| Bootstrap library | `research/common/research_stats.py` sha256 `79ae73bf8082c8fa70f97f8b2e3277b00e64f3a4a98fe5b165ed1ee2b78c243d` |
| Development | gap days 2019-01-02..2023-12-29 |
| Original nominee (Gate D) | 2,695 valid (898 dates, 1,370 symbols) + 8 missing exits; mean sector-relative gross +2.852 %; CI [+1.421 %, +4.230 %] |
| Corrected nominee (V2.1) | 1,999 valid (806 dates, 1,047 symbols) + 2 missing exits; mean +1.963 %; CI [+0.576 %, +3.324 %] |

## 1. Statistical claims

### 1a. Discovery selection (development, unchanged)
- **Grid:** 390 directional cells (330 nominatable). The cells are **not independent**: thresholds are nested, horizons share events, and event types overlap.
- **No family-wise or FDR correction was pre-specified.** Safeguards were the fully ledgered grid, the NO_EVENT null calibration (0/30) and a single frozen-ranked nominee.
- **"Survives correction for 195 tests" remains UNVERIFIED and withdrawn. No discovery multiplicity-correction claim is reinstated.**
- **Selection implies shrinkage** (winner's curse), so §8 also plans at half the corrected effect.

### 1b. Corrected development result (what it does and does not establish)
- **The corrected development screen passed.** All seven frozen screen criteria passed on the V2.1 evidence-covered population:
  - n 1,999 ≥ 300;
  - 806 dates ≥ 150;
  - mean +1.963 % ≥ 2 × 30 bps;
  - CI [+0.576 %, +3.324 %] excludes 0;
  - 5 of 5 years (2019 only +0.10 %);
  - top-5 removal +1.767 %;
  - missing exits 0.10 %.
- **Parity was verified first.** Original-rule parity reproduced all 25 Gate D metrics exactly, and the corrected manifest was rebuilt hash-identically.
- **The result applies to the evidence-covered population only.** 625 unresolved rows (mostly Section-16-exempt foreign private issuers) are excluded and were never scored.
- **The survivorship add-back check was vacuous.** No row was excluded solely by R1a, so nothing was added. It does **not** establish broad survivorship robustness.
- **Neighbour support was not rechecked.**
- **The descriptive subset `NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND`** (n 1,459; gross mean +1.486 %; gross CI [+0.048 %, +2.848 %]) **does not establish a positive after-cost CI.** Its lower bound lies below the 34 bps primary cost.
- **The metric is an adjusted-return research proxy**, not executable short P&L. A corrected pass supports further research only.

### 1c. The single validation hypothesis
- **H₀:** mean(pair_net) ≤ 0 over the validation window's eligible (V2.1) events.
- **H₁:** mean(pair_net) > 0.
- **The historical validation uses its own declared gates G1–G4 (§7).** These are **not** the development screen. For example, there is no 4-of-5-year criterion and no 2 × cost criterion; instead G1 is a mean net of the declared costs > 0.
- **Primary criterion G2:** the lower bound of the **two-sided 95 % date-clustered percentile bootstrap CI** of mean(pair_net) > 0. That is `bootstrap_ci_clustered`: group = entry date (ISO string), 10,000 resamples, seed 670067, events sorted by (entry date, symbol).
- **Tail convention.** G2 is a directional decision on one bound of a two-sided 95 % interval, a **nominal one-sided 2.5 %** level (approximate under the percentile bootstrap). It does not switch to any other level or test.
- **Inference limitation (stated, not corrected).** The frozen estimator resamples whole **entry dates**. Each event is held for 11 sessions, so events with different entry dates overlap in time and share market moves. **Entry-date clustering does not capture dependence across overlapping holding periods.** The interval is therefore likely too narrow, and G2 is likely too permissive.
  - The frozen estimator, seed (670067), 10,000 resamples and 95 % level are **kept unchanged**. No other test and no substitute estimator are added.
  - **Any PASS is conditional on:**
    1. this inferential limitation;
    2. prior exposure (§1e);
    3. evidence coverage (the V2.1 population);
    4. the adjusted-return proxy (§3).

### 1d. Interpretability conditions and limitations
**A single pre-registered test is interpretable only if:**
1. the hypothesis, rules, metric, window and decision are committed before any window data;
2. the window data were not used in selection or inspected for a closely related outcome;
3. exactly one test is run on one window and reported whatever the result;
4. eligibility is point in time;
5. the implementation is verified.

**Here:**
- Condition 2 holds only partially (§1e).
- Condition 4 holds only for the V2.1 evidence-covered population.
- Condition 3 forbids a later second historical test on any remainder without a separate pre-registration disclosed as a second look.
- A PASS confirms only this cell, on this population. It does not validate the map or its other cells.

### 1e. Prior historical exposure
- **LARGE_GAP_REVERSION_V1** inspected same-trigger, same-direction **intraday** returns on 2024-01..2026-09 (UNSUPPORTED).
- **Tasks 95D and 97** computed, but never inspected, 3–10-day returns for 35 large caps on 2024–26. **Those files must not be opened.**
- **Implication:** a 2024+ result is a **partially exposed** check. A PASS is weaker evidence than a clean holdout. A FAIL or INCONCLUSIVE is not weakened.

### 1f. Prospective confirmation
- **Not automatic.** It requires a verdict-specific written rationale **and** a separately pre-registered tracking protocol (duration, minimum n, criterion, costs, borrow handling, stop rule).
- A historical PASS is not sufficient for promotion.

## 2. Rule (carried forward exactly)

| Element | Definition | Tag |
|---|---|---|
| Trigger | `open_D / close_{D−1} − 1 ≥ +0.10` on ALL-adjusted daily bars (Alpaca SIP 1Day); bars on D and on the previous market session; calendar = SPY bar dates | [MAP] |
| Entry / exit | OPEN of session D+1 (index i₀); exit CLOSE of session i₀ + 10 (11 sessions inclusive) | [MAP] |
| Direction | SHORT the stock, paired with the ETF leg (§3) | [MAP] |
| Eligibility | On the gap day D: raw close ≥ $5. ADV20 = mean(raw close × raw volume) over the 20 consecutive sessions ending D, all present. L1: $20M ≤ ADV20 < $100M | [MAP] |
| Traded bars | A bar counts only if raw volume > 0: gap needs traded D−1 and D; eligibility needs 20 traded sessions; entry placeholder → missing entry; exit placeholder or absent → DATA_MISSING_EXIT | [V2.1] |
| Window membership | Gap day D in [window start, window end] **and** H10 exit ≤ window end; otherwise BEYOND_WINDOW. No bar after the window end is read. | [MAP→W] |
| Identity at D | Ticker on D from dated rename records (no chaining through a later reuse); issuer from the latest dated Form 3/4/5 ≤ D, with no rename-away and no trading break (≥ 5 zero-volume sessions) after it. UNRESOLVED (ABSENT or CONTRADICTORY) → excluded; VERIFIED_DIFFERENT_SECURITY → corrected to the verified issuer | [V2.1] |
| Duplicates | Identical raw volume → candidate only. VERIFIED_DUPLICATE = same raw open/close within $0.005 on ≥ 20 traded sessions **and** same ticker and issuer on D. NOT_DUPLICATE never forms a graph edge. Groups need all pairs verified, else all members excluded. Representative: own ticker on D → more traded sessions → lexical | [V2.1] |
| R1a | Unnamed and not S&P-exempt: the verified issuer has a 10-K / 10-K/A / 10-Q / 10-Q/A with filing date ≤ D (any year; no recency) | [V2.1] |
| S&P exemption | Ticker on D in a point-in-time S&P 500 list at t (2018-01-01 ≤ t ≤ D), dated issuer link in [t − 365 d, D], no other issuer and no rename-away in [t, D] | [V2.1] |
| Instrument | (1) 5.06 filed ≤ D → operating; (2) 5.06 report/filing window straddles D → unresolved; (3) dated SIC 6770 ≤ D with no cessation → SPAC; (4) known non-6770 SIC → operating unless a 5.06 is effective after D → unresolved; (5) no SIC + verified S&P → operating, unknown sector; (6) else unresolved. SPAC and unresolved are excluded. **This supersedes the frozen R7 SIC-6770 mask and R1b.** | [V2.1] |
| Benchmark | SIC_ETF_MAP_V1 on the point-in-time SIC (header of the latest company filing ≤ D); known SIC outside the map → SPY; operating with unknown sector → SPY. The 2026-SIC path is kept only for original-rule parity. | [V2.1] |
| Integrity | Missing entry bar → dropped. Missing SPY **or** ETF bar at entry or exit → BENCH_MISSING (dropped). \|close change\| > 75 % from i₀−1 through exit → SUSPECT_ADJUSTMENT (retained, flagged). No synthetic bars. | [MAP] |
| Exclusion precedence | BEYOND_WINDOW → C1 no gap → C1 not eligible → C1 entry → ID unresolved → duplicate unresolved → duplicate not representative → R1a → SPAC → instrument unresolved (first reason; all flags kept) | [V2.1] |

## 3. Primary metric, costs and economic limits

- **Primary metric.**
  - `pair_gross = −(C_exit/O_entry − 1)_stock + (C_exit/O_entry − 1)_ETF` on ALL bars, entry open → H10 close. This is the frozen SHORT sector-relative gross. [MAP]
  - `pair_net = pair_gross − 0.0030 − c_ETF`.
  - Unit: per 1 unit of short-stock notional; the pair carries 2 units of gross exposure. **Not a return on capital.**

| Cost | Value | Status |
|---|---|---|
| Stock leg | 30 bps round-trip total | [MAP] C6: declared research assumption, never tuned; not measured |
| ETF leg (primary) | 4 bps round-trip total | **[ASSUME] unmeasured primary assumption: accepted (D5, 2026-10-06)** |
| ETF sensitivities | 0 / 12 / 20 bps | **Descriptive only, never gating.** Constant shifts of the primary pair_net. They do not address borrow, locate or financing. |

- **Accounting interpretation.** The metric is an **adjusted-return research proxy** on provider multiplicative back-adjusted bars.
  - Versus fixed-position cash accounting it is exact with no action and for splits, approximate for cash distributions, and divergent for special distributions and spin-offs.
  - Multiplicative factors cancel in a ratio only when the same factor applies to both endpoints. This does not establish invariance to ticker remapping, provider revisions or all download dates.
- **Descriptive subset `NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND`** (never gating):
  - stock leg by the whole-interval raw/ALL comparison (\|ALL − m·RAW\| ≤ 0.0051);
  - ETF leg by provider **cash-dividend** records only (other ETF actions unverified);
  - missing evidence → UNKNOWN.
- **Excluded and disclosed (not modelled):** borrow fees, locate, recalls and buy-ins; Reg SHO Rule 201; short rebate, margin and financing; auction fills versus daily-bar prints.
- **Statistical-pass label.** A pass is reported as **`PASS_STATISTICAL_PROXY_PRE_BORROW`**, which maps to **PASS** in the PASS / FAIL / INCONCLUSIVE scheme. It is statistical acceptance of the pre-borrow hedged adjusted-return proxy. It is **not** executable profitability.

## 4. Transport to a validation window (resolved from frozen source; no rule amendment)

| # | Point | Resolution and evidence |
|---|---|---|
| T1 | Gap-day and exit bounds | The frozen code bounds gap days and exits by the module constants `events.DEV_START/DEV_END`. The window values are substituted for the call ([MAP→W]) by `builder.window_bounds`; the code itself is unchanged. |
| T2 | Calendar | SPY bar dates of the window archive (frozen `phase_d`) |
| T3 | Eligibility look-back | 20 sessions ending D, plus D−1. For gap days early in the window this uses late-2023 bars, which are development data and not locked. |
| T4 | Download scope | As in development: the window candidate list rebuilt with window dates ([MAP→W] sources A ∪ B ∪ C ∪ D), downloading the R1-kept **and** the R1a-removed symbols (development main + diagnostic archives). Per-event eligibility comes only from the V2.1 rules. |
| T5 | Metadata evidence end; acquisition reference date | Window end, for Form 3/4/5, submissions, master.idx, filing headers and S&P lists. Renames run through the **acquisition reference date R**, because provider relabelling is resolved at download. R is named once in the release, pinned at the first request (`acquisition/reference.json`) and never moves: identity-only renames are requested with end = R exactly; endpoints that return content to the moment of retrieval are refused after R + 1 day (one off-hours session may cross 00:00 UTC). A resume after that, or with another R, stops (ACQUISITION_BLOCKED); a new acquisition needs a new release. |
| T6 | No fetch at build | All metadata is acquired and archived **before** the manifest build. The builder never fetches; a missing input is absent evidence and is handled exactly as in V2.1. |
| T7 | Unresolved handling | Identical to V2.1: excluded with a reason code, kept in a separate manifest, never scored. |
| T8 | Use of post-window renames | Only to reconstruct which ticker the requested series traded under on D (V2.1 `ticker_at`, with its reuse bound). They never establish a filing, operating status, index membership or any other admission fact: every V2.1 predicate reads only evidence dated ≤ D. |
| T9 | Submissions history completeness (acquisition, not a rule change) | For every event issuer: the main submissions JSON plus **every** history page it advertises with filingFrom ≤ window end, each verified against the advertisement fetched in the same acquisition (row count = filingCount; first filing = filingFrom; last filing ≤ filingTo + 1 day). A missing, malformed or repaginated page stops acquisition; it is never an absence and never an exclusion. Filings are de-duplicated by accession number; conflicting duplicates stop the build. This removes an evidence asymmetry in the development acquisition (pre-window pages of R3-resolved issuers were not fetched); measured on development data it changed no eligibility decision (§10). |
| T10 | Response scope | Every request declares its content envelope (the endpoint-by-endpoint table in the acquisition review). A response containing content outside the envelope is quarantined, recorded as exposure, and makes the run **RUN_INVALID** (step 0). Filtering after download does not make a broader response unexposed. |
| T11 | S&P coverage prerequisite | The S&P list is the first request after a GO. Source semantics (README and the development rows 1996–2023): every row is a **full membership snapshot** (2019–2023: 503–507 tickers) dated at an index change; the source publishes no separate coverage horizon. Coverage through the window end T is established only by a full snapshot dated on or after T, which fixes membership on every date ≤ T under the source's own change record. A last row dated before T establishes nothing, because membership after it is unknown. The format is verified first: header `date,tickers`, ISO dates strictly increasing, every row ≥ 450 tickers; a non-snapshot format is malformed. Any failure → ACQUISITION_BLOCKED before any other request: no scoring, no FAIL label, no substitute source, no automatic window switch. Membership is never assumed unchanged. |
| T12 | Byte representation of locked artifacts | Committed git blob bytes, checked out verbatim (`.gitattributes` `-text` or `text eol=lf` on every locked path). Files written for the lock are LF. Hashes are verified from a fresh checkout by `lock.py`; the digest rules (what each record excludes) are stated in `lock.py`. |

**Transport check:** no V2.1 rule needs a substantive amendment. `v2_rules.py` is date-agnostic, and its only dated constant, 2018-01-01 for S&P/Form 3/4/5 evidence, precedes every window.

## 5. Secondary diagnostics (DESCRIPTIVE; never gating; kept separate from G1–G4)

Implemented in `research/erm_nominee_validation/diagnostics.py`. The frozen definitions are called, not re-implemented:
- `research/event_response_map_v1/metrics.py` sha256 `fd876a17f21d5c8d0ce01ff61bd30518c985d2d7ed11fa1343e28caacb2469dd`;
- `research/event_response_map_v1/events.py` sha256 `701abda1482d46cc12cac08c1fb8f4821df81393f52c1d076b3a132e0d83019c`.

| Diagnostic | Exact definition | Status |
|---|---|---|
| Missing-exit bounds | `metrics.cell_metrics(obs, "SHORT", "L1")`, `MISSING_EXIT_BOUNDS`. x = directional (SHORT) sector-relative **gross** return of the valid rows. Each missing exit is filled with **0.0** (`BOUND_LONG_MINUS100_SHORT_0`) or **−1.0** (`BOUND_MIRROR_LONG_0_SHORT_MINUS100`), and the bound = mean over **valid + missing** rows. Computed only when missing-exit rate ≤ 2 %. Missing-exit rate = missing / (valid + missing), with zero denominator → 0. Missing exits are otherwise excluded from every metric. | FROZEN |
| Ex-suspect sensitivity | Same function: `sensitivity_mean_sector_relative_ex_suspect` = mean of x over valid rows **not** flagged SUSPECT_ADJUSTMENT (gross). SUSPECT_ADJUSTMENT (`events.outcomes`) = any \|close_t / close_{t−1} − 1\| > 0.75 between consecutive available session rows of ALL closes from session i₀−1 through the exit session. | FROZEN |
| Per-year means, raw, SPY-relative, median, hit rate, SD | Same function (gross, directional) | FROZEN |
| ETF-cost sensitivities | `gates.sensitivities`: pair_net recomputed with ETF cost 0 / 12 / 20 bps (constant shifts), with the frozen bootstrap CI | [AMEND] descriptive only; accepted (D5) |
| Descriptive subset | `NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND` (§3) | [V2.1] |
| Worst event | min(pair_net) over valid events, primary costs | **Convention approved (D6)** |
| Stock-leg MAE | Per valid event: max over sessions entry..exit **that have a stock bar** of (high_t / open_entry − 1), ALL bars. 95th and 99th percentiles over valid events by `numpy.percentile(..., method="linear")` (numpy default linear interpolation) | **Convention approved (D6)** |
| Break-even borrow | mean(pair_net) / mean(days_i / 360), days_i = (exit date − entry date) in calendar days per valid event (**ACT/360**), primary costs. Annualised simple rate; a value ≤ 0 means no borrow headroom. | **Convention approved (D6)**; the formula is [R1], and the day-count and sign treatment are made explicit here |

## 6. Unit book (DESCRIPTIVE; deterministic convention approved, D6)

The statistical sample is every valid event, equally weighted; G1–G4 use only that sample. The unit book is defined exactly as implemented in `diagnostics.unit_book`. **It was never frozen in code before; it is an owner-approved convention (D6), not a frozen rule.**

- **Notional.** 1 unit per leg, fixed at the entry-session **open** (stock short, ETF long). No resizing and no compounding.
- **Marks.** At each session close from the entry session through the exit session inclusive, on ALL bars. A session is marked only if **both** legs have a close; the change since the last common mark (initially the entry opens) is recognised then. So an intermediate missing bar defers the change to the next common close, and no price is synthesised.
- **Daily pair P&L (units)** = −(S_t − S_prev)/S_entry_open + (E_t − E_prev)/E_entry_open. Summed over an event this equals pair_gross exactly.
- **Costs.** The full round-trip cost (stock 30 bps + ETF primary) is booked on the **exit session**. Summed over an event, the book therefore equals pair_net.
- **Missing exits and dropped events** are not in the book. They are counted in G4 and §5.
- **Cumulative unit P&L** = running sum of daily book P&L over window sessions in order, starting at 0. It is not compounded and has no capital base.
- **Maximum drawdown (units)** = max over t of (max(0, max_{s≤t} cum_s) − cum_t).
- **Concurrency** = the number of valid events with entry ≤ t ≤ exit at each session t. Mean, median and max are taken over every session from the first entry session to the last exit session inclusive.
- **Therefore:** no percentage return or drawdown on capital and no capital-constrained risk claim.

## 7. Gates and classification

| # | Gate | Boundary | Tag |
|---|---|---|---|
| G1 | mean(pair_net) > 0 | strict; n_valid = 0 → false | [R1] |
| G2 | lower bound of the two-sided 95 % CI > 0 | strict; CI withheld (< 5 dates) → false | [R1]; method [MAP] |
| G3 | mean after removing the 5 largest pair_net > 0 | zero is a flip; n_valid ≤ 5 → false | [R1] |
| G4 | missing / (valid + missing) ≤ 0.02 | inclusive; zero denominator → 0 | [R1] |

Values are float64 as computed, with no rounding.

**Classification, first match wins** (implemented in `research/erm_nominee_validation/gates.py`):

| Step | Condition | Verdict | Tag |
|---|---|---|---|
| 0 | Fingerprint, config hash or archive verification fails; a response exceeded the authorised scope (T10); or the run ends before its marker. One re-execution only if no outcome file exists. A request the guard refused before sending exposes nothing and is classed ACQUISITION_BLOCKED, not RUN_INVALID. | RUN_INVALID | [AMEND] **approved (D6)**; retries per §10 D6a |
| 1 | G4 fails | FAIL (integrity) | [R1] |
| 2 | **Adopted (D4):** n_valid < 100 or distinct entry dates < 40 | INCONCLUSIVE (insufficient sample) | [AMEND] **adopted (D4)**; proposed after discovery |
| 2′ | n_valid = 0 | INCONCLUSIVE | [AMEND] **approved (D6)** |
| 3 | mean ≤ 0, or CI upper bound < 0 | FAIL | [R1] |
| 4 | G1 ∧ G2 ∧ G3 ∧ G4 | **PASS_STATISTICAL_PROXY_PRE_BORROW** (= PASS) | [R1] |
| 5 | otherwise | INCONCLUSIVE | [R1] |

Nothing in §2–§7 may change after window data is read.

## 8. Planning estimates (supersedes the r1–r7 power table)

**Superseded.** The r1–r7 table (power 0.35 / 0.12 for A; 0.74 / 0.25 for B) used the **uncorrected** Gate D effect (+2.85 % gross) and frequency. It is withdrawn.

**Inputs.** These are stored corrected development values only (`corrected_cell.json`). There is no new bootstrap or simulation, and no validation counts or prices are used.
- Mean sector-relative gross m = 0.0196302207858569.
- CI = [0.005755284278680304, 0.033240887988333204].
- n = 1,999; distinct dates = 806.

**Formulas:**
1. **Effective session span** = sessions whose gap day can have H10 exit ≤ window end = sessions in the window − 11 (XNYS calendar, `exchange_calendars`, which is not market data).
   - Development: 1,258 − 11 = **1,247** (2019-01-02..2023-12-13).
   - A: 252 − 11 = **241**.
   - B: 689 − 11 = **678**.
2. **Rates per effective session:** events 1,999 / 1,247 = 1.6030; dates 806 / 1,247 = 0.64635. Expected window events E[n] and dates E[dates] are these rates × the window span. This assumes the development frequency of eligible, evidence-covered events carries over.
3. **Development SE** = (CI_high − CI_low) / (2 × 1.959964) = **0.70118 %**.
   - This is a **normal approximation to a percentile interval that is slightly asymmetric** (mean − low 1.3875 pp; high − mean 1.3611 pp).
4. **Window SE** = SE_dev × √(806 / E[dates]), date-clustered scaling. Scaling by events gives the same value, because both rates are proportional to sessions.
5. **Effects:** μ_full = m − 0.0030 − 0.0004 = **1.6230 %**; μ_half = **0.8115 %**.
6. **Approximate power for G2 only** ≈ Φ(μ / SE_w − 1.959964): the approximate probability that the G2 lower bound exceeds 0 under the frozen two-sided 95 % lower-bound gate (nominal one-sided 2.5 %), **if** the true mean equals the assumed μ.
   - It ignores G1, G3, G4 and the sample floor; no claim is made about how often they hold.
   - It is **conditional power to clear the CI gate**: not the probability that the strategy works, and not the probability of an overall PASS.

**Approximate power for G2 only** (existing calculation, unchanged):

| | **A**: 2024-01-02..2024-12-31 | **B**: 2024-01-02..2026-09-30 |
|---|---|---|
| Effective sessions | 241 | 678 |
| ≈ E[valid events] / E[dates] | 386 / 156 | 1,087 / 438 |
| ≈ SE of mean(pair_net) | 1.595 % | 0.951 % |
| ≈ G2 power at μ_full = 1.623 % | **0.17** | **0.40** |
| ≈ G2 power at μ_half = 0.811 % | 0.07 | 0.13 |
| Above the adopted floor (100 / 40)? | yes (expected) | yes (expected) |
| Locked data used | EXCLUDED_2024 | EXCLUDED_2024 + FUTURE_CONFIRMATION through 2026-09-30 |
| Reserve left | 2025-01-02 onward, partially exposed | none; prospective tracking only |
| Task75 reserved windows | consumed | consumed |

**Limitations of these estimates:**
- **Overlapping holding periods:** 11-session holds overlap across adjacent entry dates. Date clustering does not capture that cross-date dependence (§1c), so the true SE is likely larger. For a given true effect, the realised G2 rate is then uncertain in both directions: a too-narrow CI also lets G2 pass more easily.
- **Regime shifts:** development year means ranged from +0.10 % to +3.18 % after correction, and the 2024–26 gap frequency and response may differ.
- **Selection:** the corrected estimate is still from a selected cell, so expect shrinkage. The half-effect column is a realistic planning case.
- **Coverage:** the evidence-covered share (identity, instrument) and the foreign-private-issuer mix may differ in the window, changing E[n].
- **Approximation:** a normal approximation to a percentile bootstrap.

**Window recommendation (reasoned; not a decision).** **B**, if the owner proceeds with historical validation at all.
- A has approximate G2 power of only about 0.17, even if the full corrected effect were true. A real effect would most likely end INCONCLUSIVE, while consuming 2024 and the Task75 reserve for little information.
- B roughly doubles the information: G2 power is about 0.40 **conditional on** the full corrected effect, which is not a probability of PASS.
- **Trade-off:** B consumes the entire FUTURE_CONFIRMATION reserve (no later historical look; prospective only), and its whole span is exposed to the intraday LARGE_GAP_REVERSION_V1 study.
- **Neither window reaches conventional power.** INCONCLUSIVE is the most likely outcome under both, and at the half effect under either.

## 9. Exposure and Task75 reserved windows

- **Do not open:** the stored 95D/97 files must not be opened.
- **Task75 overlap:** both windows contain the Task75 holdout windows 2024-06-01..09-02 and 2024-10-21..12-20. Task75 is retired, but its guard is still PREFLIGHT, with the windows locked.
- **Consumption needs acknowledgement:** reading 2024 data **consumes** them, so this requires the owner's explicit acknowledgement (D2) and an audit entry in the Task75 holdout state at guard release.
- **Identity metadata:** renames inside these windows were not queried in development. Under validation they are required identity inputs, also covered by D2.
- **Broad metadata (D7).** Some required metadata endpoints cannot restrict returned dates: the current asset list, SEC reference files, submissions JSON (history to retrieval) and the S&P history file. Under either window they return content after the window end (to R + 1 day), including the FUTURE_CONFIRMATION period. They influence identity reconstruction and the frozen eligibility evidence only through rows dated ≤ D (or ≤ window end for the R3 download scope). They need an explicit category/date authorisation (D7), separate from price and outcome access.
- **This draft consumes nothing.**

## 10. Procedure and implementation status

**Implemented and tested (branch `research/erm-nominee-validation-plumbing`; review, not locked):**

| Module | Role |
|---|---|
| `config.py` | Immutable window/config, owner-decision fields, canonical config hash; `require_decided()` |
| `guard.py` | Fail-closed acquisition and load checks via the immutable ERM guard; `check_authorisation_scope` (hypothesis, window, config hash, explicit owner GO). Production `authorise()` refuses **even a correctly scoped record**, because no reviewed guard transition exists. |
| `inventory.py` | Required inputs, coverage and category (price/outcome; identity metadata; descriptive metadata) |
| `builder.py` | Window-parameterised V2.1 manifest. Reuses the frozen `v2_rules`, `events` and `universe` code unchanged; local inputs only. |
| `adapters.py` | `ARCHIVE_MANIFEST.json` (per-file sha256, required inputs, completeness). `ProductionLoader` verifies every file hash **before** parsing, then loads bars through the frozen `data.load` LOAD guard and metadata from local bytes. |
| `gates.py` | pair_net, G1–G4, verdict precedence, `PASS_STATISTICAL_PROXY_PRE_BORROW` → PASS |
| `diagnostics.py` | §5/§6 descriptive outputs |
| `workflow.py` | The run state machine below |
| `run.py` | DEV parity mode. `--execute` uses production components and fails closed. Owner decisions are read only from a committed decision record; none exists. |

**Workflow (`workflow.py`).** Owner decisions → scoped authorisation, **before** any request, read or run-state write → ACQUIRE (archive + manifest; incomplete → stop) → LOAD (hash-verified, guarded) → BUILD (V2.1 manifest + invariants) → OUTCOMES (frozen `events.outcomes`) → GATES → DIAGNOSTICS → REPORT → `RUN_COMPLETE.json` written **last**, with the hash of the final run record.

**Run-state rules:**
- A completed run is never overwritten.
- A failure **after** outcomes exist → `INCOMPLETE_<stage>`, `outcome_exposure = true`; no retry (the owner decides).
- A failure **before** outcomes → one re-execution; the partial outputs are moved to `attempt_1/` and preserved.
- A second failure → `ABORTED_OWNER_DECIDES`.
- Partial outputs are explicitly labelled "PARTIAL OUTPUTS -- NOT A RESULT", with no report and no marker.
- The workflow is in-process (no subprocess). Failures propagate as `StageFailure` and to the CLI.

**Production acquisition (implemented; review package `ERM_NOMINEE_ACQUISITION_FINAL_REVIEW.md`):** staged acquirer S0 (S&P coverage) → S1 base metadata → S2 R1 scope → S3 bars (frozen Downloader) → S4 candidate dates only → S5 complete issuer histories + point-in-time headers → S6 ETF dividends (optional) → S7 completeness → S8 archive manifest. Every request is guarded before it exists and response-checked after it (T10). Scoped release (`release.py`) built and **inactive**: no release store, protocol lock, decision record or GO exists.

**Run failure classes (recorded on every failed run; none is a statistical verdict):** IMPLEMENTATION_FAILURE (code / invariant error before outcomes); ACQUISITION_BLOCKED (a required input not acquirable with verified, sufficient coverage inside the authorised scope; no outcome); RUN_INVALID (step 0); INCOMPLETE_AFTER_OUTCOME_EXPOSURE (any failure once outcomes may exist; no retry). PASS / FAIL / INCONCLUSIVE exist only in a COMPLETE run.

**Execution attempts (D6 / D6a, recorded 2026-10-06).** The bounded transport retry policy is unchanged. The D6a policy, exactly:

1. An acquisition blockage before any outcome has been computed, persisted, displayed or otherwise exposed does not consume the single statistical scoring run.
2. At most one acquisition retry is permitted, under the same locked rules and approved scope (at most two executions in total; each execution acquires afresh into its own archive).
3. The retry requires an explicit recorded reason. The requests, retrieved data and exposure of every attempt are recorded and preserved (`attempt_<n>/`), never deleted.
4. The attempt budget is held in one attempt ledger per hypothesis and window, outside every run directory (`results/erm_nominee_validation/ATTEMPT_LEDGER.jsonl`). A new run ID, a renamed directory or a restarted process does not reset it.
5. No retry of any kind once outcomes may exist (the scoring stage has started). The owner decides.
6. A second failure before outcomes stops for owner review (ABORTED_OWNER_DECIDES).
7. Separate counters are kept: `acquisition_attempts` (executions started) and `scoring_attempts` (the outcome stage entered; at most one, ever).
8. A request-level transport retry is not an acquisition attempt. It is the existing bounded policy: 4 attempts, 2/4/8 s backoff, `Retry-After` ≤ 60 s, recorded per request. It happens inside one execution.
9. Reference date. An execution whose acquisition would fall outside the authorised envelope (retrieval after R + 1 day) is refused before it starts and consumes nothing. R is never re-pinned and access is never widened; a separate scope decision (a new release and GO) is required.

**Evidence:** the acquisition review records the tests (fixtures through the production orchestration), the recorded development replay (manifest byte-identical to development parity) and the development-only network smoke test.

**Sequence:**
1. Owner decisions D1, D2, D4–D7 recorded (decision record). **Done, 2026-10-06.**
2. Lock this protocol plus the decision record, and the implementation (fingerprint and config hash). **Done:** lock records.
3. Separate, explicit GO naming the exact scope with an instantiated reference date R (from the locked scope template), then the reviewed guard activation (ERM + Task75 audit records). **Not done; requires the owner.**
4. Acquire (S0 first), build, score once and report (§7), with prospective tracking only per §1f.

## 11. Owner decisions

**Recorded 2026-10-06** (`ERM_NOMINEE_OWNER_DECISION_RECORD_B.md`). These authorise locking only; this is **not a GO**.

| # | Decision | Status |
|---|---|---|
| D1 | Validation window **B** (2024-01-02..2026-09-30) | **RECORDED** |
| D2 | Acknowledge that the later authorised acquisition consumes the overlapping Task75 reserved windows and the reserved 2025–September 2026 data; nothing is consumed now | **RECORDED** |
| D4 | Minimum sample 100 valid events and 40 distinct entry dates → otherwise INCONCLUSIVE | **RECORDED (adopted)** |
| D5 | ETF cost 4 bps round trip (unmeasured primary assumption); 0/12/20 bps descriptive only; stock cost 30 bps | **RECORDED (accepted)** |
| D6 | Procedural and diagnostic conventions, including T5/T8–T12, subject to D6a | **RECORDED (approved)** |
| D6a | Acquisition-retry rule exactly as in §10 | **RECORDED** |
| D7 | Bounded broad-metadata scope for a future, separately authorised acquisition: `assets_current`, `sec_reference_current`, `submissions`, `sp500_pit` through R + 1; `identity_renames` from 2026-10-01 through R. Eligibility only from V2.1-permitted evidence; no future-assisted admission | **RECORDED (accepted)** |
| S&P | Insufficient coverage → ACQUISITION_BLOCKED; no scoring, statistical FAIL, alternative source or window switch | **RECORDED (accepted)** |

**Locks.** The protocol lock binds:
- this file;
- the decision record;
- the V2.1 rule sources;
- the config hash;
- the scope template, with R symbolic.

The implementation lock binds the implementation aggregate and every file hash. `release.py` refuses a release whose implementation or config hash differs from them.

**Recorded (2026-10-05):**
- A1: correction spec V2.1 adopted.
- A2: evidence-covered population accepted.
- A3: one corrected development run authorised and **completed** (CORRECTED_DEVELOPMENT_SCREEN_PASS).

**Fixed rules (not decisions):**
- trigger, entry, H10, direction, L1 and the $5/ADV20 formulas;
- window membership;
- V2.1 rules;
- sector map;
- 30 bps stock cost;
- estimator, CI level, seed and ordering;
- G1–G4 thresholds;
- verdict precedence steps 1, 3, 4 and 5.

**Implementation prerequisites (not decisions):** §10.

## 12. Change log r10 → final (status and procedural precision only)

| § | Change |
|---|---|
| Status, §11 | Owner decisions D1, D2, D4–D7 recorded (2026-10-06); locked; NOT A GO |
| Basis | Authoritative V2.1 rule sources referenced with sha256 |
| Tags | [AMEND]/[ASSUME] items approved or accepted (D4/D5/D6); "If adopted" → "Adopted"; distinct dates = distinct entry dates (as implemented) |
| §4 | T11 states the source semantics (full snapshots at change dates) and the format check; T12 byte representation |
| §7 | Step 0 tag: approved, retries per §10 D6a |
| §10 | Exact D6a policy replaces "unchanged pending D6a"; sequence status |

## 12a. Change log r9 → r10 (procedure only)

| § | Change |
|---|---|
| §4 | T5: renames and broad endpoints bounded by one pinned acquisition reference date R (+1 day retrieval window). New T8 (post-window renames reconstruct the ticker on D only), T9 (complete, verified submissions history for every event issuer; de-duplication), T10 (response-scope envelope → RUN_INVALID), T11 (S&P coverage is the first prerequisite → ACQUISITION_BLOCKED). |
| §7 | Step 0 wording: "guard scope exceeded" means a response outside the authorised envelope; a guard refusal before sending is ACQUISITION_BLOCKED. Precedence and steps 1–5 unchanged. |
| §9 | Broad-metadata exposure stated; authorisation D7. |
| §10 | Production acquisition and inactive release implemented; failure classes; re-execution rule unchanged pending D6a. |
| §11 | D6 extended to the acquisition procedure; D6a and D7 added; approval statement updated (NOT YET GIVEN). |

## 12b. Change log r8 → r9

| § | Change |
|---|---|
| §1c | Inference limitation stated: entry-date clustering does not capture overlapping-hold dependence. Frozen estimator, seed and level unchanged. Any PASS is conditional on the limitation, prior exposure, coverage and the proxy. |
| §5–§6 | Exact diagnostic definitions. FROZEN ones reference `metrics.py` / `events.py` with sha256; never-frozen ones (unit book, drawdown, concurrency, worst event, MAE percentile convention, break-even ACT/360) are labelled PROPOSED (D6). Kept separate from gates. |
| §8 | Table labelled "approximate power for G2 only"; the claim that G3/G4 are nearly implied is removed; 0.40 explained as conditional G2 power, not P(strategy works) or P(PASS). Calculations unchanged. |
| §10 | Workflow implemented and tested; remaining implementation named (production acquisition adapters, guard transition, development dry run); execution not ready |
| §11 | Proposed approval statement added (NOT YET GIVEN), with the note on the implementation lock |
