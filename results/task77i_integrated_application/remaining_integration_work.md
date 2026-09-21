# Task 77I — Remaining Integration Work (deliberately not done in this task)

## 1. No strategy-approval registry still exists
Carried forward from Task 76S, now load-bearing in a NEW way: with `decide()` wired into the
live path, every real decision resolves `StrategyApprovalStatus.UNVALIDATED` ->
`NO_TRADE`/`STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION`, and (by this task's own
deliberate design — see `shadow_simulation_policy.md`) shadow tracking is ALSO inert for real
traffic until such a registry exists. **Recommended follow-up**: a small, separately-reviewed
task to build the registry itself (not invented here, per this task's own explicit
instruction).

## 2. `paper_entry_settings.json` still does not exist in production
Unchanged from Task 76S — no ticker is entry-enabled until an operator explicitly creates it.

## 3. Decision-record fields `shadow_status`/`execution_status` are not yet write-back-populated
`DecisionRecord.shadow_status` and `DecisionRecord.execution_status` (distinct from
`decision_execution_status`, which IS populated at record time from `decide()`'s own
`ExecutionStatus`) remain `NOT_APPLICABLE` today — `ShadowLedger` and `PaperLifecycle` are
queried independently (by `decision_id` / `correlation_id`) rather than writing back into the
decision ledger's own mutable status fields. This was a deliberate scope decision: writing back
would require `ShadowLedger`/`PaperLifecycle` to hold a reference to `DecisionLedger` (a new
coupling point) rather than remaining structurally independent (see
`broker_state_and_concurrency_evidence.json`'s explicit proof that `shadow_ledger.py` has zero
reference to broker/lifecycle code) — a future task could add a thin read-only JOIN in
`observability.py` instead of adding this coupling, which is arguably the better design and is
flagged here rather than rushed.

## 4. No genuine cross-process file locking
Documented, not invented, in `broker_state_and_concurrency_evidence.json` — no code path outside
the single live-session process reaches `order_intent` today, so this has not been a live risk,
but a future task adding a second writer process (e.g. a separate alert/shadow worker) would
need to revisit this.

## 5. `data_provider` field always null in decision records
`decide()`'s callers (`decision_engine.py`) never plumb a provider-identity string through —
`session_runner.py`'s own provider-health tracking (`freshness.py`) is separate infrastructure
that this task surfaces read-only in `observability.py`'s `provider_and_data_health` section,
but does not yet thread into each individual `Decision`/`DecisionRecord`.

## 6. Notification WATCH classification is the only observational category wired today
Per `alert_delivery_contract.md`, `PREMARKET_WATCH`/`PREMARKET_WATCH_CLEARED` (the pre-market
radar's own, older, and completely separate observational mechanism — see `premarket_radar.py`)
is NOT unified with this task's new `WATCH_OBSERVATION_ONLY` notification classification; the
two remain distinct, parallel observational channels. Unifying them was judged out of scope
("no full process orchestration... in this task").

## 7. `observability.py` is a minimal read-only projection, not a served endpoint
No HTTP/API server is started by this task (`dashboard.py`/`dashboard_web.py` are a wholly
separate, unrelated subsystem — see `implementation_plan.md`). `build_integrated_projection`
is a pure function a future task can wire into an existing or new API surface; this task
deliberately does not build that surface itself ("Do not redesign dashboards or implement full
process orchestration... in this task").

## 8. Time/horizon-based shadow exit is not implemented
`shadow_simulation_policy.md` documents this explicitly: only stop/target/forced-flatten close
a shadow position today — no independent horizon clock exists (matching the real system, which
also has no such clock).
