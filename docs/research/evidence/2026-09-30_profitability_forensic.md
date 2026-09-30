# PAPER_SIGNAL profitability forensic — 2026-09-28 + 2026-09-29

Paper and research only: no capital, no orders, no strategy change. Tool: `talonx_paperperf/signal_forensics.py`
(read-only on production stores). Evidence: `2026-09-30_profitability/` holds `combined.json` and per-day
`*_signals.csv`.

## Verdict

**NEGATIVE_EDGE (preliminary, two sessions).** At the actionable entry, after costs, every horizon lost money on both
days, and no stratification bucket was positive. Before costs, returns were about zero, so even a free execution would
not have shown an edge.

## 1. Reconciliation

| Day | PROMOTED_SIGNAL | Telegram SENT | Actionable entry found |
|---|---|---|---|
| 2026-09-28 | 154 | 154 | 150 (4 sent too near or after the close) |
| 2026-09-29 | 153 | 153 | 151 |
| Combined | **307** | **307** | 301 |

There is no discrepancy from 154 / 153.

## 2. Method

**Entries:**
- **RESEARCH:** the Signal's reference price at its `data_as_of` (15-minute-delayed SIP).
- **ACTIONABLE:** the open of the first 1-minute SIP bar starting at or after the Telegram SENT time, rounded up to the
  minute. It is never backdated.

**Outcome definitions:**
- **Horizons:** +5, +15, +30 and +60 minutes, using the close of the last bar completed by entry+h, plus the session
  close. A horizon that ends after the regular close is UNRESOLVED and is never carried overnight.
- **MFE / MAE:** measured from entry to the close.
- **Direction:** long-only (the Signals are BULLISH).

**Costs (no new assumption):**
- **Net** = gross − max(V2's documented 20 bps round-trip research friction, *measured* SIP NBBO spread at the
  actionable entry).
- The spread is charged once for the whole round trip: half on entry, half on exit.
- Spread was measured for 300 of the 301 entries. The one unmeasured entry uses the 20 bps friction only.
- Median cost: 25.9 bps; median spread: 26.4 bps.

**Portfolio (simulation assumptions):**
- $100,000 starting capital with $10,000 equal-dollar positions. This is the V2-PAPER-RC1 campaign sizing; no
  Opportunity Engine sizing exists.
- At most 10 positions at once, no leverage, and trades taken chronologically.
- A trade is taken only if its exit horizon resolves.
- Every exit horizon is shown; none was picked after the fact.

## 3. Scorecards — ACTIONABLE entry, net of costs

| | Sep 28 | Sep 29 | Combined |
|---|---|---|---|
| +15m mean / median / win | −0.47% / −0.39% / 28.5% | −0.70% / −0.52% / 21.7% | **−0.58% / −0.41% / 25.1%** |
| +30m | −0.48% / −0.36% / 32.6% | −0.67% / −0.44% / 27.9% | **−0.57% / −0.40% / 30.3%** |
| +60m | −0.55% / −0.44% / 34.9% | −0.78% / −0.53% / 33.3% | **−0.66% / −0.49% / 34.1%** |
| Close | −0.34% / −0.45% / 36.0% | −0.44% / −0.63% / 35.1% | **−0.39% / −0.54% / 35.5%** |
| Profit factor (+15 / +30 / +60 / close) | 0.30 / 0.33 / 0.41 / 0.70 | 0.13 / 0.25 / 0.25 / 0.62 | 0.21 / 0.28 / 0.33 / 0.66 |
| Gross mean (+15 / +30 / +60 / close) | +0.09 / +0.10 / +0.05 / +0.22% | −0.23 / −0.21 / −0.32 / +0.04% | −0.07 / −0.06 / −0.13 / +0.13% |
| MFE mean / median | +2.16% / +1.14% | +1.81% / +0.90% | +1.99% / +1.07% |
| MAE mean / median | −1.56% / −1.06% | −1.79% / −1.23% | −1.67% / −1.12% |

