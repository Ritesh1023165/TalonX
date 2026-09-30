# INSIDER_BUY_CLUSTER_V2: profitability-first validation (checkpoint 1: historical + 2026Q2 holdout)

**Verdict for V2@1 as frozen and implemented: `UNSUPPORTED`.** The 7-year history is flat, net ≤ 0 with profit factor
below 1. The only positive evidence is one out-of-sample quarter in a strong market, and it is outlier-heavy.

- **Scope:** research only. No live change, no Telegram, no orders.
- **Unchanged:** CONTROL, SQF_V1, DTU and V2 execution.
- **Tools:**
  - `talonx_paperperf/v2_validation.py` (evaluator)
  - `talonx_paperperf/form4_edgar.py` (EDGAR Form 4 crawler for the post-bulk period)
- **Outputs:** `results/v2_validation/` (gitignored). The numbers below come from `evaluation.json`.

## 1. Authoritative definition (unchanged)

| Field | Value |
|---|---|
| HYPOTHESIS_ID / VERSION | `INSIDER_BUY_CLUSTER_V2` / `INSIDER_BUY_CLUSTER_V2@1`, status `PAPER_CANDIDATE` |
| FINGERPRINT | `e2acf6454789217e` (`talonx_v2/release_gate.py`, `talonx_ops/prospective`) |
| Earlier fingerprint | `11107198c5b81237`. RI-1 (c8489b7, 2026-09-18) added only campaign-identity fields; the strategy fields are byte-identical |
| Registration | Task 107B pre-registration `a9ceefc`, evaluation `625325a`, Task 109 freeze `3103d89` (2026-09-06) |
| Source | `results/task109_v2_freeze/v2_strategy_contract.md`; constants in `talonx_v2/config.py` (`validate_frozen`) |
| Cluster | ≥2 distinct reporting-owner CIKs file Form 4 code **P** in the same issuer within a **10-trading-day** window; greedy, non-overlapping. Fires on the 2nd distinct owner's FILING_DATE (causal = end of that day) |
| Eligibility | S&P 500 ∪ S&P 400 member **or** a trailing-20-session median $ volume ≥ $5M and close ≥ $5. **The runtime wires only the liquidity branch**, because no free point-in-time S&P 400 feed exists (Task 110 finding 2) |
| Entry | **Open of the first NYSE session strictly after the fire** |
| Exit | **Close of entry + 10 sessions.** A missing bar falls forward up to 5 sessions, else `EXIT_UNRESOLVED`. No stop |
| Risk | max 20 concurrent; no adds; 5-session per-issuer cooldown; long only; paper only |
| Cost | `friction_bps` = 20 bps round trip (V2 research friction). No daily spread exists; no other fallback is used |

Only one frozen definition exists; the earlier `@1` fingerprint differs only in operational fields.

## 2. Data

**Available:**

| Source | Coverage | Status |
|---|---|---|
| SEC Form 3/4/5 bulk | 2019Q1–2026Q1 | the rule was frozen from this data |
| SEC Form 3/4/5 bulk | **2026Q2** | new; the SEC moved it to a new path, so the freeze never saw it |
| EDGAR per-filing Form 4 crawl | from 2026-07-01 | in progress |
| Alpaca SIP daily bars | `adjustment=all` | 4,245 of 4,607 episode symbols priced |

**Crawler parity against the bulk file:** 59 of 60 randomly sampled filings match exactly. The one difference is a
half-cent rounding of a $0.075 price. Rare multi-owner filings can list a different "first owner".

**Limits:**
- Filing *date* only, no time of day, so the filing-actionable entry (A) is the same as the next-session open (B).
- Tickers are taken as filed. 39 malformed tickers (for example `"OMEX"`, `(CALX)`) cannot be priced.
- Alpaca's symbol mapping for delisted names isn't point-in-time.
- There is no free point-in-time S&P 400, and no market capitalisation.
- No spread on a daily horizon.

## 3. Results at the primary exit (+10 sessions, 20 bps cost)

