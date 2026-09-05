# Task 74S — Stage 0: Verify and Inventory

## 1. Baseline verification
- Branch: `research/talonx-strategy-validation` (matches expected).
- Starting HEAD: `848de0d6388f59972d8dce9b35cb45f35fe0173e` (matches expected exactly).
- Working tree: clean (`git status --short` empty).
- Origin sync: `origin/research/talonx-strategy-validation` == local HEAD (fetched, confirmed identical SHA).
- No concurrent session: `.run/talonx.pids.json` PIDs (21336, 13732, started 2026-08-17) are not
  running (`ps -W` shows no match) and are known Windows venv-shim artifacts (stale, pre-existing
  finding from earlier sessions). `logs/task69r_live_paper_2026_08_26/` is a separate, already-
  concluded live PAPER session from 2026-08-26 (yesterday) — unrelated task, not active, not touched.
  No `lifecycle_state.json` shows an active/enabled session for this checkout right now.

## 2. Prior evidence re-read
- Task 72O (`results/task72o_overnight_stabilization/`): established the frozen candidate
  `TALONX_PRODUCTION_QUANTSCANNER_INTRADAY_LONG_ONLY_V1`, ran AAPL-only over
  `data/historical_1m/task7b_alpaca_long_history`, 2025-08-15..2025-12-31, zero trades, GO for
  operational-only live session.
- Task 73S (`results/task73s_regression_and_zero_trade_diagnosis/`): repaired the regression fixture,
  reproduced Task 72O's AAPL run byte-for-byte (`config_hash=3556debe52af`, `dataset_hash=7b14ce2e50df`),
  built the full zero-trade funnel (99.47% bars rejected by `LOW_VOLATILITY`), proved the harness has
  no defect via 3 labeled control-fixture tests, and recommended a broader (more symbols / longer
  window) evaluation of the same frozen strategy — i.e., exactly this task.

## 3. Scanner identity (re-confirmed, unchanged since 848de0d)
- `talonx_backtest.BacktestEngine` does not instantiate a live `QuantScanner` object; it imports and
  reuses QuantScanner's own private gate functions (`_GATE_NAMES`, `_confluence_eligible`,
  `_evaluate_active_volatility_gate`, `_fails_min_volatility`, `_opportunity_score`, `_partition`,
  `_trend_gate_applicable` from `talonx_quant.consumer`) plus `talonx_quant.strategy.evaluate_signals`
  / `calculate_trade_geometry` directly, under its own chronological single-pass replay.
- Long-only lifecycle is hardcoded engine behavior (Task 24/25A): only BULLISH signals ever open a
  position; `TradeSimulator.open_position` fails closed on any non-BULLISH signal.
- `talonx_quant.config.QuantConfig()` defaults unchanged: spot-checked `confluence_score_min == 2`
  in the current tree at HEAD `848de0d`.
- `git diff df6da2b..848de0d -- talonx_quant/strategy.py talonx_quant/indicators.py talonx_quant/consumer.py talonx_quant/config.py talonx_piv/eod_lifecycle.py talonx_piv/session_runner.py talonx_piv/cli.py talonx_piv/events.py`
  is empty (protected files and EOD code unchanged across both prior tasks).

## 4. Cost interpretation (unchanged, reused verbatim from Task 73S)
`entry_slippage_bps=5, exit_slippage_bps=5, spread_bps=10` → 10bps total entry-side + 10bps total
exit-side = **20bps total round-trip cost**, verified directly from
`talonx_backtest/execution.py::apply_entry_cost/apply_exit_cost`. This is the "primary" cost point
this task's Stage 4 will reuse unchanged.

## 5. Universe resolution — 10-symbol vs 35-symbol (resolved from documented evidence only)

**Decision: use the 10-symbol universe** (`AAPL, MSFT, NVDA, AMZN, META, AMD, TSLA, GOOGL, PYPL, STX`
via `data/historical_1m/task7b_alpaca_long_history/`), **not** the 35-symbol
`talonx_piv.config.PivConfig.DEFAULT_UNIVERSE`.

This is a documented-evidence override of the task's stated default preference ("prefer the 35"),
permitted explicitly by the task's own escape clause: "Use the legacy 10 only if repository evidence
identifies it as the intended frozen research scope." It does. Evidence, all from
`docs/research/TALONX_RESEARCH_LEDGER.md` (no result/performance data consulted):

