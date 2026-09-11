# Task 118F — resilient warmup implementation (2026-09-11)

## Evidenced problem

Task 118A/B/C/D/E established: a transient yfinance bulk-preseed failure
this morning left many symbols with 0 usable historical 1-minute bars;
natural live-tick accumulation was the ONLY recovery path and took
multiple hours for the slowest symbols (25/43 ready at ~15:22 UTC, 30/43
at ~15:42 UTC — nearly two hours into the regular session).

## Root cause, traced to the exact mechanism

`talonx_quant/consumer.py::QuantScanner._preseed_1m_if_needed` guards
itself with `self._preseeded_1m` — a set marking a symbol "already
attempted," added **unconditionally**, regardless of whether the fetch
succeeded or returned nothing:
```python
if symbol in self._preseeded_1m:
    return
self._preseeded_1m.add(symbol)
if self.buffer.bar_count(symbol) >= self.config.min_bars_required:
    return
await self._run_1m_preseed(symbol)
```
A symbol whose first (bulk, startup) attempt failed therefore **can
never get a second attempt for the rest of the process's life** via the
existing public `preseed_symbols()` entrypoint — this is the exact reason
natural live-tick accumulation was the only path available.

## Fix — reuses the existing fetch path, adds only a bounded retry orchestrator

`talonx_quant/preseed_ordering.py::run_bounded_recovery_sweep` (new
function, same module `run_initial_preseed` already lives in):
- Identifies exactly the not-ready symbols from the `InitialPreseedReport`
  the existing call already produces.
- For each, re-verifies from the **live buffer** (never the stale report)
  that it is still below threshold before doing anything.
- Clears **only** that symbol's `_preseeded_1m` marker, then calls the
  **same, unmodified** `preseed_symbols()` public entrypoint again — no
  new fetch code, no new buffer-write code.
- Bounded: `max_attempts=2` rounds, `per_symbol_timeout_s=15.0`,
  `overall_budget_s=120.0`, exponential backoff between rounds, one
  symbol fetched at a time (no new concurrency).
- Wired into `run_talonx.py` in the **same pre-market-data safety window**
  `run_initial_preseed` already requires — strictly before any live tick
  task or `quant_scanner.run()` task exists. This is the load-bearing
  safety property: it structurally excludes any race with a live tick
  write to the same buffer timestamp (the existing `add_bar` upsert-by-
  timestamp behavior needs no new coordination), and makes the sweep
  naturally restart-safe (one sweep per process start, no persisted
  worker state to duplicate).

## What was deliberately NOT built

- No new fetch/provider integration — reuses `talonx_quant.preseed.fetch_1m_history`
  via the existing `preseed_symbols()` call, unchanged.
- No mid-session "trigger recovery now" RPC/admin endpoint — considered
  and rejected: it would require the sweep to run concurrently with live
  tick processing, reintroducing exactly the live-buffer race this design
  avoids by construction. The sweep runs only at startup, taking effect
  on the next (and every future) restart.
- No threshold, indicator, or trading-gate change.

## Real-provider evidence (bounded, isolated probe — not against the live process)

Ran `talonx_quant.preseed.fetch_1m_history` directly (isolated call, not
touching the live process's buffers) for 3 symbols still not-ready in the
live session at the time of this check:

| symbol | bars returned | elapsed |
|---|---:|---:|
| BLK | 129 | 1.61s |
| JNJ | 147 | 0.11s |
| ADC | 128 | 0.06s |

All three succeed and clear the 120-bar threshold — confirming the
provider-side issue was genuinely transient (as already established in
Task 118A/B) and that this recovery mechanism, had it existed this
morning, would have recovered these exact symbols in seconds rather than
requiring hours of live accumulation.

## Tests

`tests/test_task118f_resilient_warmup.py` — 8 tests, all passing, using a
`RealisticFakeScanner` that models the REAL `_preseeded_1m` idempotency-
guard semantics (not a bare mock) so the tests genuinely prove the sweep
defeats that guard:
1. Bulk failure → successful bounded recovery.
2. Partial recovery — one recovers, one remains explicitly incomplete.
3. No duplicate bars for a timestamp already live-written.
4. Structural exclusion of any live-tick race (no `create_task`/`gather`
   in the sweep — asserted from source).
5. No signal/alert/Telegram output surface exists or is invoked.
6. A symbol already recovered by live accumulation is never re-fetched.
7. Budget exhaustion stops cleanly, no infinite loop.
8. Provider call volume stays within the bounded retry budget.

Existing `tests/test_task66b_prep_preseed_ordering.py` (20 total with the
new file) and a broader `-k "preseed or warmup"` sweep (106 tests) all
still pass — no regression.
