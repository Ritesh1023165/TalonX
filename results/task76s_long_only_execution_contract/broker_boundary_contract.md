# Task 76S — Stage 3: Broker Boundary Contract

Enforcement point: `talonx_piv/lifecycle.py::PaperLifecycle.order_intent` — the single real chokepoint
for every per-order PAPER broker mutation in this codebase (see `execution_path_inventory.md`).

## Explicit action intent (not raw BUY/SELL interpretation)
`side` ("buy"/"sell") is resolved to a typed `ActionIntent` (`BUY_TO_OPEN`/`SELL_TO_CLOSE`) at the top
of `order_intent`; anything else is rejected as `UNSUPPORTED_ACTION_INTENT` before any state is
touched. There is no third value this can resolve to — opening a short is structurally impossible
through this path (a raw `side="short"`/`"sell_short"` string is simply unsupported, not routed
anywhere).

## Request well-formedness (checked first, before any state mutation)
- Quantity must be a real `int`/`float` (not `bool`), finite (`math.isfinite`), and `> 0` — else
  `INVALID_QUANTITY`.
- `source` must be `None` or one of `{"STRATEGY", "PIV_LIFECYCLE_PROBE"}` — else `UNAUTHORIZED_SOURCE`.
  This is the control that rejects a hypothetical `"BRAIN"`/`"GEMINI"`-sourced request (no such
  integration exists today — Stage 0 confirmed zero cross-package callers — but the allowlist makes
  this defense-in-depth rather than "true because nothing tries").

## New entries (BUY_TO_OPEN)
Checked in order, each independently sufficient to reject:
1. `UNEXPECTED_SHORT_BLOCKS_NEW_ENTRIES` — `reconcile()` previously detected a broker-reported short
   position with no matching internal long. **No automatic remediation is added for this** (per
   instruction); it only blocks new entries until an operator investigates.
2. `ALREADY_HOLDING_NO_PYRAMIDING` — an internal `OPEN` position already exists for this symbol.
3. `PENDING_ENTRY_EXISTS` — a non-terminal (not filled/rejected/canceled/expired) BUY order is already
   outstanding for this symbol.
4. `PAPER_ENTRY_DISABLED_FOR_TICKER` — `PaperEntrySettings.enabled_for(symbol)` is `False` (the Stage 2
   gate; fail-closed by default).
Existing sizing/cash/risk limits are unchanged (this task adds no new sizing logic — `PIV_QUANTITY`
remains the caller's fixed, deterministic quantity); no implicit pyramiding path exists (check 2 above
is unconditional — there is no policy flag that relaxes it, per instruction: "unless explicitly part of
an existing approved policy," and no such policy exists).

## Closing sells (SELL_TO_CLOSE)
1. `SELL_WHILE_FLAT` — no internal `OPEN` position exists for this symbol (`_open_position_for`).
2. `OVERSIZED_OR_DUPLICATE_SELL` — requested quantity exceeds `held_quantity − pending_sell_exposure`,
   where `pending_sell_exposure` sums `(originally_requested − filled_qty)` across every non-terminal
   sell order already outstanding for this symbol/position (`_pending_quantity`). This is what prevents
   a **duplicate** sell request from being treated as a second, independent close (it would compute
   `available == 0` and reject) and what prevents an **oversell** reversing a long into a short.
Both checks re-read `self.state` **fresh at call time** — never a caller's own possibly-stale local
bookkeeping (e.g. `lifecycle_probe.py`'s own pre-check is caller-side discipline only; this boundary
check is what actually cannot be bypassed). If concurrent state cannot be reconciled safely (the
position/order bookkeeping is ambiguous), the request is rejected, never guessed at.

## Idempotency and ownership
The pre-existing `stable_id("intent", signal_id, symbol, side, quantity)` duplicate-intent-id check is
unchanged and still runs (now positioned after the new well-formedness checks, before the new
position-state checks) — it catches an EXACT repeat of the same call; the new
`OVERSIZED_OR_DUPLICATE_SELL`/`PENDING_ENTRY_EXISTS` checks close the remaining gap (a DIFFERENT
`signal_id` targeting the same open position/pending order).

## Rejected categories, mapped to this task's required list
| Required rejection | Mechanism |
|---|---|
| Opening short requests | No `side` value routes to a short — `UNSUPPORTED_ACTION_INTENT` for anything but "buy"/"sell". |
| SELL while flat | `SELL_WHILE_FLAT`. |
| Oversized SELL | `OVERSIZED_OR_DUPLICATE_SELL`. |
| Invalid/non-positive/non-finite quantities | `INVALID_QUANTITY`. |
| Unsupported action intents | `UNSUPPORTED_ACTION_INTENT`. |
| Real-capital endpoints or ambiguous account mode | Pre-existing `AlpacaPaperClient.verify_paper_identity`/`_require_verified` (unchanged, still the final gate before any HTTP call). |
| Requests attempting to bypass approval/execution eligibility | `PAPER_ENTRY_DISABLED_FOR_TICKER`, `ALREADY_HOLDING_NO_PYRAMIDING`, `PENDING_ENTRY_EXISTS`. |
| Brain/Gemini requests | `UNAUTHORIZED_SOURCE`. |
| Unexpected existing shorts | `UNEXPECTED_SHORT_BLOCKS_NEW_ENTRIES` (reconciliation-derived, no remediation). |

## Applies uniformly to every path
Natural strategy (`decision_engine.py`), PIV lifecycle probe (`lifecycle_probe.py`), and any future
manual/CLI caller all go through this same `order_intent` — there is no "probe" bypass flag; the probe
label is purely descriptive (`source="PIV_LIFECYCLE_PROBE"`) and is itself part of the allowlist, not
an exemption from any of the checks above.
