# Task 79E — Remaining Issues

None of the items below block the `EXPERIMENTAL_MODE_READY_FOR_OPERATOR_REVIEW`
verdict — the feature is inert (unreachable) until an operator authors a
live `experimental_authorization.json`, so none of these can manifest in
production today. They are disclosed for the operator's own risk
assessment before ever authoring one.

## 1. `DecisionEngine.positions` is not rehydrated after a process restart

**Pre-existing, not introduced or worsened by this task.**
`DecisionEngine.__post_init__` always initialises `self.positions = {}`
fresh on construction; it is never rebuilt from `lifecycle.state.positions`
on restart. This affects an ordinary `STRATEGY` position exactly the same
way it affects an `EXPERIMENTAL` one — a restart loses in-memory knowledge
of an open position's stop/target plan at the decision-engine layer (the
broker-side position and `lifecycle.state.positions` entry are unaffected
and still get flattened correctly at EOD via `broker.close_all_positions()`,
which is source-agnostic). Fixing this is a broader, pre-existing
architectural gap out of this task's scope; flagged here rather than
silently left undocumented specifically because Task 79E's design leans on
`OpenDecisionPosition.experimental`/`experimental_id` for post-entry exit
labelling, which is one more reason a future task should close this gap.

## 2. No corrupt/missing-state-specific test for the experimental budget ledger

`LifecycleState.experimental_budgets` uses the same `field(default_factory=dict)`
/ JSON load-or-default pattern every other `LifecycleState` field uses, and
the existing `test_task77i_runtime_safety.py` corrupt-state suite passed
unchanged (proving the addition does not break that suite's existing
corrupt-state handling), but no NEW test was written proving a corrupted
`experimental_budgets` sub-object specifically fails closed (blocks new
PAPER exposure) rather than silently resetting to an empty, therefore
budget-forgetting, dict. Recommend a dedicated test before this ledger is
relied upon for a real multi-day experiment.

## 3. `strategy_id` binding is the raw `SignalType` value, not a curated identifier

`experimental_buy_permitted` is computed using
`strategy_id=signal.signal_type.value` (e.g. `"macd_bullish_cross"`) — the
same identifier already used for `Decision.strategy_id` throughout the
existing codebase, so this is consistent, not a new inconsistency. It does
mean an authorization is bound to one specific signal-generation rule, not
to "the natural strategy" as a whole; this is almost certainly the correct,
narrower scope for an experimental permission, but is worth the operator's
explicit awareness when authoring `strategy_id` in a real authorization
file.

## 4. Observability's new `experimental` section is additive, not exhaustive

`build_integrated_projection`'s new `"experimental"` block counts
decisions/notifications/shadow/paper-orders but does not itself compute a
win-rate or P&L rollup for experimental activity (no such rollup exists yet
for the ordinary shadow path either — `shadow_ledger.py`'s own records are
the raw material for that, not this projection). Out of scope for this
task; noted so a future observability task does not assume the number is
already there.
