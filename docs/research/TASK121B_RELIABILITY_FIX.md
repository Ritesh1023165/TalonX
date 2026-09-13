# Task 121B Part 2 — confirmed root cause and reliability fix

## Confirmed root cause (reproduced, not assumed)

Task 121A's post-backtest summary step hung for over an hour on the full
month-long run. Task 121A's own guess (unbounded `published_log` growth)
was **wrong** — disproven directly this task by a controlled,
instrumented, smaller-scale (2-week, 212,549-bar) reproduction using the
exact Task 121A adapter code:

```
backtest elapsed: 3059.6s
published_log size: 14
exit_log size: 9
skip_counts: {'AVGO': 1}
result.trades size: 0
result.rejections size: 118112
```

`published_log`/`exit_log`/`skip_counts` are all tiny — nowhere near
large enough to explain a multi-hour hang. **The actual culprit,
confirmed by direct inspection of `research/scripts/task121a_experimental_replay.py`
line 466**:

```python
"rejections_by_reason": {r.reason: sum(x.count for x in result.rejections if x.reason == r.reason)
                         for r in result.rejections}
```

This is **O(n²)** in `len(result.rejections)` — for EACH of the 118,112
rejection records on just a 2-week window, it re-scans ALL 118,112
records to sum matching ones: **~1.4×10¹⁰ operations** for 2 weeks alone.
Task 121A's full-month run had proportionally more bars (and therefore
more rejection records — `LOW_VOLATILITY` alone rejects the vast
majority of every bar/symbol combination, per every prior task in this
research thread) — easily tens of billions of operations, fully
explaining the observed multi-hour, 100%-CPU, no-progress hang. This is
a **confirmed** diagnosis (reproduced under controlled conditions), not
an assumption drawn from having killed the original process.

## Fix

`research/scripts/task121b_reliable_replay.py::run_reliable_replay`
replaces the O(n²) pattern with a single **O(n)** pass:

```python
rejections_by_reason: dict[str, int] = {}
for r in result.rejections:
    rejections_by_reason[r.reason] = rejections_by_reason.get(r.reason, 0) + r.count
```

More broadly, the whole adapter was redesigned so that **no** telemetry
is ever accumulated into an unbounded in-memory Python structure and then
reduced/serialized in one large final operation:

- Every published-signal and exit EVENT is written **incrementally** to a
  durable SQLite store (`TelemetryStore`) the instant it happens (batched
  commits — every write, not held only in memory).
- Summary generation is a set of **bounded SQL `GROUP BY` aggregate
  queries** over that store (`TelemetryStore.funnel_summary`), not a
  Python-side reduction over a large list.
- The one place a genuinely large Python list still exists in-process
  (`BacktestEngine`'s own `result.rejections`, which this adapter does
  not control) is now summarized with a single O(n) pass, never O(n²).

## Verification (not assumed)

The exact same 2-week window was re-run through the fixed
`run_reliable_replay` (`run_id=verify-2wk-run`) — see
`docs/research/evidence/task121b/verify_fix.log` for the raw output.
Result: **2,966.7s total wall time** (backtest 2,946.6s + summary
**~20.1s**), vs. the original adapter's backtest alone taking 3,059.6s
and then hanging indefinitely (>1hr, killed) on the summary step alone.
The fix is confirmed effective on the SAME data/window that reproduced
the original bug, not merely argued to be correct from source-code
inspection alone.

As a bonus, the new durable telemetry gives a full, self-reconciling
funnel for this 2-week run: `signals_published_engine_count=155`
(the engine's own internal counter) vs.
`n_published_signal_events=14` (this adapter's own durable log) — the
155−14=141 gap is EXACTLY `rejections_by_reason["NO_ACTIVE_POSITION"]=141`
(a bearish candidate published while flat is rejected immediately inside
`_flush_throttle`, never reaching the shim at all) — a clean, fully
explained reconciliation, not a residual unknown. Of the 14 events that
DID reach the shim: 11 bullish (10 `OPENED`, 1
`SKIPPED_POSITION_ALREADY_OPEN`), 3 bearish (all
`BEARISH_PUBLISHED_WHILE_OPEN_NO_ACTION_TAKEN`) — real, per-signal
telemetry, not an inference from aggregate-count equality (Task 121's
original limitation).

## What full mid-run resumability would require (not implemented, per
   this task's own instruction not to claim it incorrectly)

`BacktestEngine`'s internal per-symbol state — `RollingBarBuffer`
contents (1m/15m/60m), `_cooldown_until`, `_loss_lockout_until`,
`_pending_entry`/`_pending_exit` — is held only in Python object
attributes with no serialization path. Correctly resuming a killed run
mid-stream would require either (a) modifying `talonx_backtest.engine`
itself to support state export/import (out of scope — that module is
reused verbatim, not modified, throughout this research thread), or (b)
reconstructing that state from a bar-level replay of everything before
the resume point anyway (which is just a deterministic rerun with extra
steps). **This adapter does not claim mid-run resume of scanner/gate
state.** What it DOES provide, verified by the Part 2 tests
(`tests/test_task121b_reliability.py`):

- An interrupted run's telemetry up to the interrupt point is fully
  durable, readable, and correctly attributed to its own `run_id` —
  never silently merged into, or confused with, a later successful run.
- A fresh run under a new `run_id` against the same telemetry store is
  purely additive — it cannot corrupt or duplicate a prior (possibly
  interrupted) run's own rows.
- Recovery from an interruption is: **discard the interrupted attempt's
  telemetry (it stays on disk, labeled, for audit) and start a fresh,
  fully deterministic rerun from the window's own start** — not a
  resume.
