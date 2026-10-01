# TASK 95B — SWING RESEARCH PROTOCOL

**Frozen before any hypothesis is selected or any family result is inspected.** Defines the
measurement, the normalization, and the pass/fail criteria for Phases 5–17. Deviations must be logged
in `TASK95B_CHECKPOINT.md` and `rejected_hypotheses.md` with reasoning.

## 1. Event, entry, exit

- **Event** = a causally-defined condition true at a **completed daily bar** *t* (all features use
  only bars ≤ *t*; the daily feature set is pre-shifted).
- **Entry** = `adj_close(t)` (16:00 ET). A stricter next-day-open variant (`adj_open(t+1)`) may be
  reported as a robustness check; primary is close.
- **Exit** = `adj_close(t+k)` for `k ∈ {1, 2, 3, 5}` trading days (primary), `k = 10` optional,
  `overnight` reported for context. Horizon definitions: `forward_horizon_spec.md`.
- **Long-only** by construction (C-ZERO-SHORT trivially holds).
- Split-spanning forward returns are NaN and excluded.

## 2. Primary metric — net EXCESS return in bps

The Phase 3 baseline established that **unconditional long already clears cost at swing horizons in
this bull-heavy 2020–2026 sample** (+8.8 bps net @5 bps at 2 d … +81.8 bps at 10 d). A positive net
return is therefore **not** evidence of a signal. The primary metric is:

> `excess_net_bps(k, c) = mean[ candidate fwd_kd ] − mean[ comparator fwd_kd ] − (2·c)/1e4`
> expressed in bps, where `c` is the one-way cost in bps (round trip = `2·c`).

**Comparator** (Phase 15, default): the **matched unconditional-long mean** — the mean `fwd_kd` over
**all daily bars of the same symbols in the same discovery period** (equivalently, the
partition-and-universe-matched buy-and-hold drift). Additional comparators reported: random
same-symbol entries, random same-calendar-month entries, an equal-weight 35-name basket ("SPY
proxy"), and an above-`sma50` trend baseline.

The candidate's own cost is charged once (`2·c`); the comparator is treated as the zero-cost
buy-and-hold alternative the capital would otherwise earn. `excess_net_bps` is thus "extra bps from
acting on this signal, after paying to act."

## 3. Secondary metric — swing R

`R = fwd_kd / risk_unit`, `risk_unit = 2.5 · atr_pct(t)` where `atr_pct(t)` is the entry bar's
**daily** ATR(14)%/close (pre-shifted). 2.5·ATR is a conventional swing stop distance; the
denominator is **horizon-independent and fixed before results are seen** (it is *not* re-scaled per
`k` and *not* re-chosen after inspecting performance). Stop model for R: if `fwd_kd_minlow ≤ −risk_unit`
→ outcome = −1.0 R (stop-first); else `R = fwd_kd / risk_unit`. Net R at cost `c`:
`R − (2·c)/1e4 / risk_unit`. Reported at 0/2/5/10/20 bps.

## 4. Cost model

Round trip = `2 · c` bps of notional, `c ∈ {0, 2, 5, 10, 20}`. **Primary decision cost `c = 5`
(10 bps round trip); 10 bps (`c = 10`, 20 bps round trip) is the stress test.** Also report
**`COST_AS_PERCENT_OF_GROSS_EDGE` = (2·c) / gross_excess_bps** at `c = 5` and `c = 10`.

## 5. Overlapping-horizon confidence (Phase 12 — mandatory)

k-day daily forward returns overlap. Naïve i.i.d. bootstrap is **not** acceptable. For every CI:

1. **Non-overlapping subsample**: keep every k-th event per symbol (disjoint windows); report n_nonoverlap and its mean/CI.
2. **Symbol-block bootstrap**: resample whole symbols (35 blocks) with replacement, 5,000 iters; 2.5/97.5 pctile of the excess-net-bps.
3. **Newey–West / clustered SE**: cluster by symbol, report the clustered-SE 95 % interval.

A candidate must have **excess-net-bps CI lower bound > 0** under *both* the non-overlapping mean and
the symbol-block bootstrap.

## 6. Discovery pass criteria (ALL required)

| # | Criterion |
|---|---|
| **S1 — sample** | ≥ 300 events **and** ≥ 100 non-overlapping events in discovery. |
| **S2 — magnitude** | `excess_net_bps(k*, c=5) ≥ +25` at the candidate's declared primary horizon `k*`. |
| **S3 — cost stress** | `excess_net_bps(k*, c=10) > 0` (survives a 20-bps round trip). |
| **S4 — uncertainty** | excess-net-bps 95 % lower bound > 0 under **both** the non-overlapping mean **and** the symbol-block bootstrap (§5). |
| **S5 — breadth** | positive `excess_net_bps(k*, c=5)` in **≥ 50 % of discovery years** (≥ 3 of ≤ 4) **and** **≥ 45 % of symbols**. |
| **S6 — outlier robustness** | after removing the best event, best 3, best 5, best symbol, best month, and best year (each independently), `excess_net_bps(k*, c=5)` remains **> 0**. |
| **S7 — concentration** | no single symbol > 35 % of the total positive excess-R; no single month > 25 %; no single year > 45 %. |
| **S8 — turnover / capacity** | implied ≤ ~2 new entries per symbol per week on average (events/symbol/week ≤ 2), and mean concurrent open positions per symbol ≤ `k` (i.e. no absurd stacking). Purely a plausibility gate (Phase 14), not an optimization. |
| **S9 — direction** | 100 % long; declared expected direction = long; sign of the effect is positive as hypothesised (no wrong-signed "edge"). |
| **S10 — determinism** | identical result on re-run from the frozen dataset + code SHA. |
| **S11 — regime honesty** | if the candidate is regime-conditional, the regime must be causally observable at entry, present in ≥ 2 of the 4 discovery-era regimes or ≥ 20 % of discovery bars, and **not** defined from strategy P&L. A regime-conditional candidate still must meet S1–S10 *within* its regime. |

**Automatic REJECT** if: `excess_net_bps(k*, c=5) ≤ 0`; or the effect is just the unconditional drift
(excess ≈ 0 within CI); or CI includes 0 after S1 met; or wrong-signed; or S6/S7 fails; or look-ahead
found; or the candidate is a single (feature-bin × regime) cell selected from a large grid without a
pre-registered mechanism.

## 7. Multiple testing

Coarse **pre-registered** bins only (declared per family in Phases 5–9 *before* running). No
threshold scan for a best cell. Every bin tested is logged in `EXPERIMENT_LEDGER.csv` (append-only).
With ~5 families × ~6–10 bins × 4 horizons ≈ 150–200 tests, ~8–10 nominal false positives are
expected at p < 0.05 — S2 (economic magnitude) + S4 (dual CI) + S6 (outlier) are the real filters,
not a p-value. If several bins in one family pass, the family is treated as one finding and the
single most robust, most pre-registered bin is the candidate.

## 8. Candidate freeze (Phase 17)

On a discovery pass, immediately freeze into `candidate_<ID>_spec.md`: exact feature definition,
bin/threshold, entry timing, exit horizon `k*`, regime condition (if any), cost model, universe,
expected direction, and the discovery-period statistics. **No further optimization. Holdout is not
inspected.** Validation is a separate future task.

## 9. What this task does NOT do

No portfolio construction, no position sizing, no stop/target tuning, no strategy code, no live or
paper execution, no holdout inspection, no production change. Phenomenon research only.
