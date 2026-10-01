# TASK 95B — LONGER-HORIZON / SWING ALPHA RESEARCH FOUNDATION — CHECKPOINT

> Authoritative Task 95B memory. **After any context/session refresh: READ THIS FIRST**, then continue
> from "EXACT NEXT ACTION". Offline research only — no production strategy change, no intraday-threshold
> tuning, no live session, no PIV alpha execution, no local AI, no real capital.
> **Primary question:** *"Does increasing the holding horizon (multi-hour → 1–5 day) produce market
> moves large enough that a one-off round-trip cost becomes economically small relative to the
> opportunity — and is there any repeatable, cost-robust, broad, causally-identifiable long-only
> phenomenon at those horizons?"*
> **Deliberate hypothesis-space pivot: 1-minute / short-intraday feature mining is STOPPED.**

## Fixed inputs

| | |
|---|---|
| Starting SHA | `4b0e5dfa2415afe1dbf423c63c9cc479264106fa` (tree clean, verified) |
| Production strategy | UNCHANGED — research code isolated from production decision semantics |
| Source dataset | `task95a_expanded_v1` — 35 sym, 25,806,723 Alpaca SIP 1-min bars, 2020-01-01→2026-08-14, fingerprint `8333c1001e28ee18…` (`results/task95a_regime_expansion/_expanded_data/`). **Not redownloaded.** |
| Prior verdicts | T93 `CURRENT_STRATEGY_EDGE_WEAK_OR_UNPROVEN` · T94 `ALPHA_DISCOVERY_NO_CANDIDATE_PASSED` · T95A `INTRADAY_ALPHA_NOT_SUPPORTED_ACROSS_EXPANDED_REGIMES` |
| Prior finding | intraday long forward drift ≈ 5 bps/30min ≈ one round-trip cost, across all regimes / 6.6y |

## First principle (gate before any feature research)

Measure **MOVE_TO_COST_RATIO** — how forward-return magnitude scales with horizon vs cost.
If no longer horizon gives materially better move-to-cost economics than intraday →
`SWING_HORIZON_ECONOMICS_NOT_PROMISING`, STOP before Phases 5+.

## Aggregation status (Phase 1)

- `t95b_build_daily.py` (bg `b7ihxt8bd`) IN PROGRESS (~21/35). Builds `_daily/<SYM>.csv` +
  `_daily_all.parquet` + `_intraday_bridge.parquet`.
- Daily = regular session only (09:30≤et_min<16:00 ET, Mon-Fri, ≥60 1-min bars/day). **Split-adjusted**
  `adj_*` OHLC (raw retained; volume NOT adjusted, flagged). Forward returns close-to-close on
  `adj_close` for +1/2/3/5/10d + overnight; returns spanning a split ex-date nulled.
- Causal daily features: ret_{1,3,5,10,20,60}d_prior, sma20/50/200 + above flags, atr14/atr_pct,
  rv20/rv60, 20/60d high-low position, close_vs_hi20, dd_from_hi_all, rsi14 (daily Wilder),
  vol_ratio_20. Intraday bridge: 10:00 ET entry → +60/120/240 min same-session fwd returns.

## Research horizons (Phase 2 — pre-registered, see forward_horizon_spec.md when written)

Bridge (transitional, NOT a reopening of 5–30 min mining): +60, +120, +240 min.
Swing: +1, +2, +3, +5 trading days (close-to-close), + overnight; +10d optional.

## Phase 1-4 — DONE

- `task95b_daily_v1`: 51,922 split-adjusted daily bars, 35 sym, 2020-01-02→2026-08-14. Validated vs
  raw 1-min (OHLC identical, fwd_5d exact). `aggregation_spec.md`, `aggregated_dataset_manifest.json`,
  `forward_horizon_spec.md`. 11 splits handled; split-spanning fwd returns nulled.
- Partitions frozen (`research_partitions.json`, 10-day purge): Discovery 2020-01-02→2023-06-30
  (30,798 rows, 4 regimes incl. full bear), Validation 2023-07-17→2025-02-14, Holdout
  2025-03-03→2026-08-14 (UNTOUCHED).
- `SWING_RESEARCH_PROTOCOL.md` frozen BEFORE hypothesis selection: metric = net **excess** bps over
  matched unconditional-long comparator; R-unit = 2.5×daily ATR%; costs 0/2/5/10/20 (primary 5);
  overlap CI = symbol-block bootstrap + non-overlapping subsample; S1–S11 criteria.

## Phase 3 — EARLY-STOP GATE: PASSED (do NOT stop)

`horizon_cost_analysis.md`. Swing horizons materially better than intraday: abs move 116/209/277/404
bps at 1/3/5/10d (vs ~35 bps @30min); drift÷cost(5bps) 0.96/2.83/4.66/9.18 (vs ~0.5 intraday); net
long expectancy positive after 5 bps from 2d out. **Bridge horizons (60-240min) stay cost-blocked.**
Caveat: unconditional swing drift is mostly market beta (2022 bear: 5d drift −51 bps) → bar is
EXCESS over buy-and-hold (protocol S2 = excess net@5 ≥ +25 bps).

## Phases 5-16 — DONE. RESULT: `SWING_ALPHA_NO_CANDIDATE_PASSED`

- **68 experiments** (A momentum 25, B pullback 10, C breakout 11, D oversold 11, E gap 11 incl.
  35 regime cells). `EXPERIMENT_LEDGER.csv`. **0 DISCOVERY_PASS after adjudication.**
- A (momentum): no persistence; top-quintile & near-high are NEGATIVE-excess (mean-revert).
  C (breakout): all NEGATIVE-excess at 2-3d (breakouts underperform drift). B (pullback): +4..+14
  bps, sub-threshold. D (oversold) + E (gap): real-signed but **regime-episodic** — 45-64% of
  positive excess-R from 2020 (+2023) V-bottoms; NEGATIVE in 2022 bear.
- **1 automated PASS** (`E-gapdn_p10 × vol_high`, k=3, n=1177, excess net@5 +63.7 vs global) →
  **adjudicated FAIL**: wrong comparator (vs regime-matched vol_high baseline → +35, non-overlap CI
  [-22,+110] spans 0 = S4); ~77% is same-dates market move (Phase 15 basket +76.6 vs +100.2 raw);
  2022 (588 of 1177 events) NEGATIVE; remove-best-year → −6.3/−28.9 bps (Phase 13 S6 FAIL); NEGATIVE
  on COMMON10; 1-of-35 grid cell (§7).
- **Why nothing passed:** no predictive relationship (A, C — price/volume carries ~0 info beyond
  drift, often mean-reverts); signal too small (B, plain D); concentration/instability (D, E — only
  the "buy the crash" reflex shows signal, and only when the crash is followed by a recovery).
  NOT cost (favorable at swing horizons), NOT sample size.

## Blockers

- None. Task 95B complete.
- Data limitation logged: no earnings/catalyst calendar in task95a_expanded_v1 → Family E is
  price/volume-only (mechanical gaps, not post-event drift).

## EXACT NEXT ACTION

Task 95B finished; result returned to gatekeeper. **Do NOT start** independent validation, strategy
changes, live shadow, PIV alpha, local AI, model training, or Task 95C feature mining — each needs
new roadmap authorization. If resumed: nothing to do; `FINAL_REPORT.md` + all 23 artifacts complete;
tree clean at `4b0e5df`; 0 residual processes. Roadmap options for the gatekeeper (not started):
different data/feature class (earnings calendar, factor structure, options-implied), non-price
information, reposition as decision-support, or stop autonomous-alpha pursuit.
