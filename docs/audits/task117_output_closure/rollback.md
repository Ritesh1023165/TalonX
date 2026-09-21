# Rollback — Task 117 output closure

The change set is **code + tests only**. Nothing was migrated, sent, or activated, so rollback is
`git revert` plus (optionally) one config flag.

## Full rollback

```
git revert <this commit sha>        # on research/talonx-strategy-validation
```

Reverts every file. Production `v2_lane.db`, `ingestion_ledger.db`, Redis, and the
`intelligence_delivery` backlog are untouched by this task, so there is nothing to restore.

## Partial rollback — keep everything except the timestamp change

If the EDGAR-Eastern reading is later shown wrong for some feed path, **do not revert** — flip
one constant:

```python
# talonx_ingest/intelligence/edgar_normalize.py
EDGAR_ACCEPTANCE_ASSUMES_EASTERN = False
```

This restores the pre-fix behaviour (bare `Z` treated as literal UTC) for **new** ingestion.
Explicit offsets are still respected. Rows already ingested with `acceptance_tz_assumed_eastern`
carry the flag, so they are identifiable and can be reverted by the inverse of the migration
proposal (localize UTC → naive, drop the flag) on a copy.

## Per-defect rollback

| defect fix | how to disable without a revert |
|---|---|
| D1 funnel scope | callers pass `build_funnel(..., execution_allowlist=None)` — restores unrestricted funnel |
| D2 poller dedup | no toggle; `git revert` just `talonx_ops/supervisor.py` hunk if needed |
| D3 EOD session-date | `git revert` the `dashboard_read.py` hunk; the API just returns the old (wrong) tile |
| D5 age cutoff | it is opt-in (`enforce_age_cutoff=False` default) and unwired — already inert; delete `expire_stale`/`CARD_MAX_AGE_SECONDS` if desired |
| D7 heads-up telemetry | `git revert` the `consumer.py` hunk — one extra cache row stops being written |
| `form4_source` ET date | `git revert` that hunk — reverts to `t.accepted_at_utc.date()` (UTC date) |

## What cannot be "rolled back" because it never happened

- No production DB migration was run → nothing to un-migrate.
- No Telegram message was sent → nothing to retract.
- No backlog row was expired / deleted / marked SENT in production.
- No watchlist / scope / threshold change → no universe to shrink back.
- The application was not started → no session to unwind.

## Verify post-rollback

```
git checkout research/talonx-strategy-validation
./.venv/Scripts/python.exe -c "from research.scripts.task112_v2_release_fingerprint import v2_release_fingerprint as f; print(f()['fingerprint'])"
# expect: 11107198c5b81237
md5sum v2_lane.db     # expect: 29e57dbcd1a567fbc4bb0e73efdba95f
docker exec talonx-redis redis-cli PING   # expect: PONG
```
