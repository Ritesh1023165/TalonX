# Task 118F — resilient warmup: deployment and live acceptance (2026-09-11)

## Deployment sequence

1. **Pre-deployment cutoff**: `2026-09-11T15:50:06Z`. Effective config
   recorded (39-name scope, 45-day lookback, composite-yf, official
   delivery on, Experimental external off), positions recorded
   (Experimental: 4 closed, SPCX open; V2: 0 positions, cash $300,000),
   `v2_lane.db` md5 unchanged from this morning.
2. **Stop**: `stop_stack(results/prospective_2026-09-11)` — clean,
   `residual_talonx_processes: []`, all ports closed, verified via direct
   `psutil.pid_exists()` on all three previous pids (all `False`).
3. **Backups** (WAL-checkpointed `v2_lane.db` first): all four databases +
   `.env` copied to `talonx_activation_backups\*_20260911T155006Z`.
4. **Deploy**: `git merge --no-ff hotfix/task118f-resilient-warmup` (the
   hotfix diverged from the deployed `c88f4d4` after a docs-only commit
   `0209ada` landed directly on the release branch meanwhile — a
   fast-forward wasn't possible; a regular merge commit was used instead,
   no conflicts) → **`5c0b3f3ccfef45ff8438e75f8f614b738deefc9a`**.
5. **Migrations**: none required.
6. **Restart**: same approved configuration, same env vars re-exported.
   Started `2026-09-11T15:51:18Z`. Startup verdict **READY** — checkpoint
   daemon alive on the first attempt this time (Task 118A's stale-
   stop-flag fix confirmed working correctly across sessions).
7. Same ledger paths preserved; no replacement campaign.

## Live acceptance — the fix observed working in production

`original.log` (the real, running process):
```
16:52:32,816  Initial Quant preseed complete: 41/43 symbol(s) ready
16:52:35,442  Bounded preseed recovery sweep complete: 1/2 previously
              not-ready symbol(s) recovered in 2.6s (still incomplete: ['NUE'])
```
**Live readiness immediately post-restart: 42/43** (verified independently
against `quant.db.bar_buffer`, not merely the log line) — up from 30/43
just before this restart, and dramatically better than the 25/43 this
task started from. NUE, the one symbol the sweep could not fully recover,
is honestly reported **not ready** (116/120 bars) rather than silently
treated as green — expected to close via ordinary live accumulation
within minutes (4 bars short).

## Continuity verified

- Experimental: all 9 `trade_history` rows (5 BUY + 4 SELL) and the one
  open SPCX position identical before/after — no duplicate entries or
  exits, no replayed historical exit, realized P&L unchanged
  (−$324.4662160270568).
- V2: cash $300,000, 0 positions, the same ABCL stale episode id
  `07242bc857569f60` (no replay), `alert_outbox.total: 0` (no spurious
  V2 activity from the warmup fix — V2 code was not touched by this
  hotfix at all).
- V2 fingerprint `11107198c5b81237` unchanged — `preflight`'s
  `v2_fingerprint` gate `[OK]` both before and after.
- Checkpoint daemon, single V2 writer, single supervisor — all confirmed
  via fresh pids registered in `session.pids.json` and verified alive by
  direct `psutil` inspection.
- Redis untouched — not flushed, no counters reset.

## Evidence

`docs/audits/task118f_resilient_warmup/IMPLEMENTATION.md` (design +
tests + isolated real-provider probe); this file (deployment + live
acceptance); backups at
`C:\Users\rites\talonx_activation_backups\*_20260911T155006Z`; commit
`5c0b3f3` (merge of `hotfix/task118f-resilient-warmup`, commit `4531fe2`).
