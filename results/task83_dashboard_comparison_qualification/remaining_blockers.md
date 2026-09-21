# Task 83 — Remaining Blockers vs Backlog

## Blockers to the separately-authorized shadow pilot: none from this task

Task 83 delivers the dashboard/comparison layer and the offline dual-run
qualification. It does not itself unblock a live session — that remains a
separate operator authorization.

## Explicit capability limitation (surfaced, not fixed) — §6

### PIV has no durable QuantStateStore

- The reused in-process PIV `QuantScanner` runs **without** a `QuantStateStore`.
  Rolling bar buffers and funnel counters are in memory only and do **not**
  survive a PIV restart.
- Task 82 reserved an isolated path `<PIV state_dir>/piv_quant.db` so a future
  enablement cannot select Original's database. **That reserved, isolated path
  is not evidence that persistence exists.** Its presence or absence on disk
  is reported (`isolated_path_present_on_disk`) precisely so a dashboard can
  never imply persistence from the path alone.
- Exposed as:
  - `talonx_piv.observability.build_integrated_projection(...)["capability_limitations"]["durable_quant_state_store"]`
    (`status: NOT_IMPLEMENTED`, `persistence_exists: false`);
  - `talonx_compare.health.QUANT_STATE_STORE_LIMITATION`, rendered in the browser
    PIV view and the Streamlit "PIV & Comparison" section.
- **Not implemented in this task.** Implementing a durable `QuantStateStore` is a
  separate backlog item; no Task 83 dashboard requirement needed it to be
  represented honestly (the limitation itself is the honest representation).

## Unresolved question kept open — §6

### IEX receipt-time vs source-time

- Whether PIV bar timestamps reflect IEX source time or local receipt time is
  still not established (carried over from Task 81 §5 / the Task 82 handoff).
- The comparison schema carries **both** `event_time` and `source_bar_time` on
  every `ComparisonRecord`, and `FEED_INPUT_DIFFERENCE` keys on `source_bar_time`,
  so both timestamps can be displayed and compared once a raw per-bar source-time
  log exists.
- No live or historical data acquisition is authorized to resolve it. Surfaced in
  the PIV view under `unresolved_questions` with `state: UNRESOLVED`.

## Backlog (not blockers)

| Item | Why deferred |
|---|---|
| Durable PIV `QuantStateStore` | separate scope; honest limitation is sufficient for the dashboard |
| Resolve IEX receipt-vs-source-time | needs an authorized raw per-bar source-`t` log / `gap_forensics.py` archive check |
| `warmup_df` wiring for backtest CLI/`_run_multi` | carried from Task 81-R2; makes `test_backtest_*` ~36 min; out of scope here |
| Original session-id on wire records | Original does not stamp one; the collector records `original_session_id: None` honestly rather than inventing one |
| Live collector `run` loop operation | provided (`talonx_compare.runner`) but not started by this task; needs a running Redis + operator authorization |
