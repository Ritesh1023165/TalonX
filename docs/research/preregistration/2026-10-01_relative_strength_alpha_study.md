# Pre-registration: Relative Strength & Market Context Alpha Study (RS_ALPHA_V1)

**Status:** FROZEN. This file, `talonx_paperperf/rs_study.py` and `rs_sector_mapping_v1.json` were committed **before**
any Phase A outcome, RS value, quintile or future return was computed. The commit is the registration evidence.

**Scope:** research only.
- No live Signal change, no Telegram, no orders.
- CONTROL, SQF_V1 and DTU_V1 are unchanged.

| Frozen identity | Value |
|---|---|
| `HYPOTHESIS_VERSION` | `RS_ALPHA_V1` |
| Spec fingerprint (`rs_study.spec_fingerprint()`) | `711e5b0c5ee04277` |
| `SECTOR_MAPPING_VERSION` | `SIC_ETF_MAP_V1` |
| `SECTOR_MAPPING_HASH` | `5c861b56a91c8858` |
| `COST_MODEL_VERSION` | `PAPERPERF_FORENSIC_COST_V1` (hash `3e57efbe3f2a203d`) |

Tests in `tests/test_relative_strength_study.py` pin all three hashes. Any change to a definition below makes a new
hypothesis version.

## 1. Hypothesis

> "Stocks exhibiting causal idiosyncratic outperformance versus market and sector benchmarks at candidate/event time
> have higher subsequent return expectancy than otherwise similar opportunities."

- Relative strength is treated as **predictive information**, not proof of a mechanism.
- No claim of institutional accumulation is made.

## 2. Population: upstream DTU candidates, not PAPER_SIGNAL

**Source:** `opportunity.db` `candidate_events`, which is discovery output upstream of promotion.
- Event types: `NEW`, `UPGRADE`, `MATERIAL_UPDATE`.
- States: `WATCH`, `BULLISH_SETUP`, `BEARISH_SETUP`. All directions are included; the outcome is long-only.

**t0:** the event's `at_utc`.

**Qualifying:** an event qualifies if all of these hold:
- The symbol is in DTU **ACTIVE_CORE** or **EVENT_PROMOTED** at t0. Anything else is `OUT_OF_DTU` and is counted, not
  used.
- The primary 15-minute lookback starts at or after the regular open.
- The actionable entry plus 30 minutes falls at or before the regular close.
- The 15-minute sector RS can be computed causally. Otherwise the observation is reported as `INSUFFICIENT_BARS`.

**Primary observation:**
- It is the **first qualifying event per (symbol, session)**, by (t0, seq).
- Later same-session events are descriptive only and never count as independent trades.
- Reported counts: `PRIMARY_OBSERVATIONS` and `UNIQUE_SYMBOL_SESSIONS`.

**Phase A sessions:** 2026-09-28 and 2026-09-29 (discovery). 2026-09-30 is not used.

### DTU reconstruction (causal; no 2026-09-30+ state)

| Session | Core (D-1 frozen, top 1200 by ADV20 within V1 floors) | GAP ≥3% (TTL rest of window) | SEC_8K (TTL 3 sessions) |
|---|---|---|---|
| 09-28 | `universe_snapshot_2026-09-28.csv` (D-1 = 09-25) from the DTU study | first scan observation with \|gap\| ≥3% at or before t0 (near-miss SCORED + candidate gap, the DTU study replay) | 8-K filed on an earlier session within TTL (EDGAR daily index). **Same-day 8-Ks cannot be reconstructed intraday: reported as a coverage gap.** |
| 09-29 | shadow `snapshot.is_shadow_core` (built from D-1 = 09-28) | shadow `GAP_TRIGGER` first_at_utc ≤ t0 | shadow `SEC_8K` ≤ t0, plus carry-in from the D-1 batch |

## 3. Benchmarks (deterministic)

The **SIC → ETF** mapping is static, with one benchmark per SIC and no dynamic choice. Artifact:
`rs_sector_mapping_v1.json`.

| SIC | ETF |
|---|---|
| 1000–1499, 2900–2999 | XLE |
| 2830–2836 | XBI |
| 3840–3851 | XLV |
| 3570–3579, 7370–7379 | XLK |
| 3600–3699, 3700–3799 | XLI |
| 6000–6799 | XLF |
| **everything else / unknown** | **SPY** |

**SIC source:** EDGAR submissions JSON `sic` field, by the CIK in `market.db` `universe`. This is static metadata and is
not point-in-time. The minimal table above sends many names to SPY; the share mapped to SPY is reported, and the
mapping is not extended.

