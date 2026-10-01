# TASK 95B — LONGER-HORIZON / SWING ALPHA RESEARCH FOUNDATION — FINAL REPORT

## 1. Verdict

# `SWING_ALPHA_NO_CANDIDATE_PASSED`

The horizon economics **are** favourable — at 2–10 trading days the typical move is 8–11× a realistic
round-trip cost and unconditional long expectancy is net-positive after 5 bps (so this is **not**
`SWING_HORIZON_ECONOMICS_NOT_PROMISING`). But across **68 pre-registered event studies** in five
phenomenon families (multi-day momentum, pullback-in-uptrend, breakout/range-expansion, oversold
rebound, gap follow-through), plus 35 regime-conditioned cells, **no price/volume feature produces a
repeatable, cost-robust, broad, regime-general long-only excess over the matched buy-and-hold
benchmark.** The single cut that cleared the automated criteria (`E-gapdn_p10 × vol_high`) is a
2020/2023 V-bottom artifact and is adjudicated `DISCOVERY_FAIL`.

`PRODUCTION_STRATEGY_UNCHANGED`. `NO_LIVE_SESSION_REQUIRED_FOR_TASK95B`. `NO_LOCAL_AI_REQUIRED`.
Validation and holdout partitions were **not** inspected (no candidate to advance).

## 2. Dataset & horizon views

- Source: `task95a_expanded_v1` (Alpaca **SIP** 1-min, 2020-01-01 → 2026-08-14, 35 symbols,
  fingerprint `8333c1001e28ee18…`). **Not redownloaded.**
- Built `task95b_daily_v1` — **51,922 split-adjusted daily bars** (regular session, ≥ 60 1-min
  bars/day), causal daily feature set, forward returns close-to-close for +1/2/3/5/10 d + overnight,
  split-spanning returns nulled. Validated against raw 1-min (OHLC identical; `fwd_5d` exact).
  Aggregation rules: `aggregation_spec.md`; horizons: `forward_horizon_spec.md`.
- Bridge view (10:00 ET → +60/120/240 min) built only for the Phase 3 cost scan.

## 3. Phase 3 — cost-to-move baseline (the early-stop gate)

`horizon_cost_analysis.md` / `horizon_cost_baseline.csv`. Unconditional long, full sample:

| Horizon | abs median move | mean drift | net @5 bps | net @10 bps | drift ÷ cost(5 bps) |
|---|---:|---:|---:|---:|---:|
| 30 min (Task 95A ref) | ~35 bps | +5 bps | ~0 | neg | ~0.5 |
| 60–240 min | 45–68 bps | −0.3…+2.5 | −10…−7.5 | neg | −0.03…+0.25 |
| 1 day | 116 bps | +9.6 | −0.4 | −10.4 | 0.96 |
| **3 day** | 209 bps | +28.3 | **+18.3** | **+8.3** | **2.83** |
| **5 day** | 277 bps | +46.6 | **+36.6** | **+26.6** | **4.66** |
| **10 day** | 404 bps | +91.8 | **+81.8** | **+71.8** | **9.18** |

**Decision: do NOT early-stop.** Swing horizons are materially better than intraday (drift ÷ cost
0.5 → 1.9–9.2). Bridge horizons (60–240 min) stay cost-blocked — confirming the instruction not to
reopen intraday mining. **Caveat carried forward:** the positive unconditional swing drift is mostly
market beta (2022 bear year: 5-day drift **−51 bps**, pos-hit 47 %), so the bar for a discovery pass
is *excess over buy-and-hold*, not merely positive net expectancy — encoded in
`SWING_RESEARCH_PROTOCOL.md` S2.

## 4. Partitions & protocol (frozen before hypothesis selection)

`research_partitions.json` / `partition_rationale.md`: Discovery 2020-01-02 → 2023-06-30 (30,798
rows, 4 regimes incl. a full bear), Validation 2023-07-17 → 2025-02-14, Holdout 2025-03-03 →
2026-08-14 (untouched) — chronological, **10-trading-day purge** (= max horizon) so no forward
window crosses a boundary. `SWING_RESEARCH_PROTOCOL.md`: primary metric = net excess bps over the
matched unconditional-long comparator; R-unit fixed at `2.5 × daily ATR%`; costs 0/2/5/10/20 bps
(primary 5, stress 10); overlap handled by symbol-block bootstrap + non-overlapping subsample;
11 pass criteria (S1–S11).

## 5. Family results (discovery; net excess bps @5 bps, primary horizon)

