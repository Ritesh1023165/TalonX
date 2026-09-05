# TalonX — Compatibility & Deprecated Paths

Nothing here is on the primary path. All of it is retained deliberately for rollback / residual
capability, and none of it is started by `talonx_ops.supervisor`.

## `:8770` — legacy Experimental validation dashboard

- **Status: `DEPRECATED / COMPATIBILITY ONLY`.**
- Embedded in `python -m talonx_signals.run` (the Experimental lane's own telemetry dashboard).
- `:8787`'s VALIDATION section reached **5/5 offline feature parity** (Task 100C
  `task8770_parity_report.md`). All hard removal criteria pass: no default startup reference, no
  unique store writer (the `:8770` dashboard is a pure reader of `exp_alerts.db` /
  `experimental_paper.db` / `forward_outcomes.db`), no external-send dependency, rollback command
  documented.
- **Removal condition:** one real live row-level parity session (Task 103) confirming the `:8787`
  VALIDATION numbers match a running `:8770` row-for-row. Until then `:8770` is not physically
  removed — deleting it now would reduce rollback safety.
- **Rollback start:** `python -m talonx_signals.run` (binds `:8770` as before — unchanged).

## `:8501` — Streamlit (`talonx_dispatch/app.py`)

- **Status: `8501_RETAINED_RESIDUAL`.**
- Retained for capabilities with no replacement:
  - **Destructive paper resets** — `reset_portfolio` / `reset_long_term_portfolio` (each does
    `DELETE FROM positions; DELETE FROM trade_history; …=0`). Not migrated — a dashboard is not
    the place to delete trade history without an archive.
  - **Starting-balance edits** — reset-adjacent; a standalone edit would silently re-base
    `total_pnl`. Bound to the reset flow.
  - **Long-term valuation / research views** — `render_valuation_radar`,
    `render_long_term_research_viewer`, `render_long_term_portfolio` (read-only, cadence-driven,
    outside the intraday cockpit's scope).
- Routine config editing (watchlist membership/routing, paper $ amounts) has **moved to
  `:8787/admin/`** — the `:8501` copies are now redundant duplicates, to be removed in a future
  task once `/admin/` has soaked.
- **Removal condition:** a safe destructive-reset workflow (typed confirmation + engine label +
  affected-state preview + audit + history archive) **and** a home for the long-term research
  views, **and** updating `scripts/start_talonx.ps1` + `register_scheduled_tasks.ps1` to stop
  launching Streamlit.
- **Start:** `.\scripts\start_talonx.ps1` (LEGACY) or `python -m streamlit run talonx_dispatch/app.py`.

## Legacy startup scripts

| script | status | note |
|---|---|---|
| `scripts/start_talonx.ps1` | **LEGACY / COMPATIBILITY** | `run_talonx.py` + Streamlit `:8501` only; header marked; used by `register_scheduled_tasks.ps1`'s 10am task |
| `scripts/register_scheduled_tasks.ps1` | LEGACY | schedules the above — unchanged |
| `scripts/start_dashboard_web.ps1` / `stop_dashboard_web.ps1` | UTILITY | `:8787` only, without the supervisor |
| `scripts/stop_talonx.ps1` | UTILITY | legacy stop helper |
| `send_test_signal.py` / `send_test_report_pair.py` | DEV / COMPATIBILITY | manual Telegram formatting/wiring probes; not on any runtime path |
| `generate_eod_report.py` | OPS UTILITY | standalone EOD report generator; the authoritative reconciliation store is `talonx_ops.eod_reconciliation` |

**Do not** use `scripts/start_talonx.ps1` as the default startup. The one recommended path is
`scripts/start_talonx_supervised.ps1` (`docs/OPERATIONS.md`).

## `talonx_piv` — Alpaca PAPER validation harness

Not deprecated, but **opt-in and separate**: `python -m talonx_piv.cli`. Never started by the
supervisor or the dashboard. Alpaca PAPER only; structurally cannot route real capital. Its
runbook: `results/task64_paper_piv_readiness/piv_runbook.md`.

## `talonx_compare` — Original-vs-PIV comparison collector

Dormant while PIV is not running. Consumed by `:8787`'s legacy "Compare" tab. Default state/
evidence dirs live under `results/task83_dashboard_comparison_qualification/`.
