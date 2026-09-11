# Task 76S — Stage 0: Execution Path Inventory

## 1. Baseline verification
Branch `research/talonx-strategy-validation`, HEAD `b0c11b7` (matches expected), clean tree, origin
synced. No concurrent session (stale `.run/talonx.pids.json` PIDs confirmed not running via `ps -W`).

## 2. All runtime paths capable of broker mutation (individual order submission)
Grepped every caller of `AlpacaPaperClient.submit_order` and `PaperLifecycle.order_intent`
repo-wide (including `talonx_core`, `talonx_brain`, `talonx_dispatch`, `talonx_paper`, `scripts`, `cli`):

**`AlpacaPaperClient.submit_order` has exactly ONE caller: `PaperLifecycle.order_intent`
(`talonx_piv/lifecycle.py`).** No other code path posts an order directly to the broker adapter.

**`PaperLifecycle.order_intent` has exactly FOUR callers, all within `talonx_piv`:**
1. `decision_engine.py::DecisionEngine._handle_entry` — natural strategy BUY (only on a BULLISH
   published `QuantSignal`, one position per symbol already locally guarded).
2. `decision_engine.py::DecisionEngine._check_exit` — natural strategy SELL (stop/target price cross,
   or a forced `END_OF_SESSION` reason from `flatten_all`, called by `session_runner.py` at the
   scheduled EOD cutoff *within the live loop*, distinct from the separate bulk EOD reconciliation
   below).
3. `lifecycle_probe.py::run_piv_lifecycle_probe` — operator-confirmed PIV lifecycle probe BUY
   (already locally checks for an existing open position in the probe symbol before calling, but this
   is caller-side discipline, not boundary enforcement).
4. `lifecycle_probe.py::close_piv_lifecycle_probe` — probe SELL (controlled exit).

**No CLI subcommand submits a raw order directly** (`cli.py`'s `parser()` exposes only
`preflight`/`cleanup`/`start`/`kill-switch`/`eod` — none accepts a manual buy/sell). **No
Core/Brain-originated code path exists today**: `grep`-ing every top-level package for an import of
`talonx_piv` found only a comment in `talonx_dispatch/telegram_listener.py` (no actual import, and
that file never touches order submission). `talonx_brain` does not import `talonx_piv` at all.

## 3. Bulk/flatten broker mutations (no per-order side/quantity — exempt from BUY/SELL intent validation by nature)
- `eod_lifecycle.py::run_eod_lifecycle` → `lifecycle.broker.cancel_all_orders()` /
  `close_all_positions()` (idempotent, keyed by `(live_session_id, trading_date_et)`).
- `lifecycle.py::PaperLifecycle.activate_kill_switch` → `broker.cancel_all_orders()` (operator kill
  switch).
- `lifecycle.py::PaperLifecycle.eod_flatten` → both (an older, non-`eod_lifecycle`-mediated flatten
  path — retained, not removed, per "avoid redesigning the EOD implementation").
- `lifecycle.py::paper_cleanup` (module-level function, used by `cli.py cleanup`) → both, requiring
  `explicitly_confirmed=True`.

These four call sites never construct a BUY/SELL order — they cancel/close everything unconditionally
via the broker's own bulk endpoints. They remain untouched by this task's new intent-level validation
(which lives inside `order_intent`, a different code path) and are explicitly exercised in Stage 4's
regression evidence to prove they still work unchanged.

## 4. Final broker adapter and bypasses
Final adapter: `talonx_piv/broker.py::AlpacaPaperClient`. Its `submit_order` is a **generic,
unvalidated pass-through** — it accepts any `dict` payload and POSTs it verbatim once
`_require_verified()` (positive PAPER identity check) passes. **This is, by itself, "a helper that
callers can bypass"** in the sense the task warns about: nothing in `submit_order` itself distinguishes
a BUY-to-open from a SELL-to-close, checks position state, or rejects an oversized/duplicate/short
request. Because `submit_order` has exactly one caller (`order_intent`), the correct, minimal
enforcement point is **inside `PaperLifecycle.order_intent`** — the true single chokepoint for every
per-order broker mutation in this codebase today. No bypass of `order_intent` exists; verified by the
grep above finding zero other `submit_order` callers.

## 5. Sources of state
- **Position state**: `LifecycleState.positions` (keyed by `position_id`) +
  `LifecycleState.open_position_by_symbol` (symbol -> currently-OPEN `position_id`), both persisted in
  `lifecycle_state.json`, mutated only by `PaperLifecycle.apply_broker_update`.
- **Open-order state**: `LifecycleState.orders` (keyed by broker order id) + `LifecycleState.intents`
  (keyed by a stable hash of `(signal_id, symbol, side, quantity)`), same file.
- **PAPER account/endpoint verification**: `AlpacaPaperClient.verify_paper_identity` (checks
  `config.paper_trading=True`, `config.real_capital=False`, `config.broker_endpoint == PAPER_ENDPOINT`,
  positive account fetch) — `identity` is `None` until this succeeds; `_require_verified()` gates every
  other broker method on it.
- **Strategy approval status**: **no production mechanism exists today.** `talonx_quant`/`talonx_piv`
  have no "approved strategy" registry or flag anywhere in the repository (confirmed by grep for
  "approval"/"validated" across both packages — the only "approved" concept in `talonx_piv` is
  `approved_sha`, a deploy/commit-pinning mechanism, unrelated to alpha validation status). Per this
  task's own instruction, the new decision contract must therefore **default every real strategy to
  `UNVALIDATED` and fail closed** — no approval is invented for the current scanner.
- **Per-ticker execution settings**: none exist today (`PivConfig.universe` is a flat tuple of symbols
  with no per-symbol attributes). This is a new concept introduced in Stage 2.

## 6. Smallest implementation plan
See `implementation_plan.md` for the full write-up. Summary: (a) a new, standalone
`talonx_piv/decision_contract.py` module (Stage 1) — pure, typed, no wiring into the live
`decision_engine.py` signal loop in this task (that integration is explicitly deferred, see
`remaining_integration_work.md`); (b) a new `talonx_piv/execution_settings.py` module (Stage 2) for
per-ticker `paper_entry_enabled`, fail-closed by default; (c) harden `PaperLifecycle.order_intent`
in place (Stage 3) — it is already the single real chokepoint, so no new call sites need to be
introduced for enforcement to be complete; (d) wire the new `PaperEntrySettings` loader into
`cli.py::runtime()` (the one production construction site) so the gate has real effect operationally;
(e) update existing test factories (one local `lifecycle(...)` helper per file, not every individual
test) to explicitly enable their test symbols under the new fail-closed default, since this is an
intentional, disclosed behavior change, not incidental breakage.

**No protected file dependency was found.** All of the above is achievable entirely within
`talonx_piv/*` and `tests/*`; `talonx_quant/{strategy,indicators,consumer,config}.py` are read-only
references (call-path tracing) and are not modified.
