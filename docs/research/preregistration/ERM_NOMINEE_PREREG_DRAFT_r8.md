# PRE-REGISTRATION DRAFT r8: GAP_UP_10|SHORT|H10|L1_V1 (NOT APPROVED / NOT LOCKED)

**Status.** This is an owner-decision draft for review.
- It is **not approved and not locked**. No validation-lock marker exists.
- `WINDOW_CHOICE = OWNER_DECISION_PENDING`.
- The Task75 reserve-consumption acknowledgement is **pending**.
- No 2024+ data has been read for this hypothesis, and no validation-window input has been acquired.
- The EVENT_RESPONSE_MAP_V1 guard (EXCLUDED_2024; FUTURE_CONFIRMATION from 2025-01-02) stays locked. Releasing it needs, after this protocol and its implementation are finally locked:
  - a separate, explicit, hypothesis- and window-scoped authorisation;
  - a reviewed guard transition.

Historical validation then needs a separate GO.

**Basis (verified 2026-10-05).**
- **Gate D:** `research/event-response-map-v1` @ `06c2ece`. Design lock rev 3.2, fingerprint `12a909e7…cb8ad`.
- **Correction spec V2.1 (authoritative; supersedes V1 and V2, both preserved):** `research/erm-nominee-integrity-audit` @ `aab578e`.
  - Spec sha256 `b805ce415fb067d6e0fad90859ddc7d35a31e3195c946cbe3460172c7a72ded2`.
  - Freeze record `8581e3d3…31f5`.
  - Manifest `9ed45652ff1ddf4237a71ad920e7b30d506133f774ac7e3f760aa092f0e8579d`.
  - Rules `v2_rules.py` (`RULES_VERSION = ERM_NOMINEE_CORRECTION_V2.1`) sha256 `a4e3b82d…48ef`.
- **Corrected development run:** `research/erm-nominee-corrected-dev-run` @ `b91dc0a`. Verdict **CORRECTED_DEVELOPMENT_SCREEN_PASS**; marker `RUN_COMPLETE.json`; `corrected_cell.json` `da63533d…cc9e`.
- **Validation plumbing (review, not locked):** branch `research/erm-nominee-validation-plumbing` (§10).
- Earlier drafts r1–r7 are preserved unchanged outside the repository: r7 `7fdbad17…e24f`.

**Rule tags:**

| Tag | Meaning |
|---|---|
| [MAP] | Frozen before discovery (design lock rev 3.2 / nomination protocol) |
| [MAP→W] | [MAP] rule with the validation window's dates substituted |
| [V2.1] | Frozen correction rule (owner-adopted A1, 2026-10-05) |
| [R1] | Draft rule written after Gate D, before any validation data |
| [AMEND] | Proposed amendment; **pending owner approval** |
| [ASSUME] | Modelling assumption; **pending owner acceptance** |
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
| ETF leg (primary) | 4 bps round-trip total | **[ASSUME] unmeasured primary assumption: owner acceptance pending (D5)** |
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
| T5 | Metadata evidence end | Window end, for Form 3/4/5, submissions, master.idx, filing headers and S&P lists. Renames run through the **bar download date**, because provider relabelling is resolved at download. |
| T6 | No fetch at build | All metadata is acquired and archived **before** the manifest build. The builder never fetches; a missing input is absent evidence and is handled exactly as in V2.1. |
| T7 | Unresolved handling | Identical to V2.1: excluded with a reason code, kept in a separate manifest, never scored. |

**Transport check:** no V2.1 rule needs a substantive amendment. `v2_rules.py` is date-agnostic, and its only dated constant, 2018-01-01 for S&P/Form 3/4/5 evidence, precedes every window.

## 5. Secondary (reported, not gating)

- Raw naked short: `−r_stock − 0.0030`.
- SPY-relative directional return.
- Break-even annual borrow: `mean(pair_net) / mean(calendar_days_held / 360)`.
- Missing-exit bounds.
- Ex-suspect sensitivity.
- Per-year means.
- ETF-cost sensitivities.
- The descriptive subset (§3).

## 6. Unit book (descriptive only)

- **Statistical sample:** every valid event, equally weighted. G1–G4 use only this sample.
- **Unit book:** 1 unit = the entry notional of one leg. Book P&L is in these units and is not compounded. There is no capital base, cap, leverage limit or admission priority.
- **Therefore:** no percentage return or drawdown on capital and no capital-constrained risk claim.
- **Outputs:** cumulative unit P&L and its maximum drawdown (units); concurrent open pairs; worst event; stock-leg MAE percentiles.

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
| 0 | Fingerprint, config hash or archive verification fails; guard scope exceeded; or the run ends before its marker. One re-execution only if no outcome file exists. | RUN_INVALID | [AMEND] **pending (D6)** |
| 1 | G4 fails | FAIL (integrity) | [R1] |
| 2 | **If adopted (D4):** n_valid < 100 or distinct dates < 40 | INCONCLUSIVE (insufficient sample) | [AMEND] **pending (D4)**; proposed after discovery |
| 2′ | n_valid = 0 | INCONCLUSIVE | [AMEND] **pending (D6)** |
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
6. **Power** ≈ Φ(μ / SE_w − 1.959964). This is the approximate probability that the G2 lower bound exceeds 0, under the frozen two-sided 95 % lower-bound gate (nominal one-sided 2.5 %). It ignores G1, G3 and G4, which are nearly implied when G2 holds.