| Family | Best bin | excess net @5 | verdict | one-line finding |
|---|---|---:|---|---|
| **A — multi-day momentum** | `ret_60d_prior` q1 (weakest) | +20.8 | FAIL | momentum does **not** persist; top quintiles & near-highs are **negative**-excess (mean-revert) |
| **B — pullback in uptrend** | 3-day pullback q1 | +13.7 | FAIL | shallow-dip signal is real-signed but half the bar; deeper dips flip negative |
| **C — breakout / expansion** | — | **−19 to −31** | FAIL | breakouts / strong closes **underperform** the drift at 2–3 days (clean negative) |
| **D — oversold rebound** | `dd20 + RSI≤35` | +35.3 (spans 0) | FAIL | real-signed but **regime-episodic** — 45–64 % of positive excess-R from 2020; negative in 2022 |
| **E — gap follow-through** | `gapdn_p10 × vol_high` | +63.7 → +35 matched | FAIL (adjudicated) | up-gaps fade (−36); down-gap edge only in stress regimes = V-bottom artifact |

Full detail: the five `*_analysis.md` files; every row in `EXPERIMENT_LEDGER.csv`.

## 6. The one automated pass, and why it is rejected

`E-gapdn_p10 × vol_high` (bottom-decile overnight down-gap, high realized-vol regime, 3-day hold;
n=1,177) cleared S1–S10 against the global comparator (excess net @5 = +63.7 bps, net @20 = +33.7,
non-overlap CI [+6.4, +138.6], block-boot [+44.7, +112.0], years+ 0.75, symbols+ 0.74). Adjudicated
`DISCOVERY_FAIL`:

1. **Wrong comparator.** Against the **regime-matched** vol_high baseline (55 bps/3 d, not the
   global 26) the excess falls to +35 net @5 and the **non-overlap CI becomes [−22.3, +109.9] —
   includes zero (S4 fail)**; at 5 days that CI is entirely negative.
2. **~77 % is the market.** The equal-weight-basket return over the **exact same event dates** is
   +76.6 bps vs the candidate's +100.2 bps raw (Phase 15). The events sit on days that immediately
   preceded broad rallies; the signal-specific residual (~23 bps) is below the +25 bar.
3. **Negative in the bear year that holds half the events.** By-year excess (vs vol_high baseline):
   2020 +120 · 2021 +140 · **2022 −47 (n = 588 / 1,177)** · 2023 +211 — a crash-recovery / V-bottom
   effect, not a general swing edge.
4. **Phase 13 fail:** remove the best year → **−6.3 bps** (3 d) / **−28.9 bps** (5 d).
5. **Negative on the liquid COMMON10 universe** (−20.7 bps; best-symbol share 0.32).
6. **1 of 35 (family-best × regime) grid cells** — protocol §7 auto-reject for a grid-selected cell
   whose mechanism holds only in a specific historical episode.

## 7. Cost resilience

`cost_sensitivity.csv`. The bins with positive gross excess: `E-gapdn_p10 × vol_high` cost-as-%-of-
edge = 13.6 % @5 bps / 54 % @20 bps; `D-deepdd_fresh3ddrop` 28 % / 114 %; `D-dd20_rsi35` 22 % / 88 %.
So for the near-miss family **cost is not the binding constraint** (unlike Tasks 93–95A) — a +35 bps
gross edge easily carries a 10 bps round trip. The binding constraints are **statistical
separability (S4)** and **year-concentration / instability (S6, S7)**.

## 8. Overlapping-horizon confidence

`statistical_confidence.md`. Every CI uses a symbol-block bootstrap **and** a non-overlapping
subsample; the pass rule requires the lower bound > 0 under both, vs the correct comparator. No claim
uses a naïve i.i.d. bootstrap over overlapping k-day returns. Zero cuts clear S2 + S4 against their
correct comparator, so no multiple-testing correction is needed to reach the verdict.

## 9. Breadth / concentration / turnover

`concentration_analysis.md`, `turnover_capacity.md`. Event- and symbol-level concentration is fine
(top-3 events ≤ 3 %, best symbol ≤ 14 % on the D/E bins). **Year-level concentration is fatal:**
45–64 % of every positive-excess bin's gains come from one calendar year (2020, sometimes + 2023),
and removing it collapses or reverses the effect. Turnover is trivially plausible (0.2–0.35
events/symbol/week for the near-miss bins) — not a reason for failure — but the events cluster in
market-stress episodes, so opportunity flow is lumpy (near-zero in calm years), inconsistent with the
owner's `REGULAR_OPPORTUNITY` intent.

