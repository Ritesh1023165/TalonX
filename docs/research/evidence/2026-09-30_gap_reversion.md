# LARGE_GAP_REVERSION_V1: historical test (pre-registered at 7b06ff3)

**Verdict: `LARGE_GAP_REVERSION_V1 = UNSUPPORTED`.**

- **PRICE_EDGE:** a small gross reversion exists, but it does not survive the standard TalonX cost.
- **DEPLOYABLE_SHORT_STRATEGY:** NO.

The frozen gate is the one registered before any outcome was computed: n ≥ 200 **and** (net ≤ 0 **or** profit factor
≤ 1). No new threshold, spread, time-of-day or catalyst filter is used to rescue it.

**Scope:** research-only short reference. No broker, no alerts, borrow not modelled.
- Runner: `talonx_paperperf/gap_reversion_run.py`
- Output: `2026-09-30_gap_reversion/report.json`

## Data

- **Source:** free Alpaca SIP data. The universe is the `market.db` ELIGIBLE set (currently listed names; survivorship
  caveat).
- **Candidate screen:**
  - Daily bars from 2023-11 to 2026-09 screened 21,600 candidate gap days, requiring V1 floors at D-1.
  - Daily open ≥ 1.08× the prior close for the ≥ 10% class.
  - The frozen 10% hash sample for the 3–10% class.
- **Gap and outcomes:** the frozen gap, entry and outcomes are computed on raw 1-minute bars, plus a quote spread at
  each entry.
- **Prefilter check:** Alpaca's daily open equals the first regular-session print (227 of 232 exactly, the rest within
  1%).
- **Coverage:**
  - Historical period 2024-01-02 → 2026-09-25: **8,025** events of ≥ +10%.
  - 2,606 symbols over 684 sessions.
  - Excluded: 552 NO_OPEN_BAR, 77 NO_ENTRY_BAR, 58 NO_PRIOR_CLOSE, 54 SPLIT_DAY.
- **CLUE** (2026-09-28/29): n = 20, reported separately.
- **FORWARD:** 0 so far.

**Operational note:** the fetch ran during market hours and exhausted the shared Alpaca quota from 16:00 to 20:08Z,
causing production DTU sweeps to get HTTP 429. Research fetches are now capped at 40 requests a minute during sessions.

## Primary result: entry A, short reference, HISTORICAL

| Horizon | Mean | Median | t | 95% CI (i.i.d.) | 95% CI (day-clustered) |
|---|---|---|---|---|---|
| +15m gross | −0.01% | +0.45% | −0.1 | [−0.18, +0.16] | [−0.20, +0.17] |
| **+30m gross** | **+0.23%** | +0.80% | 2.1 | [+0.01, +0.44] | [−0.03, +0.46] |
| +60m gross | +0.42% | +1.01% | 3.1 | [+0.15, +0.68] | [+0.11, +0.70] |
| Session close gross | +0.68% | +1.52% | 3.0 | [+0.22, +1.12] | [+0.16, +1.20] |
| **+30m standard net** | **−1.12%** | −0.48% | −10.2 | [−1.33, −0.90] | [−1.38, −0.88] |

- **Win rate and profit factor:** net win rate 46.8%; profit factor (net) **0.70**; profit factor (gross) 1.07.
- **Cost:** the mean is **1.34%** per round trip, because the measured NBBO spread one minute after the open is wide on
  gappers. Only 4 cost measurements were partial.
- **Short-side excursions:** mean MFE +10.0%; mean MAE −13.0%, meaning a large adverse move.

**Concentration:** not the issue. Removing the best 1, 3 and 5 gives net −1.13%, −1.14% and −1.15%.

**Consistency:**

| Split | Net +30m |
|---|---|
| H1 | −1.19% |
| H2 | −1.07% |
| 2024 | −1.33% |
| 2025 | −0.85% |
| 2026 | −1.26% |

30 of 33 months are negative.

**Confirmation entry (B):** n = 8,017, gross +0.22%, net −0.89%, PF 0.72.

**Portfolio (`RESEARCH_SHORT_PORTFOLIO`):**
- 749 trades: gross +$9.0k, net **−$90.4k**.
- Max drawdown −90.9%; capital utilisation 28%.

**Baseline on the same events and entry:** the long-continuation gross is −0.23% and net −1.57%. Both directions lose
after cost.

## Descriptive breakdowns (not filters; no rescue)

- **Gap bucket, net +30m:**

  | Bucket | n | Gross | Net | PF |
  |---|---|---|---|---|
  | 3–5% (sample) | 4,231 | +0.11% | −1.23% | — |
  | 5–10% (sample) | 2,142 | +0.17% | −1.39% | — |
  | 10–20% | 5,583 | +0.05% | −1.45% | 0.58 |
  | 20%+ | 2,462 | +0.65% | −0.35% | 0.92 |

- **DTU at D-1:**

  | DTU state | n | Gross | Net |
  |---|---|---|---|
  | Core | 1,954 | +0.28% | −0.47% |
  | Event-promoted | 6,011 | +0.21% | −1.34% |

  The event tier is not useful for reversion either.
- **Spread:**

  | Spread | ≤ 25 bps | 25–50 bps | 50–100 bps | > 100 bps |
  |---|---|---|---|---|
  | n | 846 | 1,560 | 2,334 | 3,281 |
  | Net | **+0.16%** (PF 1.07) | −0.09% | −0.66% | −2.27% |

  This is noted, not promoted.
- **Price and ADV:** net is negative in every band.
- **Regime:**

  | Regime | Net |
  |---|---|
  | SPY above its 200-day average | −0.99% |
  | SPY below | −1.50% |
  | High volatility | −1.25% |
  | Low volatility | −0.96% |

- **Catalyst:**

  | Catalyst | n | Gross | Net |
  |---|---|---|---|
  | 8-K | 3,617 | +0.08% | −1.26% |
  | 6-K | 759 | +0.92% | −0.18% |
  | Form 4 | 376 | — | −1.13% |
  | None known | 3,273 | — | −1.18% |

- **Opening path:**
  - 91% retrace 1% within minutes of entry, and 84% retrace 2%.
  - 37% first extend 1% higher.
  - 17% never revert 2%.
  - The median maximum extension above entry is +6.5%.

**The CLUE was an outlier:** 2026-09-28/29 (n = 20) gave +2.19% gross and +1.21% net. The 2.7-year history shows +0.23%
gross and −1.12% net.

## Shortability

- **Basis:** Alpaca asset flags, a current snapshot and not point in time. No borrow-fee data.
- **Coverage:** 2,605 of 2,606 symbols are known. 1,749 are shortable now and 1,750 are easy to borrow now.
- **Status:** SHORTABILITY = PARTIAL. It is moot given the price result.

## Next

No forward tracker is started, because the historical result is clearly unsupported (§28). The only positive cell is
spreads ≤ 25 bps, and that is a post-hoc slice of the same data. Under the no-rescue rule it cannot be promoted. If it
is ever pursued, it would need a new, separately pre-registered hypothesis tested only on future data.
