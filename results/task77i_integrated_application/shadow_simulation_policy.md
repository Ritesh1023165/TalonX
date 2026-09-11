# Task 77I Stage 3 — Shadow Simulation Policy

Frozen BEFORE this policy's semantics were exercised against any live data (this is a
policy/contract document, not a report of observed results — no shadow trade has ever run
against real market data; every proof in this task uses synthetic, clock-controlled bars).

## Actionability gate
A shadow position is only ever opened for `decision.recommendation == Recommendation.BUY` —
i.e. only when strategy approval + bullish + flat + ready data all already held (the identical
gate real PAPER execution uses). This is deliberate, not an oversight: gating shadow P&L on raw
signal direction alone (ignoring strategy approval) would let an UNVALIDATED strategy accumulate
an informal, unaudited "shadow track record" — exactly the kind of accidentally-manufactured
evidence Tasks 74S/75S were careful never to create by accident. Consequence: today, with no
approval registry, shadow tracking is (like PAPER execution) inert for real natural-strategy
traffic, and is exercised in this task only via `TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE`
fixtures. `WATCH`, `HOLD`, and `NO_TRADE` decisions never become hypothetical entries.

## Entry eligibility and fill timing
A decision is evaluated at a specific, already-CLOSED trigger bar. The shadow entry does
**not** assume a fill at that bar's close (the price the strategy's own indicators were
computed from — a zero-latency, unrealistic fill). The position sits `PENDING_FILL` until
`on_bar` observes a **strictly later** bar for the same symbol (`bar.timestamp >
recommendation_time`), then fills at **that bar's `open`**. This exactly replicates
`talonx_backtest.engine.py`'s own `_PendingEntry` convention (see that module's docstring: "a
published signal's entry is executed at the OPEN of the NEXT bar... never a same-bar close") —
the same rule the historical backtest already applies, reused rather than reinvented.

## Stop/target handling
Reuses `talonx_backtest.execution.check_bar_for_exit` directly (no reimplementation): a bar's
`high`/`low` are checked against the position's fixed `stop_price`/`target_price` every tick
after the fill bar (inclusive of the fill bar itself, so a stop/target hit on the very bar that
filled is still caught).

## Same-bar stop/target ambiguity
Both `check_bar_for_exit`'s default (`stop_first`) applies unchanged — the conservative
assumption when a single bar's range touches both levels. Not configurable per-shadow-position
in this task; matches the historical backtest's own default exactly.

## Time/horizon exit
No independent time-based exit is implemented in this task (the natural strategy's own
`horizon` field is carried through for record-keeping, but no horizon-driven forced-exit clock
exists yet — matching the fact that the real system has no such clock either, only stop/target
and EOD). A shadow position closes only via stop, target, or `force_close` (EOD or any other
forced flatten the caller supplies a real observed price for).

## Gap behaviour
A gap in bar arrival (no data for a period) never fabricates an intermediate fill or exit —
`on_bar` only ever acts on bars it actually receives. Once real bars resume, stop/target
detection continues correctly from the position's persisted state (proven by
`test_data_gap_after_fill_then_recovery_still_exits_correctly`).

## Spread/slippage assumptions
Reuses `talonx_backtest.execution.apply_entry_cost`/`apply_exit_cost` and `ExecutionConfig`
directly, with its own default (`entry_slippage_bps=0.0, exit_slippage_bps=0.0,
spread_bps=0.0`) unless a caller supplies a non-zero config — i.e. by default the shadow
ledger's `net_result` equals `gross_result` (identical to how the real PAPER broker models zero
commissions/fees today), same reasoning, not a new assumption.

## Data-gap and unresolved-outcome handling
- A `PENDING_FILL` shadow position that never observes a later bar before horizon/session end
  resolves `UNRESOLVED` / `UNRESOLVED_NO_FILL_BEFORE_HORIZON_END` — never a fabricated fill.
- An `OPEN` shadow position `force_close`d with `price=None` (a genuinely unknown flatten price)
  resolves `UNRESOLVED` / `UNRESOLVED_MISSING_CLOSE_PRICE` — never a fabricated exit price.
- `force_close` at real end-of-session uses the actual last observed bar's `close` — a real,
  observed price, exactly mirroring how the live system's own EOD flatten only ever acts on
  real broker/market state, never an invented one.

## Linkage and separation from PAPER
- Every `ShadowPosition` carries `decision_id`, cross-referencing the same `DecisionRecord` a
  notification (if any) and the real `order_intent` attempt (if any) are keyed by.
- `shadow_ledger.py` has **zero import of or reference to** `lifecycle.py`/`broker.py`/
  `order_intent` (confirmed by grep — see `broker_state_and_concurrency_evidence.json`) — a
  shadow position structurally cannot authorise, and cannot even attempt, a real broker
  mutation.
- `PaperEntrySettings`/`paper_entry_enabled` is never consulted anywhere in `shadow_ledger.py` —
  a PAPER-disabled ticker's approved-strategy BUY still gets shadow-tracked identically to an
  enabled one (proven by `test_paper_disabled_actionable_decision_still_creates_alert_and_shadow`).

## Persistence and idempotency
Same full-file JSON-rewrite pattern as `LifecycleState`/`DecisionLedger`/`NotificationOutbox`.
`consider_entry` is idempotent per `decision_id` (a duplicate/restarted call returns the
existing record unchanged); at most one `PENDING_FILL`/`OPEN` shadow position per symbol at a
time (mirrors the real one-position-per-symbol invariant).
