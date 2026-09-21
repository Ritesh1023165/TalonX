# Task 83 — Operator Handoff (for the separately-authorized shadow pilot)

Status after Task 83: **DASHBOARD_AND_OFFLINE_DUAL_RUN_QUALIFIED** (see
`verification_report.md`). Strategy **UNVALIDATED**, profitability
**UNDETERMINED**, experimental authorization **disabled**, PAPER pilot
**unauthorized**. No live session, broker call, or Telegram request was made.

## What is ready

- `talonx_compare/` passive comparison collector (read-only observer; owns its own
  namespace, cursors, dedup index, lock, and date-partitioned evidence store).
- Browser dashboard (`localhost:8787`) read-only views: `/views/original`,
  `/views/piv`, `/views/compare` + a Live/Original/PIV/Compare tab nav in `index.html`.
- Streamlit "🔬 PIV & Comparison" read-only section.
- Health-state contract (nine states) + QuantStateStore limitation surfaced in both dashboards.
- 20-scenario offline dual-run rehearsal, all PASS (`offline_rehearsal_matrix.csv`).

## To run the offline rehearsal again

```
.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_task83_offline_dual_run.py -q
```
No network, no real Redis; process-ownership scenarios (4–6, 19) spawn genuine
`python` subprocesses whose command lines the real `talonx_core.process_guard`
Windows enumeration matches.

## When a shadow pilot IS separately authorized

1. **Confirm isolation before starting PIV** (Task 82, unchanged):
   `python -m talonx_piv.cli preflight --approved-sha <sha>` and
   `validate_piv_isolation(PivConfig())` must pass — distinct Redis DB,
   `talonx:piv:*` channels, PIV Quant DB path, PIV state dir, Telegram disabled.
2. **Start PIV with the required marker**:
   `python -m talonx_piv.cli start --approved-sha <sha> --isolated-parallel ...`
   (the process guard rejects an unmarked PIV peer beside Original).
3. **Start the comparison collector** (read-only):
   `python -m talonx_compare run` — it subscribes to Original (DB 0) and PIV
   (DB 1) channels and folds them plus the PIV state files into
   `results/task83_dashboard_comparison_qualification/daily_evidence/<date>/`.
   It holds only `collector_runtime/collector.lock`; it never touches an
   Original/PIV lock, never publishes, never writes to Redis.
4. **Watch the dashboards**: browser `Original` / `PIV` / `Compare` tabs, or the
   Streamlit "PIV & Comparison" section. Every count carries a health badge;
   `NOT_RUN` / `MISSING` / `STALE` / `WRONG_SESSION` are shown explicitly and are
   never a plausible zero.

## Invariants the operator must keep true

- PIV `execution_mode` stays `SHADOW` until an operator explicitly enables a PAPER
  entry in `paper_entry_settings.json` (fail-closed / all-disabled by default).
- PIV outbound Telegram attempts stay **0**; PIV inbound poller starts **0** times.
- The collector and both dashboards remain read-only.
- A `session_recovery_required.json` / entry-admission block takes priority over any
  startup / isolation marker (scenario 18).
- On abrupt termination, only the collector's own lock is affected; it self-heals on
  the next run and the evidence store is preserved (scenario 19).

## Where the evidence lives

`results/task83_dashboard_comparison_qualification/`
- `daily_evidence/<date>/manifest.json` — immutable per-day manifest (session ids,
  runtime SHAs, config hashes, feeds, universes, modes, start/end)
- `.../original_events.jsonl`, `.../piv_records.jsonl` — append-only, dedup by `_id`
- `.../comparison.json`, `.../divergences.json`, `.../telegram.json`, `.../diagnostics.json`
- `.../file_hashes.json` — sha256 of every evidence file; `python -m talonx_compare verify <date>`
