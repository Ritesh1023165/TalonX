# Task 66B-PREP Part 7 — Cross-path (PIV vs full application) comparator contract

Implementation: [`talonx_ops/comparator.py`](../../talonx_ops/comparator.py).
Tests: [`tests/test_task66b_prep_comparator.py`](../../tests/test_task66b_prep_comparator.py) (12 focused tests).
Live smoke evidence: `comparator_smoke_report.json` (this directory), run against the real
`piv_events.jsonl` produced by today's actual Task 65B/66A PIV sessions.

## What this is

A **read-only** reconciliation report over evidence that already exists on disk from two
independent runtimes:

- **PIV** (`talonx_piv`) — reads `piv_events.jsonl` directly.
- **Full application** (`run_talonx.py`) — reads the same SQLite stores
  `generate_eod_report.py` already reads, via its own `build_report()` function (reused, not
  re-implemented, so there is exactly one place that knows how to query those stores).

It never changes a runtime decision, never writes to either system's state, and never fabricates
a value that isn't backed by real evidence on the side it's attributed to.

## Stages

`symbol`, `timestamp`/`correlation_id`, `market_event_seen`, `quant_candidate`, `quant_rejection`,
`quant_signal`, `brain_received`, `brain_report`, `core_received`, `core_result`,
`dispatch_received`, `telegram_event`, `paper_decision`, `paper_execution`, `final_position_state`
(minus the identity fields `symbol`/`timestamp`/`correlation_id`, which key every row rather than
being a stage of their own — 13 stages total, see `talonx_ops.comparator.STAGES`).

## Why most stages can never come from PIV

PIV drives `talonx_quant.consumer.QuantScanner` directly (`talonx_piv.decision_engine`) and has no
Brain/Core/Dispatch participation at all — this is the architecture, not a gap (see
`full_app_runtime_graph.md`'s comparison table and `next_e2e_piv_handoff.md`). Only 4 of the 13
stages can ever be populated from `piv_events.jsonl`: `quant_signal` (a `SIGNAL` event with
`source="STRATEGY"` — explicitly excluding `PIV_LIFECYCLE_PROBE` orders, which are not alpha
evidence and not a real strategy signal), `paper_decision` (`ORDER_INTENT`), `paper_execution`
(`PAPER_ORDER_SUBMITTED`/`FILLED`), and `final_position_state` (`POSITION_OPENED`). Every other
stage is reported `NOT_APPLICABLE_TO_PIV` on the PIV side — not silently dropped, not treated as a
defect.

## Classification taxonomy

| Classification | Meaning |
|---|---|
| `MATCH` | Real evidence exists on **both** sides for this symbol/stage. |
| `DATA_DIFFERENCE` | Reserved — see "Known limitation" below. |
| `PIV_GATING_DIFFERENCE` | Reserved — see "Known limitation" below. |
| `DOWNSTREAM_PIPELINE_DIFFERENCE` | Reserved — see "Known limitation" below. |
| `EXECUTION_DIFFERENCE` | Reserved — see "Known limitation" below. |
| `MISSING_EVENT` | Evidence exists on exactly one side (or neither), for a stage PIV *could* have populated. |
| `NOT_APPLICABLE_TO_PIV` | The stage is structurally outside PIV's scope (see above) — not a gap. |
| `UNEXPLAINED` | Reserved — not currently emitted; kept in the enum for a future pass that needs it. |

## Known limitation (by design, not an oversight)

This is a **presence-based** reconciliation, not a semantic value-diff. As of this task, the normal
application has never run with this evidence layer active, so there is no full-app data to
calibrate a real field-level comparison (price/quantity/timestamp deltas) against —
`DATA_DIFFERENCE`/`EXECUTION_DIFFERENCE`/`PIV_GATING_DIFFERENCE`/`DOWNSTREAM_PIPELINE_DIFFERENCE`
are defined in the taxonomy but never emitted by `compare()` today. `comparator_smoke_report.json`
demonstrates this honestly: run against real PIV evidence with the full-app side genuinely empty,
it reports `MISSING_EVENT`/`NOT_APPLICABLE_TO_PIV` only — zero `MATCH`, because there is nothing on
the other side to match against yet. That is the **correct** answer for today, not a bug. A future
task, once real full-app evidence exists from an actual `run_talonx.py` session, can extend
`compare()` to diff specific fields for rows that already show `MATCH` at the presence level.

## Contract for callers

- `load_piv_evidence(path)` — never raises; a missing file or malformed line simply contributes
  nothing (skipped), not an error.
- `load_full_app_evidence_for_date(date_str)` — never raises; any store that can't be opened
  (not yet run, persistence disabled) is simply absent from the result. A watchlist ticker with
  zero real pipeline activity is **not** included just for being on the watchlist (fixed during
  this task — see the comparator's own module comments for the failure mode this avoids).
- `compare(piv_evidence, full_app_evidence)` — pure function, no I/O, always returns exactly
  `len(symbols) * len(STAGES)` rows.
- `build_comparator_report(piv_events_path, date_str)` — the CLI entrypoint
  (`python -m talonx_ops.cli comparator-smoke`) wraps this and writes the JSON report.