| Role | Benchmark |
|---|---|
| **PRIMARY** | sector ETF (the map) |
| **SECONDARY** | SPY |
| **DIAGNOSTIC** | QQQ |
| **DIAGNOSTIC** | DTU Core equal-weight |

**DTU Core equal-weight index:**
- Built from the **D-1 frozen Core membership only**; no same-day additions.
- At each timestamp it includes only the constituents with valid aligned prices at **both** endpoints. Nothing is
  forward-filled.
- `CORE_INDEX_COVERAGE_PCT` is reported.

## 4. Causal alignment

**Feature views:**
- **ENGINE_VIEW (PRIMARY):** the endpoint is the event's `data_as_of_utc`, which is t0 − 16 minutes. This is the 15-minute
  delayed SIP the engine saw, and the only view an unpaid live implementation could compute.
- **WALLCLOCK_VIEW (DIAGNOSTIC ONLY):** the endpoint is t0. It needs real-time data. It never gates and never promotes.

**Price at time x:** the close of the last 1-minute bar **closed** by x (bar start + 1 minute ≤ x). That bar must have
closed no earlier than x − 5 minutes; otherwise the price is **MISSING**, never filled.

**Interval:**
- E* is the close time of the stock's last closed bar at or before the view endpoint.
- S* is the close time of the stock's last closed bar at or before E* − L.
- **Every benchmark is priced at bars closed by E* and by S*.** A benchmark bar is never newer than the stock bar.
- A lookback start before the regular open means the feature is missing.

**Lookbacks:**
- 5, 15 and 30 minutes.
- **15 minutes is primary** and drives the quintiles and all six variants.
- 5 and 30 minutes are diagnostic.

**Features:**
- `sector_excess = R_stock − R_sectorETF`
- `market_excess = R_stock − R_SPY`
- `rs_ratio = (1+R_stock)/(1+R_sector)`
- No beta adjustment.

**RVOL_15m:** stock volume in (E* − 15m, E*], divided by (D-1 ADV20 shares × 15/390).

**RS-5 spread-to-price:** the median SIP NBBO (ask − bid)/mid in [E* − w, E*], with w in (2, 30, 300) seconds. This is
backward-looking. If it is unmeasured, the event fails RS-5.

## 5. Outcome and cost

**Entry:** the open of the first 1-minute SIP bar starting in [ceil_minute(t0), +10 minutes). This is the forensic's
actionable rule.

**Exits:**
- **Primary endpoint: +30 minutes gross**, the close of the last bar completed by entry + 30 minutes.
- Descriptive only: +15 minutes, +60 minutes and the session close.
- No exit is chosen after the fact.
- Multi-day behaviour is out of scope; if it looks interesting, it is recorded only as a separate future hypothesis.

**Cost (`PAPERPERF_FORENSIC_COST_V1`):** this is the authoritative Sep 28–29 profitability contract, unchanged.
- Round-trip cost = max(**20 bps** V2 `friction_bps`, **measured SIP NBBO spread at entry**).
- The spread is taken from `signal_forensics.quote_spread` over windows of 2, 30 and 300 seconds.
- If the spread is unmeasured, cost is friction only, flagged `COST_PARTIAL`.

**Metrics:**
- Net = gross − cost.
- Win rate and profit factor are computed on net.
- P&L assumes $10k per trade.

## 6. Primary RS information test: the quintile gradient

**Ranking:**
- Primary observations with a valid 15-minute sector_excess and a resolved +30-minute outcome are sorted by
  (sector_excess, session, symbol).
- Quintile = floor(5·rank/N)+1, so Q1 has the lowest RS.
- Reported per quintile: N, mean and median gross +30m, mean net, win rate and profit factor.

**`QUINTILE_GRADIENT_GATE` passes only if all three hold.** Literal monotonicity is not required.
1. The Spearman rank correlation between quintile number and quintile mean gross is greater than 0.
2. Q5 mean gross is greater than Q1 mean gross.
3. Q5 mean net is greater than 0.

`Q5_MINUS_Q1_GROSS` is reported.

**If the gate fails**, fixed thresholds are descriptive only and cannot earn Phase B.

## 7. Incremental information beyond the TalonX score

**Score bands:** the event's `score` falls into one of [0,50), [50,60), [60,70), [70,80) or [80, max).

**Per band:**
- HIGH_RS is sector_excess at or above the band median; LOW_RS is below it.
- Each band reports: `score_band`, `high_RS_n`, `low_RS_n`, `high_RS_forward_return`, `low_RS_forward_return` and
  `delta`.
