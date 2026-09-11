# Corrected rollback procedure (Task 117 final-activation A5)

Supersedes `docs/audits/task117_overnight_release_closure/rollback.md`'s
step 3, which used the wrong `%USERPROFILE%\.talonx\v2_lane.db` path and
described restoring pre-activation copies without reconciling anything
written since. See `resolved_paths_and_migrations.md` for the corrected real
paths.

## Principle: preserve legitimate post-activation writes

If the stack ran for any amount of time after activation, real writes may
have happened — new positions, entry intents, delivered/ambiguous card
attempts with message IDs. A rollback must not discard these by reflex.

**Order of preference, strongest guarantee first:**

1. **Compatible code rollback, keep the data** (preferred, and sufficient for
   everything in this release — see the change table below: every schema
   change is additive-only and every code change is a pure behavioural fix
   with no incompatible data format change). Older code simply ignores the
   new `intelligence_delivery` columns and the `schema_meta` digest keys;
   nothing needs to be stripped out of the database for old code to run
   against it correctly.
2. **Reconciled partial restore** — only if (1) is somehow insufficient:
   diff the live DB against the pre-activation backup, and re-apply
   post-backup rows on top of the restored backup rather than discarding
   them. Never a blind `copy` over the top.
3. **Full pre-activation restore** — last resort only, and only after (2) is
   confirmed impossible or the post-activation writes are confirmed
   worthless (e.g. the activation never got past `disabled` mode and
   produced no real writes at all).

## What this release actually changed

| area | change | why compatible-code rollback is enough |
|---|---|---|
| `intelligence_delivery` table | additive columns `attempt_id`, `in_flight_since_utc`, `transport_message_id` | older `DeliveryOutbox` code never reads them; a row with a value in `attempt_id` etc. from during activation is simply invisible to, and untouched by, the old code |
| `schema_meta` | `last_digest_bucket`, `last_digest_sent_utc` | older `process_digest` (if reached at all) recomputes its own bucket; these rows are inert extra state, not a format break |
| `v2_lane.db` | none in this task (the pre-existing `v2_alert_outbox.deliver_by_utc` column predates it) | n/a |
| delivery pipeline / outbox / telegram_client / runner / lock.py / proc.py / dashboard | pure code | `git checkout <PREV_SHA>` |

**No strategy input changed.** V2 fingerprint `11107198c5b81237` before and
after. Frozen thresholds / holding period / sizing / execution scope
untouched. No production timestamp history reinterpreted.

## Procedure

### 1. Stop owned writers BEFORE any recovery step
```
python -m talonx_ops.prospective close            # reconciles + ownership-safe stop_stack
```
This is ownership-verified (create-time + cmdline checked before any
terminate/kill) and reaps the whole supervisor tree, including the
supervised `intelligence` component — nothing is left half-stopped. If a
manual poll loop is somehow still running (it should not be, per
`supervised_intelligence.md`), Ctrl-C it — cooperative shutdown: an
in-flight claim is left `IN_FLIGHT` and recovered to `AMBIGUOUS` on the next
start, never blind-resent.

Confirm:
```
python -m talonx_ops.prospective status
```
Expect `NOT_STARTED`. Only if `status` shows no live owner, remove a stray
lock: `del <REPO_ROOT>\v2_lane.db.startlock` (note: this is the repo-root
path, not `~/.talonx`).

### 2. Prefer compatible code rollback — do this first
```
git -C C:\workspace\TalonX checkout <PREV_SHA>
```
`<PREV_SHA>` = the commit before the final Task 117 commit (recorded in
`docs/audits/task117_overnight_release_closure/MORNING_HANDOFF.md`). **Do
not restore any database.** The additive schema is forward- and
backward-compatible; older code runs correctly against a database that has
been touched by this release. Re-verify:
```
python -m talonx_ops.prospective preflight --expected-sha <PREV_SHA>
```
If this passes and the stack starts cleanly, rollback is **done** — stop
here. Positions, entry intents, message IDs, and ambiguous attempts recorded
during the activation window are preserved exactly as they are.

### 3. Only if code rollback alone is judged insufficient — reconciled restore
Do NOT proceed to this step without first stating, in writing, why (2) was
not enough.

1. Take a **fresh** copy of the current (post-activation) `v2_lane.db` /
   `ingestion_ledger.db` — call it `*.post_activation_<UTC>`.
2. Diff it against the `*.pre_activation_<UTC>` backup made before activation
   (§1 of `deployment_candidate.md`): specifically enumerate
   - new/changed rows in `positions`, `pending_entry_intents`,
     `processed_episodes`, `trades` (v2_lane.db)
   - new/changed rows in `intelligence_delivery` (state, `attempt_id`,
     `transport_message_id`, `sent_at_utc`) and `intelligence_delivery_log`
3. Write the diff to a reconciliation file BEFORE touching anything:
   `results/task117_rollback_reconciliation_<UTC>.json`.
4. Restore the pre-activation backup, then **re-apply** the diffed
   post-activation rows on top of it (INSERT/UPDATE by primary key) — never a
   raw file copy that discards them.
5. Verify row-for-row against the reconciliation file before declaring done.

### 4. Full pre-activation restore — last resort
Only if (3) is confirmed impossible (e.g. the diff cannot be safely
reconciled) or the post-activation writes are confirmed worthless (activation
never left `disabled` mode). Even then:
```
copy v2_lane.db.pre_activation_<UTC>               <REPO_ROOT>\v2_lane.db
copy v2_service_status.json.pre_activation_<UTC>   <REPO_ROOT>\v2_service_status.json
copy env.pre_activation_<UTC>                       <REPO_ROOT>\.env
copy ingestion_ledger.db.pre_activation_<UTC>       %USERPROFILE%\.talonx\ingestion_ledger.db
```
State explicitly, in the incident record, that this discards any
post-activation writes and why that was judged acceptable.

## Redis

Never flush or restart `talonx-redis`. Rollback does not touch Redis. Any
comingled `metrics:*` keys are historical and read-only.

## Partial-start failure

`prospective start` already self-heals a partial start:
`FAILED_WITH_RESIDUALS` → automatic ownership-safe `stop_stack` +
`start_cleanup.json` (bounded rollback of only what that start attempt
spawned — see `ownership_lifecycle_tests.md` item 7). No manual rollback
needed for a failed start.