| Period | Episodes (evaluated / detected) | Gross mean | Gross median | Net mean | Win (net) | PF (net) | vs SPY | MFE / MAE mean |
|---|---|---|---|---|---|---|---|---|
| **DISCOVERY** 2019-01 → 2026-04 (not validation) | 4,009 / 16,773 | **+0.052%** | +0.61% | **−0.148%** | 52.2% | **0.967** | −0.38% | +9.1% / −9.0% |
| **HOLDOUT 2026Q2** (unseen) | 145 / 458 | +2.948% | +2.31% | +2.748% | 60.0% | 2.11 | +1.24% | +10.2% / −5.9% |

**Why detected episodes don't become evaluated trades:**
- The liquidity gate excludes 12,745 discovery episodes and 313 in the holdout.
- 12 are not priceable at entry.
- 7 are `EXIT_UNRESOLVED`.

**Other horizons, gross (descriptive):**

| Period | +1 | +3 | +5 | +10 |
|---|---|---|---|---|
| Discovery | +0.15% | −0.09% | −0.07% | +0.05% |
| Holdout | +0.27% | +1.83% | +2.21% | +2.95% |

**Entry delay:** entering at the entry session's close instead of its open gives −0.25% in discovery and +2.35% in the
holdout.

**Baselines, discovery:**
- SPY over the same windows: +0.43%, so the episodes underperform SPY by −0.38%.
- Same symbol, unconditional over the prior year: +1.41%, so the episodes underperform that by −1.43%.

**Concentration:**
- **Discovery:** removing the best 1, 3 and 5 gives mean net −0.18%, −0.23% and −0.27%. The worst trades are March 2020
  energy names (−80% to −88%) and TCDA (−98%).
- **Holdout:** MNTS at +148% is **37%** of all net points, and the top 5 are 63%. Mean net without the best 1, 3 and 5 is
  +1.74%, +1.34% and +1.06%.

**Paper portfolio (V2-PAPER-RC1: $100k, $10k per position, contract maximum 20, cash-bound at 10):**

| Period | Trades | Gross P&L | Net P&L | Ending capital | Mark-to-market max drawdown | PF | Per trade | Utilisation |
|---|---|---|---|---|---|---|---|---|
| Discovery | 1,527 (2,366 skipped for cash) | +$129.4k | +$98.9k | $198.9k | **−50.4%** | 1.19 | +$64.7 | 73% |
| Holdout | 55 (90 skipped for cash) | +$5.4k | +$4.3k | $104.3k | −8.9% | 1.29 | +$78.2 | 73% |

**The portfolio result depends on order.** Only the first ten names that fit the cash are held, so the portfolio does not
represent the average episode. Most of the loss-heavy episode clusters (March 2020) are never taken.

## 4. The key diagnostic: where the Task 107B edge lives