- A band is usable only if both sides have at least 10 observations.

**Combined measures:**
- Weighted delta is Σ n·delta / Σ n over the usable bands.
- OLS: gross30 ~ 1 + z(score) + z(sector_excess), reporting the t-statistic of the RS coefficient.

**Decision:**

| Result | Condition |
|---|---|
| **YES** | weighted delta > 0 **and** t ≥ 2 |
| **NO** (`REDUNDANT_FEATURE`) | weighted delta ≤ 0 **or** t < 1 |
| **INCONCLUSIVE** | anything else, or fewer than 2 usable bands |

## 8. Six frozen Phase A variants

All variants use 15-minute ENGINE_VIEW features, go long, and exit at +30 minutes. A missing feature never passes.

| Id | Rule | Role |
|---|---|---|
| RS-1 MARKET EXCESS | market_excess ≥ +1.5% | long candidate |
| RS-2 SECTOR EXCESS | sector_excess ≥ +1.5% | long candidate |
| RS-3 DIVERGENT ALPHA | stock return ≥ +2.0% **and** SPY return ≤ 0.0% | long candidate |
| RS-4 VOLUME-CONFIRMED SECTOR RS | RS-2 **and** RVOL_15m ≥ 2.0 | long candidate |
| RS-5 LOW-FRICTION SECTOR RS | RS-2 **and** spread-to-price ≤ 1.0% | long candidate |
| RS-6 DIAGNOSTIC REVERSION | sector_excess ≤ −2.0% | **COUNTERFACTUAL / DIAGNOSTIC ONLY; can never promote** |

No threshold variant is added after results are seen. If nothing passes, 1.0%, 1.25%, 1.75%, 2.5% and similar
thresholds are **not** run.

## 9. Gates

**Minimum eligibility (all required):**
- Gross mean > 0.
- Net mean > 0.
- Profit factor > 1.0.
- N ≥ 40 primary symbol-sessions.
- No single trade exceeds 20% of total gross P&L.
- Net mean stays > 0 after removing the top 3 gross winners.
- The quintile gradient gate passes.

**Strong economic hurdle, required for Phase B in this study:** gross mean ≥ **+0.35%**.

**Variant status:**
- A variant that passes the minimum gates but has gross below +0.35% is `INTERESTING_BUT_INSUFFICIENT`. It is **not**
  forward-registered.
- RS-6 is always `DIAGNOSTIC_ONLY`.

**Selecting at most one variant.** Sep 28–29 is discovery data, and the best of six is never "validated". Among long
candidates that pass the strong gate, the selection order is:
1. Highest net expectancy.
2. Larger N.
3. Lower top-3 share of gross.
4. Simpler variant (fewer conditions).
5. Variant id.

The choice is recorded as `PHASE_B_SELECTION_REASON`.

**Verdict:**

| Verdict | Condition |
|---|---|
| **INCONCLUSIVE** (data) | fewer than 250 quintile observations, or benchmark coverage below 90% |
| **PROMOTE_TO_FORWARD** | a Phase B candidate exists |
| **INCONCLUSIVE** | the gradient passes and some variant is `INTERESTING_BUT_INSUFFICIENT` |
| **UNSUPPORTED** | otherwise |

## 10. Phase B (only if one variant passes)

- The window starts **2026-10-01** and needs at least **10 complete trading sessions**.
- The variant is frozen in a **separate registration commit** before its first Oct 1 qualifying observation is
  evaluated. That commit fixes the variant, benchmark, threshold, lookback, entry, exit, cost model and DTU population
  rules.
- Nothing changes during the window.

**Success requires:**
- Gross > 0, net > 0 and profit factor > 1.
- Positive results across multiple sessions.
- No single-trade domination.
- A positive result after removing the top 3 winners.
- An adequate sample.

**Failure:** if net ≤ 0, `RELATIVE_STRENGTH_HYPOTHESIS = UNSUPPORTED`. There is no rescue on the same forward period.

**If no candidate passes:** Phase B does not start, and a genuinely different information source is proposed instead.

## 11. Known limitations, declared in advance

- **Signal lag in the primary view:** the ENGINE_VIEW RS is measured about 16 minutes before entry. That is the honest
  cost of the free delayed data. WALLCLOCK_VIEW shows how much information exists with real-time data, and it is a
  diagnostic only.
- **SIC:** it is not point-in-time, and the minimal map leaves many names on SPY.
- **Sep 28 DTU:** the event tier is a replay, same-day 8-Ks are missing, and coverage gaps are reported.
- **Sample size:** two sessions are a small sample. Every Phase A result is exploratory.