Unresolved (horizon after the close, or no entry), combined: +15m 20, +30m 33, +60m 58, close 6.

The RESEARCH entry is **worse** at every horizon (net: +15m −0.70%, +30m −0.84%, +60m −0.87%, close −0.66%;
gross −0.19%, −0.33%, −0.36%, −0.15%).

**False-edge check:** `BOTH_NEGATIVE` at every horizon. `DELAY_ERASES_EDGE` does **not** apply, because there was no
edge at the reference price for the delay to erase.

## 4. Paper portfolio

$100k, $10k per position, up to 10 at once:

| Exit | Trades (skipped at capacity) | Gross P&L | Net P&L | Ending capital | Max drawdown | Win rate | Profit factor | Expectancy per trade |
|---|---|---|---|---|---|---|---|---|
| +15m | 287 (0) | −$1,858 | **−$16,736** | $83,264 | −$16,736 | 25.1% | 0.21 | −$58.31 |
| +30m | 193 (81) | −$1,511 | **−$11,279** | $88,721 | −$11,501 | 31.1% | 0.26 | −$58.44 |
| +60m | 100 (149) | −$1,447 | **−$6,906** | $93,094 | −$7,472 | 36.0% | 0.34 | −$69.06 |
| Close | 20 (281) | +$223 | **−$1,061** | $98,939 | −$2,632 | 35.0% | 0.76 | −$53.07 |

- **Per day at +30m:** Sep 28 −$4,313 (drawdown −$4,559); Sep 29 −$6,966 (drawdown −$7,050).
- **Per day at +15m:** Sep 28 −$6,786; Sep 29 −$9,950.
- **Capacity:** with a 10-position cap, longer holds skip most Signals. The +15m run averaged 6.6 positions open, with
  a maximum of 10.

## 5. Concentration

**+30m net:**
- **Best / worst:** best KRSA (Sep 29) +5.9%; worst XRPN (Sep 28) −7.7%.
- **Winners' share:** the top 1 / 3 / 5 trades contribute +5.9 / +17.0 / +21.9 percentage points.
- **Removing them makes it worse:** the mean goes from −0.57% to −0.60% / −0.64% / −0.67%.
- **Top winners:** KRSA, CANG, PWP, IVA, DFTX.
- **Top losers:** XRPN, SMJF (Sep 29), JELD, NAMI, SLGL.

**Close:**
- **Best / worst:** best WYY +12.4%; worst AVX −9.8%.
- **Winners' share:** the top 5 contribute +47.6 percentage points.
- **Removing them makes it worse:** without the top 5 the mean falls to −0.56%.

The result is not an outlier artefact: it is broadly negative.

## 6. Free-data delay impact

- **Latency.** The median time from data to send is 1,167 s (p90 1,548 s). It breaks down as:
  - provider delay 960 s (the 15-minute SIP delay plus scan alignment);
  - engine to queue 73 s;
  - promotion queue 88 s;
  - Telegram 2 s.
- **Entry drift** (actionable vs reference): median −0.13%, p90 +1.07%.
  - Absolute drift was ≤0.5% for 47%, ≤1% for 71%, ≤2% for 89%, and >2% for 11%.
  - 11% had already risen more than 1% before delivery; 18% had *fallen* more than 1%.
- **Reading:** the delay does not cost money here. Prices on average drift *down* between the data time and delivery,
  so the actionable entry is cheaper than the reference, and actionable results beat research results. The free feed
  is adequate for paper validation. **Paid data is not justified by this evidence.**

## 7. Stratification

Actionable, net. n is small in several buckets, and no causality is claimed.

