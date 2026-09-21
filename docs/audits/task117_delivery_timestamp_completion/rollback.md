# Rollback

Code + tests only. Nothing migrated, sent, activated, or expired in production.

## Full rollback

```
git revert <this commit sha>          # on research/talonx-strategy-validation
```

Production `ingestion_ledger.db` (md5 `2ae2105c6f51a4af4b3b80dc06e5f30f`),
`v2_lane.db` (`29e57dbcd1a567fbc4bb0e73efdba95f`), Redis and the
`intelligence_delivery` backlog are untouched — nothing to restore.

## Per-area rollback without a full revert

| area | disable / revert |
|---|---|
| runner delivery drain | it is already inert (`deliver_intelligence_cards=False` → `mode="disabled"`, mutates nothing). To remove entirely: revert the `deliver_cycle` call in `runner.run_poll_loop` and the `deliver_cycle` method. |
| `process_pending` mode contract | callers that want the old always-mark-SENT dry-run behaviour: there is none — the old behaviour was the bug. If truly needed, `mode="simulate"` renders the plan without SENT; `mode="enabled"` with a `RecordingSender` records + marks SENT in an isolated ledger. |
| `AMBIGUOUS` state | revert the `mark_ambiguous` calls in `process_pending`; ambiguous outcomes fall back to `mark_failed` (transient RETRY). |
| `expire_stale` event-time basis | drop the `event_time_lookup` argument → back to enqueue-time only. |
| timestamp `source` contract | `parse_acceptance_datetime(raw)` with no `source` defaults to `"submissions"` == genuine UTC == the pre-task (pre-`48d2946`) behaviour. Nothing to disable. The `sgml_header` contract is unwired. |
| D4 startup verdict / concurrent guard | `--force` bypasses `assert_no_live_prior_stack`. To remove: revert the `proc.py` + `__main__.py` hunks; `cmd_start` returns to the preflight-verdict print. |
| D6 lane accounting | revert the `close.py` hunk (one `atomic_write`) + delete `lane_accounting.py`; `prospective close` stops writing `lane_accounting_eod.json`. |
| `form4_source.py` | already reverted to the pre-task original. |

## What never happened (nothing to undo)

- No Telegram message sent.
- No `intelligence_delivery` row expired / deleted / marked SENT in production.
- No `ingestion_ledger.db` write / rebuild.
- No `v2_lane.db` write; V2 fp unchanged.
- No config activation (`TALONX_INTEL_DELIVER_CARDS` unset).
- No application started; Redis retained, not flushed.

## Verify post-rollback

```
git checkout research/talonx-strategy-validation
./.venv/Scripts/python.exe -c "from research.scripts.task112_v2_release_fingerprint import v2_release_fingerprint as f; print(f()['fingerprint'])"   # 11107198c5b81237
md5sum v2_lane.db                     # 29e57dbcd1a567fbc4bb0e73efdba95f
md5sum ~/.talonx/ingestion_ledger.db  # 2ae2105c6f51a4af4b3b80dc06e5f30f
docker exec talonx-redis redis-cli PING   # PONG
```
