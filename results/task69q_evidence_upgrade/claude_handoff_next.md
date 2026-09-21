# Claude Handoff — after Task69Q

## Immediate next priority

**Task70: accelerated frozen-alpha validation / historical holdout
assessment.** Do not get pulled back into infrastructure — Task69Q's own
instructions were explicit about this ("do not spend days perfecting
infrastructure"), and the operational/evidence gaps that mattered are closed
or documented. Runtime live sessions can continue in parallel on market days.

## If you're asked to run the next live PAPER session

Read `next_live_session_plan.md` first. Key points:
- Do NOT pass `--confirm-piv-lifecycle-probe` unless broker/lifecycle code
  changed materially since Task69P — it's already validated.
- Pre-market radar runs automatically from 04:00 ET; no action needed to
  enable it, and nothing you do there can place an order (see
  `premarket_radar_contract.json`'s structural guarantee).
- After `eod`, check `quant_funnel.unaccounted_candidates == 0` in
  `latest_session_report.json` before trusting the funnel numbers.

## If you're asked to continue the warmup-provider migration (PRG-07)

`talonx_piv/alpaca_historical_warmup.py::fetch_1m_bars()` is verified against
the real Alpaca API and unit-tested, but not wired into
`talonx_quant.consumer.QuantScanner`'s buffers. Before wiring it in:
1. Check what shape `RollingBarBuffer` (talonx_quant, likely `store.py` or
   similar) expects for `add_bar`/equivalent, and how `buffer_htf`'s 15m
   data is currently populated by `preseed.py` (native 15Min timeframe fetch,
   or 1m aggregation) — match that exactly.
2. Do NOT touch `talonx_quant/consumer.py`, `strategy.py`, `indicators.py`,
   `config.py` — this is a warmup DATA SOURCE change, the consumer of that
   data (the buffers) is a separate, non-protected surface
   (`talonx_quant/preseed.py`, or a new module) you CAN edit.
3. Keep yfinance as the default until the Alpaca path is proven against the
   full 35-symbol universe (only 3 symbols were spot-checked this task).
4. Add a config flag rather than a hard swap, so a bad migration can be
   reverted by config alone.

## If you're asked about the position lifecycle fix (Part 5)

`talonx_piv/lifecycle.py`'s `PaperLifecycle.apply_broker_update()` now
distinguishes an exit fill (sell, matching `open_position_by_symbol`) from an
entry fill by `side` + a symbol-keyed open-position map, not just by
`position_id`. This has NOT yet been exercised against a real live natural
fill (Task69P had zero natural signals) — the next live session is the first
real-world test of this path. If anything looks off in a live
`POSITION_CLOSED` event, check `talonx_piv/lifecycle.py`'s
`apply_broker_update` first.

## If you're asked why /ping shows different things for PIV vs the general app

`talonx_dispatch/telegram_listener.py`'s `_pipeline_status()` and
`_piv_section()` both branch on whether `piv_info` (a dict, not `None`) was
passed — this is intentional and tested
(`test_pipeline_status_general_app_behavior_unchanged_when_no_piv_info`).
Don't "fix" the general app's behavior to match PIV's — they're deliberately
different because they observe different subsystems.

## Files worth reading first if you're new to this task's changes

- `results/task69q_evidence_upgrade/task69q_summary.md` (this task, overview)
- `docs/research/TALONX_PIV_RUNTIME_PRODUCT_TARGET.md` (the permanent
  product direction this task recorded)
- `results/task69q_evidence_upgrade/production_readiness_gaps.json` (every
  known open item, with severity and a recommended next step)