| Bucket | +30m n / mean | Close n / mean |
|---|---|---|
| Spread ≤25 bps | 135 / −0.25% | 146 / −0.29% |
| Spread 25–50 | 73 / −0.45% | 81 / −0.05% |
| Spread 50–100 | 40 / −1.06% | 45 / −0.21% |
| **Spread >100** | 25 / **−2.17%** | 28 / **−2.30%** |
| ADV $20–100M | 94 / −0.20% | 104 / −0.11% |
| **ADV <$5M** | 61 / **−1.15%** | 69 / −0.52% |
| Price <$3 | 23 / −1.50% | 25 / +0.16% (median −1.33%) |
| Score 65–70 | 62 / −0.25% | 70 / −0.11% |
| Score 85+ | 10 / −1.05% | 10 / −0.12% |
| **Catalyst 8-K** | 14 / **−1.74%** (win rate 7%) | 15 / −1.19% |
| No catalyst | 224 / −0.50% | 247 / −0.35% |
| Opening hour / midday / late | −0.66 / −0.56 / −0.53% | −0.20 / −0.37 / −0.55% |
| DTU ACTIVE_CORE / EVENT_PROMOTED | 68 / −0.28% · 201 / −0.67% | −0.34% · −0.40% |

- **Best (least negative):** tight spread (≤25 bps), ADV $20–100M, Core names, and score 65–70. Their advantage is
  mostly lower cost.
- **Worst:** spread >100 bps, ADV <$5M, 8-K catalysts, price <$3 (at 30 minutes), and score 75–80 / 85+.
- **Score does not order outcomes:** the higher score bands are not better.

## 8. Dynamic Tradable Universe × P&L

| Horizon | Full-universe net P&L | Core 1200 + event tier net P&L | Difference |
|---|---|---|---|
| +30m | −$15,700 | −$15,700 | $0 |
| Close | −$11,689 | −$11,689 | $0 |

The shadow retained **every** Signal on both days (09-28 from the study replay; 09-29 from the live shadow with
POLICY protection). So it neither removes losers nor loses winners: **P&L-neutral**. It is a workload decision, not a
profitability lever.

## 9. Answers

1. **Did TalonX make money on paper over Sep 28–29?** No. Every horizon and every portfolio variant lost money.
2. **Profitable after realistic costs?** No. Net expectancy runs from −0.39% (close) to −0.66% (+60m) per trade.
3. **Actionable vs reference?** Actionable was *better* by +0.12 to +0.27 percentage points, but both were negative.
4. **Did the free 15-minute delay hurt?** No, not materially. Prices drifted slightly down before delivery.
5. **Did performance depend on a few winners?** No. Removing the top winners makes it worse; the losses are broad.
6. **Best type:** tight-spread, liquid ($20–100M ADV) Core names. Even these were negative after costs (−0.25% at
   30 minutes).
7. **Worst type:** wide-spread (>100 bps), illiquid (<$5M ADV) and 8-K-catalyst Signals.
8. **Would the Dynamic Universe help or hurt profitability?** Neither. It is P&L-neutral.
9. **Enough evidence to tune?** Enough to say the current Signal policy has no edge. Not enough to choose a tuned
   policy from two days; any bucket filter would be fitted to noise.
10. **Single highest-value next experiment:** a pre-registered **shadow filter**, evaluated forward over ≥10 sessions
    without changing the live policy:
    - spread ≤25 bps at entry, ADV20 ≥ $20M, and no 8-K-only catalyst;
    - held to a fixed +30-minute exit;
    - graded against the same cost model.

    Pre-registering is what keeps it honest. If even that subset stays at or below zero *gross*, the Signal premise
    (buying gap-up continuation after a 20-minute delay) should be retired rather than tuned.

## 10. Limitations

- **Short sample:** only 2 sessions, in the same market regime.
- **No slippage:** fills beyond the quoted spread are not modelled.
- **Spread sampling:** the spread is sampled only at entry, and the same spread is assumed at exit.
- **Mechanical exits:** exits are mechanical (fixed time); there is no stop or target model.
- **Mixed DTU sources:** the classification for 09-28 comes from replay, not live.
- **Outcome source:** outcomes use SIP 1-minute bars. They are not the engine's own `paper_outcomes`, which use the
  reference price.
