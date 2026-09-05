# Task 79E — `ExperimentalAuthorization` Contract

Source of truth: [`talonx_piv/experimental_authorization.py`](../../talonx_piv/experimental_authorization.py).

## What this object answers

"Has an operator explicitly, narrowly, and verifiably authorised ONE
experiment to generate an alert/shadow record (and optionally a bounded
PAPER order) for an otherwise-ineligible `UNVALIDATED` strategy, today, for
these symbols only?" It never answers "is the strategy validated" —
`strategy_approval_status` is a completely separate field and is never
touched by anything in this module.

## Loading (`load_experimental_authorization(path)`)

Fail-closed on every ambiguous case — returns `None` (no permission) rather
than raising:

| Condition | Result |
|---|---|
| File does not exist | `None` |
| File is not valid JSON, or not a JSON object | `None` |
| `enabled` is missing, not a strict `bool`, or `false` | `None` |
| Any required string field empty/missing (`experiment_id`, `strategy_id`, `strategy_version`, `runtime_sha`, `config_hash`, `trading_date_et`, `session_scope`) | `None` |
| `operator_acknowledged_unvalidated` is not literally `true` | `None` |
| `allowed_symbols` missing, empty, or contains a non-string | `None` |
| `activated_at`/`expires_at` missing, not ISO-8601, timezone-naive, or `expires_at <= activated_at` | `None` |
| `paper` present but malformed, or its numeric limits are non-finite/non-positive/boolean | `None` |

Strict typing throughout: `isinstance(value, bool)` is checked explicitly
and BEFORE any numeric check (`bool` is an `int` subclass in Python — a
JSON `true`/`false` is never accepted where a count/limit is expected, and a
JSON string `"true"`/`"false"` is never coerced).

## Re-validation (never a cached check)

`permits_entry(...)` and `permits_paper_execution(...)` both take an
explicit `now: datetime` (timezone-aware, checked — a naive `now` fails
closed) and are called **fresh on every admission attempt**, at two
independent layers:

1. `decision_engine.py::_experimental_permissions` — before a decision is
   even made, to compute `experimental_buy_permitted`/
   `experimental_paper_permitted` for `decide()`.
2. `lifecycle.py::_enforce_experimental_paper_guards` — again, independently,
   at the actual broker-order boundary inside `order_intent`, never trusting
   the decision layer's own prior check.

Both return `(bool, reason_str)` — never a bare boolean — so every rejection
carries an honest, specific reason code
(`SYMBOL_NOT_IN_ALLOWED_SET`, `WRONG_TRADING_DATE`, `WRONG_STRATEGY_ID`,
`WRONG_STRATEGY_VERSION`, `WRONG_RUNTIME_SHA`, `WRONG_CONFIG_HASH`,
`PERMISSION_NOT_YET_ACTIVE`, `PERMISSION_EXPIRED`,
`EXPERIMENTAL_PAPER_EXECUTION_NOT_ENABLED`, `WRONG_PAPER_ACCOUNT`).

## The PAPER-specific budget (separate from entry permission)

Bounded by `ExperimentalPaperPermission`: `account_id_binding`,
`max_quantity_per_entry`, `max_reference_notional_budget`,
`max_entry_count`, `max_concurrent_exposure`. Enforced only in
`lifecycle.py` (never in the pure `decide()` function, which has no state):

- **Reference-price budget, not a fill-value cap.** The notional check uses
  `reference_price * quantity` — an ESTIMATE at order-submission time.
  Market orders can fill at a different price; nothing in this system ever
  claims the budget is a hard cap on realised exposure. No reference price
  at all → `EXPERIMENTAL_REFERENCE_PRICE_REQUIRED_FOR_BUDGET_CHECK` (fails
  closed; unknown is never treated as free).
- **Durable, restart-surviving.** `LifecycleState.experimental_budgets`,
  keyed by `experiment_id`, is loaded from the same `lifecycle_state.json`
  every other lifecycle state lives in — re-minting the
  `ExperimentalAuthorization` object, or restarting the process, does not
  reset it (`test_budget_survives_restart`,
  `test_budget_not_reset_by_reloading_a_fresh_authorization_object`).
- **Never refunded on a failed submission.** If `submit_order()` itself
  raises before a broker id is ever received, the budget reservation already
  made for that attempt stays reserved — conservative, "no blind assumption
  of zero exposure" (`test_submission_failure_does_not_refund_experimental_budget`).

## Explicit non-goals

- Does not itself validate a strategy, does not set
  `strategy_approval_status = APPROVED`, and is never consulted by any
  non-experimental decision path.
- Grants no permission to any symbol not explicitly listed, on any date
  other than the one explicitly listed, under any runtime/config identity
  other than the one explicitly listed.
- Grants no PAPER execution permission on its own — `paper` must be present
  AND `enabled: true` AND account-bound, or every PAPER attempt is rejected
  with the entry/alert/shadow path still fully functional.
