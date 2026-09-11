# Task 118A Priority 1 — Experimental paper exit lifecycle (2026-09-11)

**Verdict: confirmed and fixed.** The existing `check_exits`/`close_long`
logic (`talonx_signals/experimental_paper.py`) was real, already correct,
and already unit-tested — it was simply never invoked anywhere in the live
process. Fixed by wiring it into the existing live tick loop; no new
trading rule invented.

## 1. Trace — confirmed from source and recorded state before any change

- **Producer**: `talonx_signals/run.py::ExperimentalLane.consume()` already
  subscribes to `talonx:market:stream` (the same real-time tick channel
  `talonx_paper.consumer` — Original's own, proven, live stop/target
  path — reads) and already updates `self._last_price[sym]` and
  `self.recorder.on_market_bar(...)` on every tick (lines ~285–301,
  pre-existing).
- **Market-data path**: identical live feed Original already trusts for
  its own `_handle_market_tick` → `check_stop_take` → `_close_position`
  chain (`talonx_paper/consumer.py:260-287`) — reused as the reference
  pattern, not reinvented.
- **Paper store**: `ExperimentalPaperEngine` (`talonx_signals/experimental_paper.py`)
  wraps `talonx_paper.store.PaperTradingStore` (the SAME class Original
  uses, pointed at an isolated `experimental_paper.db`) — `execute_buy`/
  `execute_sell` are already atomic (`store.py:386-486`, single
  `with self._lock:` / one `commit()`), already battle-tested.
- **Exit rules**: `check_exits(symbol, price)` → `talonx_paper.engine.check_stop_take`
  — ATR-anchored dollar stop/target levels captured at entry
  (`store.execute_buy`'s `stop_price`/`target_price`), the SAME rule
  Original's own live positions use. Confirmed unchanged.
- **The actual defect, confirmed**: a repository-wide search for call
  sites of `check_exits`/`flatten_all` outside test files found **zero**
  callers in `talonx_signals/` before this fix (the only other real
  caller, `talonx_piv/session_runner.py:705`, is a different engine
  entirely — unrelated PIV, not this lane).
- **A second, causally-related defect found while tracing (not
  previously reported)**: `ExperimentalDispatcher.dispatch_trade()` →
  `ExperimentalAlertStore.record_trade()` is INSERT-only, keyed by
  `trade_id`. `close_long()`'s returned SELL dict carries a **different**
  `trade_id` from the original BUY row (by design —
  `make_trade_id(..., side="SELL", ...)`). Had the exit path simply
  reused the BUY dispatch pattern verbatim, it would have inserted a
  **second, separate row** rather than updating the original — leaving
  the display/dispatch log (`exp_alerts.db.experimental_trades`, the SAME
  table the Task 118 Part 4 reconciliation queried) permanently showing
  the position as still open even after the authoritative ledger
  correctly closed it. Confirmed never previously exercised (since
  `check_exits`/`close_long` were never called at all) — an unwired,
  latent second defect in the same unfinished feature, not a new
  regression from this fix.

## 2. What was wired — and what was deliberately NOT wired

- **Wired**: `check_exits` (stop-loss / take-profit), called on every
  `talonx:market:stream` tick for the ticking symbol, via
  `ExperimentalLane._maybe_check_exit()` (new) →
  `ExperimentalLane._record_experimental_exit()` (new) —
  `talonx_signals/run.py`.
- **NOT wired**: `flatten_all` (EOD mandatory flatten). Per this task's
  explicit instruction not to introduce a new mandatory rule just because
  the function exists, the applicable policy was determined from
  observed evidence, not assumed: the 5 positions under investigation
  (VRT, BLSH opened 2026-09-09; AMD, STX, SPCX opened 2026-09-10) had
  already persisted across 2+ calendar days with **no** flatten ever
  applied — before this fix, nothing called `flatten_all` for this lane
  at all (confirmed by the same call-site search above; its only real
  caller is the unrelated PIV engine). This is direct evidence Experimental
  is a **hold-until-stop/target** lane, not an intraday-flatten lane, and
  wiring a new EOD-flatten behavior now would be inventing a rule the
  system's own history contradicts. **Determined policy: stop/target only,
  no EOD flatten** — documented here as the explicit semantic decision, not
  silently assumed.

## 3. Independence from entry-signal machinery — verified by test, not assumed

`_maybe_check_exit` is called unconditionally for any symbol on any tick,
with no reference to `handle_message`, entry severity gates, or the
`_maybe_open_experimental` new-entry path. Proven directly:
`test_exit_fires_from_a_bare_market_tick_no_candidate_involved` (no
candidate message anywhere in the test) and
`test_entry_rejection_on_the_same_symbol_does_not_block_the_exit` (a
`LOW_CONFLUENCE` rejection for the SAME symbol is processed first, exit
still fires) — `tests/test_task118a_experimental_exit_lifecycle.py`.

## 4. Validation before executing a paper exit

- **Instrument identity**: implicit via `get_position(symbol)` dict
  lookup — a tick for an unrelated/flat symbol is a no-op.
- **Price validity**: `price is None or price <= 0` → explicit skip, no
  fill invented (`test_none_or_non_positive_price_is_skipped`,
  `test_missing_price_never_marks_the_display_row_exited`).
- **Price timestamp / staleness**: a tick's own timestamp is compared
  against the evaluation time; age `<0` (clock skew) or `>
  TALONX_EXPERIMENTAL_EXIT_MAX_TICK_AGE_S` (default 300s) is an explicit
  skip with a logged reason, never a fill
  (`test_stale_tick_is_skipped_not_filled`,
  `test_a_tick_within_the_freshness_window_still_fills`).
- **Session eligibility**: this lane relies on the same live tick stream
  Original's own `_handle_market_tick` trusts (no separate session gate
  exists there either) — ticks only flow while the live market-data
  producer is actually running/publishing; no new session concept was
  invented here. Stated explicitly as a parity decision, not silently
  assumed equivalent.

