# TASK 95B — Rejected Hypotheses

**All 68 experiments ended `DISCOVERY_FAIL` (67) or `DISCOVERY_INCONCLUSIVE` (1). 0 `DISCOVERY_PASS`
after adjudication.** Full numeric detail: `EXPERIMENT_LEDGER.csv` (append-only). Metric throughout =
net **excess** bps over the matched unconditional-long comparator at the declared primary horizon,
5-bps one-way cost, with symbol-block-bootstrap + non-overlapping-subsample CIs.

> Units: all values are **bps of excess forward return over the comparator**, net of the stated
> round-trip cost. Horizons are trading days.

## Family A — multi-day momentum (25 exp, all FAIL)

| Hypothesis | best bin | excess net@5 | failing criteria |
|---|---|---:|---|
| prior 5d/20d/60d return quintiles → continuation | `ret_60d_prior` q1 (weakest) | +20.8 | S2 (< +25), S7 |
| top prior-return quintiles continue | `ret_5d_prior` q5 | **−28.0** | wrong sign — strong movers mean-revert |
| 20d relative-strength leaders continue | RS-20d top q | +2.8 | S2, S3, S4, S5, S6 |
| within 2 % of 20d high → continuation | — | **−26.6** | wrong sign — proximity to breakout underperforms |

**Ruled out:** multi-day price momentum / relative strength / near-high as long-continuation signals
at 1–5 day horizons in this universe. The only positive cells are *weak*-quintile reversion, sub-threshold.

## Family B — pullback in established uptrend (9 FAIL + 1 inconclusive)

| Hypothesis | best bin | excess net@5 | failing criteria |
|---|---|---:|---|
| dual-SMA uptrend + short pullback → rebound | 3d pullback q1 | +13.7 | S2, S6 |
| uptrend + 5d pullback q1 → rebound | — | **−23.3** | wrong sign — deeper dips keep falling |
| uptrend + 4–10 % below 20d high | — | +4.1 | S2, S3, S4, S5, S6 |
| uptrend + daily RSI < 40 | n=7 | — | INCONCLUSIVE (condition ~never co-occurs) |

**Ruled out:** buy-the-dip-in-an-uptrend as a cost-clearing swing edge.

## Family C — breakout / range expansion (11 FAIL)

| Hypothesis | bin | excess net@5 | failing criteria |
|---|---|---:|---|
| new 20d high → follow-through | `new_hi20` | **−24.0** | wrong sign |
| 20d-high breakout + volume ≥ 1.5× | `new_hi20_vol` | **−24.5** | wrong sign |
| top-decile 20d-range close → continuation | `range_pos_top` | **−19.0** | wrong sign |
| up day ≥ 2× ATR% → follow-through | `expansion_up` | **−31.1** | S1, wrong sign |

**Ruled out:** breakouts / strong closes / range-expansion up-days — all *negatively* predictive at
2–3 days here (clean mean-reversion result).

## Family D — oversold rebound (11 FAIL — closest to passing)

| Hypothesis | bin | excess net@5 (vs global / vs matched) | failing criteria |
|---|---|---:|---|
| 5d-drawdown bottom quintile → rebound | `5d_drawdown_q1` | +6.0 | S2, S3, S4 |
| daily RSI ≤ 30 → rebound | `rsi30` | +1.7 | S2, S3, S4, S6 |
| > 15 % drawdown + fresh bottom-decile 3d drop | `deepdd_fresh3ddrop` | +25.2 / **+17.3** | **S7** (best-year 52 % = 2020); vs DD15-matched < S2; 2022 negative |
| > 20 % drawdown + daily RSI ≤ 35 | `dd20_rsi35` | +35.3 | **S4** (non-overlap CI [−91, +86]); **S7** (best-year 64 %) |

**Ruled out:** the oversold-bounce is real-signed but **regime-episodic** — 45–64 % of its positive
excess-R comes from 2020 (and 2023) bottoms; it is negative in the 2022 bear and does not survive
removing the best year or a drawdown-matched comparator.

## Family E — gap follow-through, price/volume only (10 FAIL + 1 adjudicated FAIL)

| Hypothesis | bin | excess net@5 | failing criteria |
|---|---|---:|---|
| top-decile up gap → continuation | `gapup_p90` | **−36.4** | wrong sign — up-gaps fade |
| up gap + volume ≥ 2× | `gapup_p90_vol` | **−38.6** | S1, wrong sign |
| bottom-decile down gap → rebound | `gapdn_p10` | −1.7 | no edge unconditioned |
| **down gap × high realized-vol regime** | `gapdn_p10 × vol_high` | +63.7 (global) / **+35 (matched)** | **automated PASS → adjudicated FAIL**: wrong comparator; ~77 % is same-dates market move; 2022 (half the events) negative; remove-best-year → negative; negative on COMMON10; 1-of-35 grid cell |
| down gap × mkt_bear / dd20 | — | +15 … +27 | S4 (non-overlap CI spans 0), S7 |

**Ruled out:** up-gap continuation (clean negative); down-gap rebound on price/volume alone; the
regime-conditioned down-gap is the same 2020/2023 V-bottom artifact as Family D. A clean
earnings/catalyst calendar (not available in `task95a_expanded_v1`) would be needed to test true
post-event drift — logged as a data requirement.

## Phase 10 — regime conditioning (35 cells)

Every cell with positive excess is a stress regime (`vol_high` / `mkt_bear` / `dd20`) on the
oversold/gap-down families, and every one fails S4 and/or S7. `vol_low` is uniformly the *worst*
regime for swing longs here (−14 to −44 excess) — the inverse of Task 95A's intraday finding. No
regime-conditional candidate advances (`regime_conditioning.md`).