## 10. Why nothing passed

| Cause | Families |
|---|---|
| **No predictive relationship** (excess ≈ 0 or wrong-signed) | A (momentum), C (breakout) — and up-gaps in E. Prior returns, relative strength, new highs, range expansion, strong closes carry no forward information beyond drift; several are *negatively* predictive (short-term reversion dominates). |
| **Signal too small** (real sign, < +25 bps excess) | B (pullback), the plain oversold bins in D |
| **Concentration / instability** (works only at V-bottoms) | D (deep-drawdown), E (down-gap × stress regime). Positive excess is 45–64 % from 2020; negative in the 2022 bear; fails remove-best-year. |
| **Cost** | **Not** the binding constraint at swing horizons (contrast Tasks 93–95A). |
| **Sample size** | Not binding — 30 k discovery daily rows, 1 k–8 k events/bin, 4 regimes incl. a full bear. |

The core result: **at 2–5 day horizons in this 35-name mega-cap universe, price/volume features do
not add directional information beyond general equity drift, except a "buy the crash" reflex that
only pays when the crash is immediately followed by a recovery.**

## 11. Recommendation for the roadmap gatekeeper (NOT auto-started)

Per the task: *"Do not immediately create Task 95C with more feature mining."* The failure is
predominantly **no predictive relationship** in price/volume alone (A, C) plus **regime-instability**
of the one reflex that does show signal (D, E). Options for the gatekeeper to weigh — none started:

- **Different data / feature class:** a clean earnings & corporate-event calendar (Family E is
  price/volume-only by data limitation), analyst-revision / estimate data, sector-relative or
  cross-sectional factor structure, options-implied signals, breadth/positioning data.
- **Non-price information:** news/sentiment, filings, supply-chain, macro nowcasts.
- **Reposition:** TalonX as research / decision-support / risk-and-regime monitoring rather than an
  autonomous long-only alpha engine.
- **Stop autonomous-alpha pursuit** on this instrument set and horizon range.

The `task95b_daily_v1` view and frozen partitions are reusable for any of the first two.

## 12. Production status

**`PRODUCTION_STRATEGY_UNCHANGED`.** `git diff` over `talonx_quant/ talonx_core/ talonx_piv/
talonx_paper/ talonx_brain/ run_talonx.py talonx_ingest/ scripts/` is empty; tree clean at
`4b0e5dfa2415afe1dbf423c63c9cc479264106fa`. All Task 95B work is offline research scripts + gitignored
artifacts under `results/task95b_swing_foundation/`. Research instrumentation is fully isolated from
production decision semantics.

## 13. Live status

**`NO_LIVE_SESSION_REQUIRED_FOR_TASK95B`.** Entirely offline — daily aggregation of an existing local
dataset + vectorised event studies. No Shared Gateway, no Original runtime, no PIV, no paper broker,
no live shadow, no historical-API calls (the source was already local). `NO_LOCAL_AI_REQUIRED`.

---

## Artifacts (`results/task95b_swing_foundation/`, gitignored)

`TASK95B_CHECKPOINT.md` · `aggregation_spec.md` · `aggregated_dataset_manifest.json` ·
`forward_horizon_spec.md` · `horizon_cost_baseline.csv` · `horizon_cost_analysis.md` ·
`research_partitions.json` · `partition_rationale.md` · `SWING_RESEARCH_PROTOCOL.md` ·
`EXPERIMENT_LEDGER.csv` (68 rows) · `momentum_analysis.md` · `pullback_analysis.md` ·
`breakout_analysis.md` · `oversold_rebound_analysis.md` · `gap_followthrough_analysis.md` ·
`regime_conditioning.md` · `cost_sensitivity.csv` · `statistical_confidence.md` ·
`concentration_analysis.md` · `turnover_capacity.md` · `candidate_ranking.csv` (0 pass) ·
`rejected_hypotheses.md` · `FINAL_REPORT.md`. Supporting: `_daily/`, `_daily_all.parquet`,
`_intraday_bridge.parquet`, `_families_results.json`, `_deepdive.json`, `_phase15_comparators.json`,
`_horizon_cost.json`.

## Final action

Task 95B complete. **STOP.** Not starting independent validation, production strategy changes, live
shadow, PIV paper alpha execution, local AI, model training, or another hypothesis family — each
requires a new roadmap authorization. Findings returned to the roadmap gatekeeper.
