# Stale-Exclusion Guard -- Full Code-Path Trace

## The guard itself (`talonx_piv/session_runner.py::process_tick`)

```python
decision_eligible = self._ready_symbols & self.decision_engine.warmup_ready_symbols
decision_eligible = {s for s in decision_eligible if self._freshness.state_of(s) not in (STALE, DATA_GAP)}
ready_bars = {s: b for s, b in new_bars.items() if s in decision_eligible}
if ready_bars:
    await self.decision_engine.on_bars(ready_bars)
```

## Trace: everything `self._freshness.state_of(s)` can influence

`FreshnessTracker.state_of` (`talonx_piv/freshness.py`) returns one of
exactly 5 strings: `FRESH`, `STALE`, `RECOVERED`, `DATA_GAP`, `UNKNOWN`.
The guard's set-comprehension filter (`not in (STALE, DATA_GAP)`) is a
pure boolean membership test against a Python set literal -- it cannot:

- Change a symbol's OHLCV values (it never touches `new_bars[s]`'s
  content, only whether the key `s` is retained).
- Change confluence score, risk/reward, ATR, RSI, MACD, or any other
  indicator (none of those are computed here -- `talonx_quant/strategy.py`
  and `indicators.py` are not imported anywhere in `freshness.py`,
  `gap_forensics.py`, or this guard's own module).
- Change which strategy runs, or any threshold used by one (no
  `QuantConfig` field is read or written by this guard).
- Reorder or re-rank anything (the guard runs once, before `on_bars` is
  even called; `on_bars`'s own internal candidate ranking, unmodified, is
  entirely downstream of this filter and never sees a hint that a symbol
  was ever filtered out).

## Trace: what happens on each branch

**`state_of(s) not in (STALE, DATA_GAP)` is True (included):** `s` passes
through to `ready_bars` unchanged, `b` (its `Bar` object) is passed to
`decision_engine.on_bars` byte-for-byte identical to what
`fetch_bars_latest` originally parsed from the Alpaca response. Nothing
about the guard's existence is visible past this point.

**`state_of(s) not in (STALE, DATA_GAP)` is False (excluded):** `s` is
absent from `ready_bars`. If `ready_bars` ends up empty, `on_bars` is not
even called this tick. This is EXACTLY the same effect as the two
pre-existing gates (`_ready_symbols`, `warmup_ready_symbols`) already
have when they exclude a symbol -- the guard added by Task 71S is
structurally identical to gates that already existed and were already
accepted as correct, fail-closed behaviour.

## Why a stale/incomplete symbol can genuinely never reach `on_bars`, by construction

1. `new_bars` only ever contains a symbol when `fetch_bars_latest` returned
   a bar with a STRICTLY NEWER timestamp than any previously seen this
   session (`if last is not None and bar.timestamp <= last: continue`,
   unmodified since before Task 70S).
2. The moment such a bar is recorded, `self._freshness.observe_fresh(symbol)`
   runs in the SAME tick, BEFORE the guard above -- so by construction, a
   symbol present in `new_bars` this tick has ALREADY had its freshness
   state cleared to `FRESH` (or `RECOVERED`) before the guard ever
   evaluates it. A symbol still `STALE`/`DATA_GAP` at guard-evaluation time
   is, therefore, a symbol that did NOT get a new bar this tick -- and such
   a symbol is never in `new_bars` in the first place regardless of the
   guard.
3. This makes the guard **provably redundant with the pre-existing
   `new_bars` population logic** in the current architecture -- confirmed
   by inspection, not merely asserted. It exists anyway as an explicit,
   testable, future-proof invariant (so a later refactor of the bar-fetch
   loop cannot silently reintroduce a path where a stale symbol's bar
   reaches `on_bars`) -- belt-and-suspenders, not a functional change to
   today's behaviour.

## The one new, NON-redundant case this task's fix touches

Before Task 71S-R1's `_check_stale` gate relaxation, a symbol that had
ALREADY been excluded from `_ready_symbols` (e.g. REGN, never
session-ready that day) was invisible to `_check_stale` for the rest of
the day -- so its freshness state, absent any further checks, could in
principle have remained stuck at whatever it last was (`FRESH`, if its
last bar before 10:00 ET happened to be recent). Relaxing the gate means
such a symbol NOW continues to be re-evaluated and correctly marked
`STALE`/`DATA_GAP` throughout the day. This is strictly MORE conservative,
never less: it can only ever ADD to the set of symbols the guard excludes,
never remove a symbol the guard would otherwise have excluded. See
`test_integration_no_candidate_from_repeatedly_monitored_not_ready_symbol`
(this task's own new test) for direct proof that a not-ready symbol
STILL never reaches `on_bars` under the new, wider monitoring.

## Conclusion

The stale-exclusion guard (both the original Task 71S version and this
task's extension of its monitoring scope) can only PREVENT evaluation on
data this task's own forensic evidence shows is unreliable/incomplete. It
cannot alter, weaken, or bypass alpha logic, thresholds, or scoring in any
way -- confirmed both by static code-path inspection (no talonx_quant
import anywhere in the guard's dependency chain) and by direct test
(`test_integration_no_candidate_from_repeatedly_monitored_not_ready_symbol`,
`test_integration_no_signal_from_stale_symbol` from Task 71S,
`test_integration_recovery_permits_evaluation_once_restored` from Task 71S).