The earlier edge (Task 107B's in-panel population: +1.69%, runtime detector +1.01%) was measured on the **S&P 500
panel**. The runtime's liquidity gate admits far more names.

| Discovery +10 | n | Gross | Net | vs SPY |
|---|---|---|---|---|
| S&P 500 panel names | 788 | **+1.08%** | +0.88% | +0.74% |
| Liquid non-S&P names | 3,221 | **−0.20%** | −0.40% | −0.66% |

- The pipeline reproduces the known in-panel figure, which confirms it.
- **The liquidity gate is not the validated domain.** It dilutes the edge to zero.

In the 2026Q2 holdout:

| Holdout +10 | n | Gross | vs SPY |
|---|---|---|---|
| S&P 500 panel names | 30 | +1.74% | **−0.48%** |
| Non-S&P names | 115 | +3.26% | +1.70% (MNTS-driven) |

The holdout does **not** confirm the S&P-domain edge beyond market beta.

## 5. Descriptive breakdowns (discovery gross +10; not filters)

- **Year:**

  | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026Q1 |
  |---|---|---|---|---|---|---|---|
  | +0.48 | **−3.18** | +0.69 | −0.49 | +0.69 | +1.62 | +2.57 | −0.17 |

- **Regime:** SPY above its 200-day average +0.51% (n = 2,533); below −0.73% (n = 1,112). **Pro-cyclical.**
- **Distinct insiders:**

  | 2 | 3 | 4+ |
  |---|---|---|
  | +0.02 | −0.05 | +0.37 |

- **Aggregate value:**

  | < $100k | $100k–250k | $250k–1M | ≥ $1M |
  |---|---|---|---|
  | +0.10 | −0.60 | −0.06 | +0.54 |

- **Role:**

  | Officer | Director-only | 10%-owner-only |
  |---|---|---|
  | +0.07 | −0.20 | +1.17 (n = 264) |

- **Repeat purchases:** yes +0.42, no −0.22.
- **Filing lag:**

  | 0–2 days | 3–5 days | > 5 days |
  |---|---|---|
  | −0.10 | +0.39 | +0.86 |

- **Price:**

  | $5–10 | $10–20 | $20–50 | ≥ $50 |
  |---|---|---|---|
  | −0.42 | +0.22 | −0.35 | +0.56 |

- **Median $ volume:**

  | $5–20M | $20–100M | ≥ $100M |
  |---|---|---|
  | −0.03 | −0.16 | +0.67 |

No bucket is large and consistent enough to justify a filter. Adding filters from this dataset would be a rescue, which
the task forbids.

**Event quality (code-P rows, n = 213,203):**
- 0.04% have a missing price; 2.2% are amendments; 41% are indirect ownership; 33% are 10%-owner rows.
- Other transaction codes never enter.
- No contamination found.

## 6. DTU and V2 scope

**DTU:**
- DTU_V1 has **no Form 4 trigger** (only gap and 8-K), so outside the Core a V2 name stays active only by coincidence.
- Classified against the 2026-09-30 D-1 snapshot as a **static proxy**, of 4,173 V2-eligible episodes:

  | DTU state | Episodes |
  |---|---|
  | Core | 1,308 |
  | V2 scope | 63 |
  | Event-eligible (trigger-dependent) | 1,867 |
  | Not in the universe | 797 |
  | Auto-excluded | 82 |
  | Structurally excluded | 56 |

- **DTU_RETAINED 1,371; DTU_MISSED 2,802.**
- No live Sep 28–30 entries.

**V2 scope:**
- The scope has 39 names. **63 events fall in scope; 4,110 are outside it.** The scope is far too narrow to evaluate the
  hypothesis.
- The in-scope subset is −1.00% net with PF 0.73.
- The live RC1 ledger has 3 episodes, 0 positions and 0 trades.

## 7. Out-of-sample discipline

- 2019–2026Q1 is the discovery period; the rule was frozen from it.
- 2026Q2 is a data holdout that the freeze did not use, but it is not prospective.
- **The first truly forward date is 2026-09-07** (activation filings after the 2026-09-06 freeze).
- The Jul–Sep 2026 crawl, including the prospective September events, is added in checkpoint 2.

## Checkpoint 2 (2026-09-30 16:02Z): Jul–Sep 2026 via EDGAR per-filing crawl, including the first prospective events

**Crawl:** 63 trading days, 33,849 Form 4 filings (1 failed fetch), 29,901 code P/S rows. It is merged with the bulk data
through 2026Q2. **The forward tracker runs daily until 2026-10-31** and writes `results/v2_validation/forward/<date>.json`.

| +10 sessions, 20 bps | n | Gross | Net | PF (net) | vs SPY | Without best 3 (net) | RC1 portfolio |
|---|---|---|---|---|---|---|---|
| POST_Q2, entries 2026-07-02 → 09-15 | 99 | **−2.27%** | **−2.47%** | 0.48 | −2.01% | −3.15% | −$14,969, max drawdown −15.6% |
| PROSPECTIVE, activation after the 2026-09-06 freeze | 10 | −2.06% | −2.26% | 0.64 | −3.18% | — | −$2,264 |
| **All unseen, 2026Q2 + Q3** | 244 | +0.83% | +0.63% | 1.19 | **−0.08%** | **−0.23%** | **−$8,722**, max drawdown −18.0% |

**Q2 did not repeat.** The unseen-period average is carried entirely by MNTS, whose best single trade is **96%** of total
net points: without it the mean is +0.02%, without the best 3 it is −0.23%, and it is flat against SPY. The prospective
sample so far is 10 trades, all negative except GME, KMT and TSM.

**Verdict unchanged, and now stronger: `INSIDER_BUY_CLUSTER_V2@1 = UNSUPPORTED`.**
