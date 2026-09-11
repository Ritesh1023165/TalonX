# TalonX — Paper Trading Model

Three **completely separate** simulated ledgers. None touches a broker or real capital. The
dashboard never merges them into one "positions" number.

| ledger | engine | store | attribution | started by |
|---|---|---|---|---|
| **Original local paper** | `talonx_paper.consumer.PaperTradingEngine` / `LongTermPaperEngine` | `~/.talonx/paper_trading.db` | `ORIGINAL / local-only (no broker)` | `run_talonx.py` |
| **Experimental validation paper** | `talonx_signals.experimental_paper.ExperimentalPaperEngine` | `~/.talonx/experimental/experimental_paper.db` | `EXPERIMENTAL / validation-only, simulated, no real capital` | `python -m talonx_signals.run` |
| **PIV Alpaca PAPER** | `talonx_piv` | Alpaca PAPER account (independent) | `PIV / Alpaca PAPER (independent)` | opt-in `python -m talonx_piv.cli` only |

## Rules

- **Long-only.** `SELL` / `EXIT` closes an existing long. There is no `open_short` method
  anywhere in `talonx_paper` or `talonx_signals.experimental_paper`.
- **`BEARISH` is informational** — it is a directional label on an alert, never an order.
- Original paper: ATR-anchored intraday stops; a DCA-aware long-term ledger (Phase 2 horizon).
- Experimental paper: opened from relaxed-profile `WOULD_PASS` candidates; fully isolated — a
  separate `PaperTradingStore` file/instance, never the same object as Original's.
- PIV: `talonx_piv` structurally cannot route real capital (`PaperGuardError` on
  `real_capital=True`; `TALONX_PIV_REAL_CAPITAL=false`). Never surfaced as Original local paper.

## Settings

Routine paper settings — per-symbol enable/disable (intraday + long-term), trade allocation
`$/position`, DCA `$/cycle` — are edited on **`:8787/admin/`** (see `docs/ADMIN.md`).

Destructive actions — reset intraday portfolio, reset long-term portfolio (both
`DELETE FROM positions; DELETE FROM trade_history`), and starting-balance edits — remain on
**`:8501`** behind a confirm checkbox (see `docs/COMPATIBILITY.md`).

## EOD reconciliation

`talonx_ops.eod_reconciliation.EodReconciliationStore` writes one durable row per session date
(`~/.talonx/eod_reconciliation.db`) on controlled shutdown: Original / Experimental paper open
positions + trades, PIV positions/orders (`NOT_CHECKED` unless an explicit read-only reader is
injected — never fabricated `0`), alert counts, reconciliation status, mismatch details,
timestamp. Idempotent per session. Read via `supervisor status` or the `:8787` Paper/EOD section.

## Forward outcomes (Experimental only)

`talonx_signals.telemetry.ForwardOutcomeRecorder` advances MFE / MAE / +30m / +60m / EOD / +1D
for every open Experimental observation from the same causal live bar stream (Task 99G) — no
separate polling loop. Stored in `~/.talonx/experimental/forward_outcomes.db`. This is validation
telemetry, not a P&L claim.
