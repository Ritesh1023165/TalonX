# TalonX Documentation

Start with the root [`../README.md`](../README.md) for the one-page overview, then use this index.

## Current product docs (authoritative — post-Task 104)

| doc | covers |
|---|---|
| [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md) | **the single authoritative architecture description** — supervision, market path, Original, Experimental, Intelligence, Ops, UI, Telegram, PIV, boundaries |
| [OPERATIONS.md](OPERATIONS.md) | start / status / stop / EOD; which script is authoritative; the pending live qualification |
| [DASHBOARD.md](DASHBOARD.md) | `:8787` cockpit (six sections + legacy tabs), false-zero semantics, `:8760`, `:8770`, `:8501` |
| [ADMIN.md](ADMIN.md) | `:8787/admin/` — the 9 controls, the denylist, the audit log, safety properties |
| [INTELLIGENCE.md](INTELLIGENCE.md) | the Risk & Event Intelligence layer (Task 96) — descriptive, deterministic, no forward-return |
| [PAPER_TRADING.md](PAPER_TRADING.md) | the three separate simulated ledgers, EOD reconciliation, forward outcomes |
| [BACKTESTING.md](BACKTESTING.md) | `talonx_backtest`, datasets, methodology contract, how to add a new hypothesis safely |
| [RESEARCH_STATUS.md](RESEARCH_STATUS.md) | consolidated Task 93-101 verdicts — **no robust free intraday alpha; research lane closed** |
| [DATA.md](DATA.md) | data catalog — live stores, SEC data, research datasets (locations, sizes, sources) |
| [SAFETY_BOUNDARIES.md](SAFETY_BOUNDARIES.md) | Original vs Experimental, external-alert boundary, no shorts / no real capital / no paid data, frozen settings |
| [COMPATIBILITY.md](COMPATIBILITY.md) | `:8770` / `:8501` deprecation status + removal conditions; legacy scripts |
| [CHANGELOG.md](CHANGELOG.md) | baseline changelog — Task 100 → 105 |

## Research / owner history (kept — do not merge into the current docs)

- [research/TALONX_RESEARCH_LEDGER.md](research/TALONX_RESEARCH_LEDGER.md) — append-only
  chronological history of every research/validation task.
- [research/TALONX_PRODUCT_STRATEGY_SPEC.md](research/TALONX_PRODUCT_STRATEGY_SPEC.md),
  [research/TALONX_OWNER_DECISIONS.md](research/TALONX_OWNER_DECISIONS.md),
  [research/TALONX_PIV_RUNTIME_PRODUCT_TARGET.md](research/TALONX_PIV_RUNTIME_PRODUCT_TARGET.md),
  `research/task21_frozen_early_failure_spec.json` — frozen product/strategy decisions and a
  SHA-referenced early-failure spec.

## Pre-consolidation docs (superseded — retained as history)

These describe the pre-Task-100 "six cooperating modules" layout and are **superseded by
`CURRENT_ARCHITECTURE.md`**. They remain for their still-accurate low-level detail (indicator
math, env-var reference, bar-buffer persistence, earnings/pre-market radar internals) and are not
deleted:

`architecture-overview.md` · `modules/{ingest,quant,brain,core,dispatch,paper,orchestrator}.md` ·
`setup.md` · `running.md` · `troubleshooting.md` · `configuration.md` · `performance.md` ·
`roadmap.md` · `phase2-multi-horizon.md` · `earnings-radar.md` · `premarket-radar.md` ·
`bar_buffer_persistence.md`.

(`backtesting.md` was renamed to `BACKTESTING.md` and rewritten in Task 105 — it is a **current**
doc, not superseded.)

When these conflict with a current doc, the current doc wins.
