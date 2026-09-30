# Pre-registration: LARGE_GAP_REVERSION_V1

**Status: FROZEN.** This file and `talonx_paperperf/gap_reversion.py` (the `SPEC` dict and its pure logic) were committed
**before any outcome of this study was computed.**

| Registration item | Value |
|---|---|
| HYPOTHESIS_ID / VERSION | `LARGE_GAP_REVERSION` / `LARGE_GAP_REVERSION_V1` |
| FINGERPRINT | `18da4977123db5bf` (`spec_fingerprint()`, pinned by `tests/test_gap_reversion.py`) |
| AUTHORITATIVE_SPEC_FILE | `talonx_paperperf/gap_reversion.py::SPEC` |
| `RESEARCH_SHORT_REFERENCE` | `TRUE` on every record |

- **No** broker, **no** live shorts, **no** Signal alerts and **no** production change.
- Borrow availability and fees are **not modelled**.

## Hypothesis

Stocks with a large positive opening gap mean-revert over the 30 minutes after the open, rather than continue. A large
gap is ≥ +10% at the first regular-session print versus the prior regular-session close.

**Provenance:** the clue was n = 15 on 2026-09-28/29, from the VR paper and alpha studies. Those two days are **excluded**
from the historical test and reported separately as `CLUE`.

## Population

**Universe:** `market.db` ELIGIBLE members of the 2026-09-30 window, which is the structural US common-stock filter.
- **Survivorship caveat:** only currently listed names are included; delisted names are absent.

**Periods:**

| Period | Dates |
|---|---|
| **HISTORICAL** | 2024-01-02 → 2026-09-25; halves split at 2025-05-15 |
| **CLUE** (excluded) | 2026-09-28, 2026-09-29 |
| **FORWARD** | 2026-09-30 onwards (shadow tracker) |

**Floors at D-1** (V1 hard floors):
- Close ≥ $1.
- ADV20 ≥ $1M, where ADV20 is the mean of close × volume over the 20 raw daily bars ending D-1.

**Gap:**
- gap = open of the 1-minute bar starting exactly at the regular open ÷ prior close − 1.
- Prior close = close of D-1's last 1-minute bar starting before its regular close, within its last 30 minutes.
- Raw (unadjusted) SIP bars.

**Primary population:** gap **≥ +10%**.

**Descriptive buckets:** 3–5%, 5–10%, 10–20% and 20%+.
- For the 3–10% buckets, a deterministic 10% sample is used (sha256(symbol|date) mod 10 = 0).

**Exclusions:**
- `SPLIT_DAY`: the ratio of raw to split-adjusted daily close changes by more than 1% between D-1 and D.
- `NO_OPEN_BAR`
- `NO_PRIOR_CLOSE`
- `NO_ENTRY_BAR`

## Entry, exit and cost

- **Primary entry (A):** once the open bar has closed, enter at the open of the first bar starting in [open + 1m,
  open + 10m).
- **Confirmation entry (B), the only alternative:** scan closed bars from open + 1m for the first whose close is below
  the previous bar's low, among bars starting before open + 60m. Enter at the next bar's open.
- **Return:** short reference, −(exit/entry − 1).
- **Exits:**
  - Primary: **+30 minutes**, the close of the last bar completed by entry + 30 minutes.
  - Descriptive: +15 minutes, +60 minutes and the session close.
- **Cost (`STANDARD_TALONX`):** max(20 bps, measured SIP NBBO spread at entry). Borrow is not modelled.
- **Lifecycle:** not run in V1. No authoritative short lifecycle exists, and V1's bearish geometry is an artefact of the
  long contract.

## Statistics and gates (entry A, +30 minutes, HISTORICAL period)

**Statistics reported:**
- n, mean, median, standard deviation, standard error and t-statistic.
- Bootstrap 95% confidence intervals, both i.i.d. and day-clustered (seed 20260930).

**Adequate sample:** n ≥ 200.

**`PRICE_EDGE_PROMISING` requires all of these:**
- Gross mean > 0.
- Net mean > 0.
- Profit factor (net) > 1.
- Net mean stays > 0 after removing the best 3 events.
- Net mean > 0 in **both** chronological halves.
- Net mean > 0 in **at least 2 of the 3** calendar years.

**Other verdicts:**
- **`UNSUPPORTED`:** n ≥ 200 **and** (gross ≤ 0 or net ≤ 0 or profit factor ≤ 1).
- **`INCONCLUSIVE_FORWARD_TEST_REQUIRED`:** anything else. The rule is then frozen unchanged for forward shadow
  observation.

**No rescue:** no new threshold, score, time-of-day or catalyst filter may be added from the same data.

## Descriptive only (never gates)

- **Gap buckets.**
- **DTU state, causal at D-1:** ACTIVE_CORE if the ADV20 rank is within the top 1200; otherwise EVENT_PROMOTED_BY_GAP.
- **Liquidity:** price, spread and ADV bands.
- **Regime:** SPY versus its 200-day average, SPY up or down on the day, and SPY 20-day volatility.
- **Catalyst:** EDGAR daily index, 8-K or Form 4 on D-1 or D.
- **Opening path.**
- **Concentration.**
- **Consistency:** per month and per year.
- **`RESEARCH_SHORT_PORTFOLIO`:** $100k, $10k per position, at most 10 open, no leverage.
- **Shortability:** Alpaca asset `shortable` and `easy_to_borrow` flags. These are a current snapshot, not point in
  time, so shortability is **PARTIAL**.

**`DEPLOYABLE_SHORT_STRATEGY`: NOT_ASSESSED** in V1. This version answers the price-edge question only.