## 5. Atomicity / durability / idempotency

The authoritative position/cash transition is `PaperTradingStore.execute_sell`
— already atomic (one lock, one commit; DELETEs the position row,
INSERTs the trade_history row, UPDATEs `portfolio_state`, all-or-nothing).
Repeated ticks after a close find `get_position()` returns `None` and
no-op — proven by `test_repeated_ticks_after_close_never_double_exit`
(cash and trade-history row count identical before/after 2 extra ticks)
and `test_restart_reopens_the_same_ledger_position_survives` (a fresh
`ExperimentalLane` against the same on-disk db sees the still-open
position and can correctly close it).

## 6. External-send prohibition

The exit path never calls `self.dispatcher` at all (the display-log
reconciliation writes directly via `ExperimentalAlertStore.update_trade`,
not through the dispatcher/sender). Proven by
`test_exit_never_calls_the_sender` (a spy sender records zero calls) and
`test_exit_path_makes_no_dispatcher_call_at_all` (monkeypatched
`dispatch_trade` raises if called — never triggered).

## Existing positions — recovery policy applied

Per this task's explicit instruction: **no synthetic fill, no backdated
exit, no invented rule.** The frozen, already-existing gap/fill convention
(`talonx_paper.engine.check_stop_take` / `apply_spread`, proven by
Original's own identical live pattern) already answers this: when a tick's
price has already crossed the stop/target — by any amount, including a
large gap — the position closes **at that tick's own price** (spread-
adjusted), **at that tick's own observation time**. Nothing about this
convention is new; it is the same rule Original's `_handle_market_tick`
already applies to a live gap-through.

| symbol | last known reference price (2026-09-10, Task 118 Part 4) | vs. recorded stop | recovery outcome |
|---|---:|---|---|
| VRT | $247.65 | **below** stop $273.65 | **pending** — will close at the next valid, non-stale market tick's actual price, at that tick's real observation time. Not force-closed using the stale 2026-09-10 reference price (per "a historical reference price below a stop is evidence to investigate, not proof of an executable fill"). |
| BLSH | $34.04 | **below** stop $34.72 | same as VRT — pending the next valid tick. |
| AMD | $505.29 | inside stop/target band | pending, unaffected — will evaluate normally on the next tick. |
| STX | $870.00 | inside stop/target band | pending, unaffected. |
| SPCX | $148.19 | inside stop/target band | pending, unaffected. |

**No position was force-closed by this task.** All five remain in their
authoritative `PaperTradingStore` state exactly as recorded; only the
exit-evaluation wiring changed. VRT and BLSH are expected to close on the
first fresh, valid tick they receive after the fix is deployed and live
ticks resume (pre-open now; the market:stream feed carries live prices
during the active producer's operating hours) — this will be captured as
part of post-restart acceptance evidence (see the main activation report),
not asserted here in advance.

## Tests

`tests/test_task118a_experimental_exit_lifecycle.py` — 16 tests, all
passing, covering exactly the 8 required areas (stop/target exits;
exit-without-new-entry; entry-rejection-does-not-block-exit;
missing/stale prices; restart+repeated-event idempotency; overdue-position
gap-fill recovery; ledger/cash reconciliation; external-send prohibition).
`tests/test_task99a_experimental_paper.py` (pre-existing, unmodified) —
the underlying `check_exits`/`close_long` dollar-math coverage this fix
reuses, still passing.

## Files changed

- `talonx_signals/run.py` — `_maybe_check_exit`, `_record_experimental_exit`,
  wired into `consume()`'s market-tick branch; `_EXIT_TICK_MAX_AGE_SECONDS`.
- `talonx_signals/alert_store.py` — `ExperimentalAlertStore.get_open_trade_id`
  (new, small, read-only lookup used by the reconciliation step above).

No change to `talonx_paper/*` (the shared, proven engine/store) and no
change to `talonx_v2/*` (V2 fingerprint unaffected — verified separately,
see the main activation report).