- The 10-symbol universe was established at Task 4 ("10-Symbol Trade-Lifecycle Discovery") and
  Task 7B/8 (full-year Alpaca pull, `data/historical_1m/task7b_alpaca_long_history/`, hash
  `5e5412a960bf`) and has been the **continuously-reused frozen research dataset** for every
  profitability/alpha-research task since: Task 24/25A (long-only fix), Task 26, Task 36 ("structural
  stop **canonical baseline**"), Task 53/54/55/56 (RSI/MACD family research, "the original 10"),
  Task 58, Task 61R (FPRC_V1), Task 63/63R (ORPB_V1), and Task 72O/73S (this line). It is repeatedly
  called the "canonical baseline" / "frozen candidate" dataset in the ledger (e.g. lines ~314, 351,
  691, 716, 1274, 2812, 3320, 3968, 5664).
- A mandatory research-family criterion documented in the ledger (line ~5664) requires
  "`>=10 symbols`" — i.e. the 10-symbol universe is itself the documented minimum bar for a research
  candidate, not a placeholder awaiting expansion.
- The **35-symbol universe was explicitly evaluated once, separately, as a feasibility check** (Task
  37, "Fast Production-Universe Feasibility Check"), and that check's own conclusion was
  `LIKELY_TOO_SPARSE` — expanding to 35 did not become the new frozen research scope; every
  alpha-research task after Task 37 (53 through 64) continued using the 10-symbol universe, not 35.
- Every ledger reference to "the frozen 35-symbol universe" (e.g. line ~5929, Task 64 Paper PIV
  Readiness) is in the context of the **live/operational PIV product universe**
  (`talonx_piv.config.PivConfig.DEFAULT_UNIVERSE`), used for broker/session/Telegram preflight — never
  as an offline research/backtest scope.
- **Holdout non-overlap confirmed by symbol set, not just dates**: `data/historical_1m/task56_holdout/`
  and `task56_independent_family_holdout/` (H1_early/H2_middle/H3_late) contain ONLY the 25
  *additional* symbols beyond the original 10 (ADBE, ADI, AMAT, AVGO, BKNG, CMCSA, COST, CSCO, GILD,
  HON, INTC, INTU, ISRG, KLAC, LRCX, MDLZ, MU, NFLX, PANW, PEP, QCOM, REGN, SBUX, TXN, VRTX) —
  verified by directory listing. None of the 10 core symbols appear in any holdout directory at all,
  at any date. Selecting the 10-symbol universe therefore has **zero holdout overlap by construction**
  (disjoint symbol sets, not merely disjoint dates) — no stop-and-request-direction trigger applies.

**Conclusion**: the 10-symbol universe is the intended frozen offline research scope; the 35-symbol
universe is the product's operational/live universe and was itself found too sparse in its one
feasibility check. Proceeding with the 10-symbol universe is the evidence-driven choice, decided
entirely before any Task 74S replay is run.

## 6. Data inventory (task7b_alpaca_long_history, common usable period)
All 10 symbols: `status: FULL`, `requested_start=2025-08-15`, `requested_end=2026-08-14`, provider
`alpaca` — per the ledger's own Task 7B section title ("Task 7B — Long-History Dataset (Alpaca SIP)"),
this is **SIP** consolidated-tape data, not IEX. Per-symbol bar counts (sum = 1,903,044, matching Task
26/36's own recorded total exactly, confirming this is the same canonical dataset): AAPL 189,563, MSFT
199,156, NVDA 237,875, AMZN 194,988, META 184,201, AMD 204,714, TSLA 234,652, GOOGL 191,394, PYPL
142,095, STX 124,406. STX starts later in the day (2025-08-15 13:03 UTC vs. 08:00 UTC for the others)
and ends one minute earlier (23:58 vs 23:59 UTC) than the rest. Per the ledger's own established
convention (line ~673-676), the **common usable period across all 10 symbols is 2025-08-15 13:03 UTC
→ 2026-08-14 23:58 UTC**, ~1,901,714 bars when merge-sorted across symbols (the figure already reused
unchanged through Task 8/13/13B/22/26/36) — this is the window this task's replay will request, not a
new derivation. Dataset hash `5e5412a960bf` (`talonx_backtest.reproducibility.get_dataset_hash`).

## 7. Non-goals confirmed
- Validation windows (`task46_validation_windows`, `task54_extended_windows`) and retired research
  lines (`task61r_fprc_v1_validation`, `task63_orpb_v1_validation`) are not read or touched.
- Reserved holdouts (`task56_holdout`, `task56_independent_family_holdout`) are not read or touched
  (directory *listing* only, to confirm symbol-set disjointness above — no file contents opened).
- No protected file, no EOD code, no live session, no broker/Telegram/Gemini call.

**Stage 0 verdict: PASS.**