| | **A**: 2024-01-02..2024-12-31 | **B**: 2024-01-02..2026-09-30 |
|---|---|---|
| Effective sessions | 241 | 678 |
| ≈ E[valid events] / E[dates] | 386 / 156 | 1,087 / 438 |
| ≈ SE of mean(pair_net) | 1.595 % | 0.951 % |
| ≈ power at μ_full = 1.623 % | **0.17** | **0.40** |
| ≈ power at μ_half = 0.811 % | 0.07 | 0.13 |
| Above the proposed floor (100 / 40)? | yes (expected) | yes (expected) |
| Locked data used | EXCLUDED_2024 | EXCLUDED_2024 + FUTURE_CONFIRMATION through 2026-09-30 |
| Reserve left | 2025-01-02 onward, partially exposed | none; prospective tracking only |
| Task75 reserved windows | consumed | consumed |

**Limitations of these estimates:**
- **Overlapping holding periods:** 11-session holds overlap across adjacent entry dates. Date clustering does not capture that cross-date dependence, so the true SE is likely larger and power lower.
- **Regime shifts:** development year means ranged from +0.10 % to +3.18 % after correction, and the 2024–26 gap frequency and response may differ.
- **Selection:** the corrected estimate is still from a selected cell, so expect shrinkage. The half-effect column is a realistic planning case.
- **Coverage:** the evidence-covered share (identity, instrument) and the foreign-private-issuer mix may differ in the window, changing E[n].
- **Approximation:** a normal approximation to a percentile bootstrap.

**Window recommendation (reasoned; not a decision).** **B**, if the owner proceeds with historical validation at all.
- A has power of only about 0.17 even at the full corrected effect. A real effect would most likely end INCONCLUSIVE, while consuming 2024 and the Task75 reserve for little information.
- B roughly doubles the information (power about 0.40 at the full effect).
- **Trade-off:** B consumes the entire FUTURE_CONFIRMATION reserve (no later historical look; prospective only), and its whole span is exposed to the intraday LARGE_GAP_REVERSION_V1 study.
- **Neither window reaches conventional power.** INCONCLUSIVE is the most likely outcome under both, and at the half effect under either.

## 9. Exposure and Task75 reserved windows

- **Do not open:** the stored 95D/97 files must not be opened.
- **Task75 overlap:** both windows contain the Task75 holdout windows 2024-06-01..09-02 and 2024-10-21..12-20. Task75 is retired, but its guard is still PREFLIGHT, with the windows locked.
- **Consumption needs acknowledgement:** reading 2024 data **consumes** them, so this requires the owner's explicit acknowledgement (D2) and an audit entry in the Task75 holdout state at guard release.
- **Identity metadata:** renames inside these windows were not queried in development. Under validation they are required identity inputs, also covered by D2.
- **This draft consumes nothing.**

## 10. Procedure

**Implementation (prepared for review, not locked).** `research/erm-nominee-validation-plumbing`:

| Module | Role |
|---|---|
| `research/erm_nominee_validation/config.py` | immutable window/config; owner-decision fields; canonical config hash; `require_decided()` rejects pending decisions |
| `guard.py` | fail-closed acquisition and load checks delegating to the immutable ERM guard. **Release is disabled.** A release record alone is not sufficient: a reviewed guard transition is required. |
| `inventory.py` | required inputs and coverage by category (price/outcome versus identity versus descriptive metadata), without querying |
| `builder.py` | window-parameterised V2.1 manifest using the frozen `v2_rules`, `events` and `universe` code unchanged; local inputs only; deterministic output |
| `gates.py` | pair_net, G1–G4 and verdict precedence, with the PASS label mapping |
| `run.py` | DEV parity mode; A/B fail closed (pending decisions, then the guard) |

**Before the lock:**
1. The owner decides D1–D6.
2. Review and freeze the plumbing, with a fingerprint and config hash.
3. Development parity through the plumbing passes (recorded).

**After the lock and an explicit, scoped GO:**
1. Reviewed guard transition; Task75 audit entry.
2. Acquire and archive the window metadata (§4 T5), then the bars (T4).
3. Build the window manifest, then compute §3, §5, §6 and §7 exactly once and classify.
4. Prospective tracking only per §1f.

## 11. Owner decisions

**Pending.** Recommendations are not approvals.

| # | Decision | Proposed default | Status |
|---|---|---|---|
| D1 | Validation window A or B | **B** (§8), with the reserve trade-off | **PENDING** |
| D2 | Acknowledge consumption of the Task75 reserved windows (required under A or B) | Acknowledge | **PENDING** |
| D4 | Minimum-sample floor (n < 100 or dates < 40 → INCONCLUSIVE; proposed after discovery) | Adopt | **PENDING** |
| D5 | ETF cost: primary 4 bps (unmeasured); 0/12/20 bps descriptive | Accept as labelled | **PENDING** |
| D6 | Procedural amendments: RUN_INVALID (step 0), n = 0 (step 2′), unit-book conventions, verification checks | Approve | **PENDING** |

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

## 12. Change log r7 → r8

| § | Change |
|---|---|
| All | Consolidated into one self-contained protocol; labelled NOT APPROVED / NOT LOCKED |
| §1b | Corrected development result added, with explicit non-claims (survivorship vacuous; neighbours not rechecked; subset not positive after cost; no multiplicity claim) |
| §1c, §7 | Validation uses its own gates G1–G4, not the development screen; `PASS_STATISTICAL_PROXY_PRE_BORROW` label mapped to PASS |
| §2 | V2.1 rules stated in full; R7 mask and R1b marked superseded by the V2.1 instrument hierarchy |
| §4 | Transport points T1–T7 resolved from frozen source; no rule amendment |
| §8 | **Power table replaced** using the corrected development values; old table superseded |
| §10 | Validation plumbing (review) described; guard release disabled |
| §11 | D1, D2 and D4–D6 pending with proposed defaults; A1–A3 recorded |
