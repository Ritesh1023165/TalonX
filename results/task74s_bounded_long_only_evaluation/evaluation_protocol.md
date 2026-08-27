# Task 74S — Evaluation Protocol (preregistered before any replay)

**Label: DEVELOPMENT / ROBUSTNESS EVALUATION.** This is not independent validation and cannot produce
"validated alpha," regardless of outcome (per this task's own instruction).

## 1. Candidate
`TALONX_PRODUCTION_QUANTSCANNER_INTRADAY_LONG_ONLY_V1` — the existing, currently-deployed frozen
strategy (`talonx_quant/strategy.py`, `talonx_quant/consumer.py`, `talonx_quant/indicators.py`,
`talonx_quant/config.py`, all protected/untouched), executed via `talonx_backtest.BacktestEngine`
(reuses QuantScanner's private gate functions directly, not a reimplementation). No parameter is
changed by this task. `talonx_quant.config.QuantConfig()` defaults, spot-checked at HEAD `848de0d`:
`confluence_score_min=2` (unchanged from Task 72O/73S).

## 2. Universe: 10 symbols (resolved from documented evidence — see `stage0_verification_and_inventory.md` §5)
AAPL, MSFT, NVDA, AMZN, META, AMD, TSLA, GOOGL, PYPL, STX — `data/historical_1m/task7b_alpaca_long_history/`.
Selected because repository evidence identifies this as the intended frozen offline research scope
(continuously reused as the "canonical baseline" since Task 4/7B, satisfies the ledger's own documented
`>=10 symbols` research-family minimum, and the one occasion the 35-symbol universe was evaluated for
research purposes — Task 37 — concluded `LIKELY_TOO_SPARSE` and was not adopted going forward). Not
selected by observed returns, signal counts, or performance — decided entirely from provenance
documentation before this task's own replay exists.

## 3. Window
Full common usable period across all 10 symbols: **2025-08-15 13:03:00 UTC → 2026-08-14 23:58:00 UTC**
(~1 year, ~1.90M bars merge-sorted) — the entire dataset on disk, not a cherry-picked sub-window. This
is a broader window than Task 72O/73S's AAPL-only 2025-08-15..2025-12-31 slice, satisfying this task's
"more symbols and/or a longer window" mandate with both.

No reserved holdout is touched: `task56_holdout`/`task56_independent_family_holdout` contain only the
25 additional (non-core) symbols, confirmed by directory listing — zero overlap with this universe by
symbol set, at any date.

## 4. Calendar-month reporting buckets (fixed before any replay; August begins on the 15th)
| Bucket | Start (UTC) | End (UTC) |
|---|---|---|
| 2025-08 (partial) | 2025-08-15 13:03 | 2025-08-31 23:59 |
| 2025-09 | 2025-09-01 00:00 | 2025-09-30 23:59 |
| 2025-10 | 2025-10-01 00:00 | 2025-10-31 23:59 |
| 2025-11 | 2025-11-01 00:00 | 2025-11-30 23:59 |
| 2025-12 | 2025-12-01 00:00 | 2025-12-31 23:59 |
| 2026-01 | 2026-01-01 00:00 | 2026-01-31 23:59 |
| 2026-02 | 2026-02-01 00:00 | 2026-02-28 23:59 |
| 2026-03 | 2026-03-01 00:00 | 2026-03-31 23:59 |
| 2026-04 | 2026-04-01 00:00 | 2026-04-30 23:59 |
| 2026-05 | 2026-05-01 00:00 | 2026-05-31 23:59 |
| 2026-06 | 2026-06-01 00:00 | 2026-06-30 23:59 |
| 2026-07 | 2026-07-01 00:00 | 2026-07-31 23:59 |
| 2026-08 (partial) | 2026-08-01 00:00 | 2026-08-14 23:58 |

13 buckets total (11 full calendar months, 2 partial at the edges of the available data).

## 5. Replay mechanics
- Runner: `talonx_backtest` CLI (direct invocation, one process, all 10 symbols, single chronological
  pass), `--research-telemetry` enabled (needed for the full per-candidate funnel this task's Stage 3
  requires), `--no-progress` suppressed via periodic `--progress-interval` for background monitoring.
- Cost config (primary, unchanged from Task 73S): `--entry-slippage-bps 5 --exit-slippage-bps 5
  --spread-bps 10` → 20bps total round-trip, per `talonx_backtest/execution.py`.
- `--cost-sensitivity` (the repo's own built-in sweep) is **not** used for the secondary grid — see §6.
- Pre-roll: none manufactured; the full downloaded history IS the pre-roll for early bars (RSI(14)/
  MACD(12,26,9)/ATR(14) warm up within the data itself; `compute_indicators` returns `None` during
  warm-up and both live/backtest fail closed identically). The 200-bar/15-min HTF trend gate warms up
  within the first ~8 trading days of this ~1-year window — immaterial, per Task 73S's own finding that
  HTF warmup was never a blocker for a window of this length.
- Runtime estimate: Task 36 (`docs/research/TALONX_RESEARCH_LEDGER.md`, identical 1,903,044-bar/
  10-symbol dataset, `research_telemetry=True`) completed in **233.8 minutes**. This run is expected to
  take a comparable time; launched as a single background process, not re-launched or re-scoped based
  on any interim result.

## 6. Cost sensitivity grid — analytic recomputation, not a second replay
Per this task's "one frozen replay" requirement, the secondary zero/half/baseline/double grid is
derived from the **same single primary replay's trade population**, not from additional
`BacktestEngine` passes. This is justified directly from `talonx_backtest/execution.py`, read and
verified before this decision was made:
- `TradeSimulator.open_position`: `risk = abs(entry_price_raw - signal.stop_price)` — raw-price only.
- `check_bar_for_exit`: compares `bar_high`/`bar_low` against raw `stop_price`/`target_price` — cost
  never enters trade-identification or exit-reason determination (TARGET/STOP/SIGNAL_EXIT/
  END_OF_SESSION/DATA_END is decided identically regardless of cost config).
- `Trade.entry_price`/`Trade.exit_price` (in `trades.csv`) are the **raw** fill prices; `net_pnl`/`net_R`
  are computed from `apply_entry_cost`/`apply_exit_cost`, a pure deterministic function of
  `(raw_price, direction, bps)` (`_apply_cost`, execution.py:48-57).
- Therefore, for any cost scenario, `net_pnl(bps) = (apply_exit_cost(exit_price_raw, dir, bps) -
  apply_entry_cost(entry_price_raw, dir, bps)) * direction_sign` is exactly what a fresh
  `BacktestEngine` run at that `bps` config would produce for the same trade — recomputing this in
  post-processing from the primary run's `trades.csv` is mathematically identical to re-running the
  engine, not an approximation, and requires no additional replay.

Grid (uniform `entry_slippage_bps = exit_slippage_bps`, `spread_bps = 2x` that, matching the primary's
5/5/10 shape, scaled): zero (0/0/0 → 0bps RT), half (2.5/2.5/5 → 10bps RT), baseline (5/5/10 → 20bps RT,
primary), double (10/10/20 → 40bps RT). Fixed before any replay is run; not adjusted after seeing
results.

## 7. Sample-size threshold
No defensible trade-count threshold for this specific universe/window is documented anywhere in this
repository (checked: `docs/backtesting.md`, `docs/research/TALONX_RESEARCH_LEDGER.md`). Per this task's
own instruction, **none is invented**. If trades exist, sample-size adequacy is discussed qualitatively
(concentration, dependence, count vs. the ledger's own general small-sample caution) — not measured
against a threshold manufactured after seeing the count.

## 8. Decision gates / classification labels (fixed in advance, reused from Task 73S's protocol)
- Zero trades anywhere → economics `N/A`; profitability verdict `INCONCLUSIVE`.
- Non-zero trades, positive net-of-primary-cost economics → **at most** "justifies untouched
  validation" — never "validated alpha," never `VALIDATED_AND_REPLICATED` (that requires a separate,
  untouched validation-window run this task does not perform).
- Non-zero trades, negative/mixed economics → reported as such; not reframed, not re-scoped, not used
  to justify a parameter change (frozen strategy).
- Portfolio-level returns/drawdown are **not** reported unless concurrency/sizing/capital/overlap are
  actually modelled (they are not, in this harness) — outputs are labeled trade-level statistics only.
- Correlated trades (same symbol, overlapping regime) are not treated as independent observations
  without qualification.
- If a genuine correctness defect is discovered mid-replay, the run stops and is reported as-is — it is
  not silently patched and continued under the same experiment identity.

## 9. Anti-p-hacking commitments (verbatim constraints, restated as commitments)
Universe, dates, cost grid, and calendar buckets above are fixed now, before Stage 2/3 execute, and
will not be altered after seeing results. No repeated re-scoping. No forward-filling of missing data.
No holdout access. No IEX/SIP substitution. This experiment runs once.

## 10. Artifacts and commit plan
Stage 1 (this preregistration: `preregistration.json`, `universe_manifest.csv`, `data_manifest.csv`,
`evaluation_protocol.md`) is committed **before** Stage 2/3 launch the replay. Stage 2/3/4/5 evidence
is committed as a separate, subsequent checkpoint. Runner changes (if any prove necessary) are
committed separately from research evidence, per this task's own instruction.
