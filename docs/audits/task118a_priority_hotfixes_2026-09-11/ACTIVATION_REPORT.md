# Task 118A — priority hotfixes, validation, controlled restart (2026-09-11)

**Verdict: HOTFIX_DEPLOYED_AND_RESTART_VERIFIED.**

Baseline verified before work: SHA `fb4b071eafb74f13bf2ab290d1e2c80e400d6163`,
session `results/prospective_2026-09-11`, V2 fingerprint `11107198c5b81237`,
scope 39/45-day/composite-yf, matching the handoff exactly. Actual UTC time
checked before every state-changing step (pre-open throughout: work began
~11:03 UTC, restart at ~11:54 UTC, all well before the 13:30 UTC open and
20:00 UTC close).

## A. Preflight and isolation

Isolated hotfix checkout: `C:\workspace\TalonX-task118a-hotfix`, branch
`hotfix/task118a-experimental-exit-lifecycle`, based on the exact running
SHA `fb4b071`. All code changes made there — the live release worktree's
files were **not** edited while its processes were running (one
accidental direct edit to `talonx_ops/prospective/proc.py` was caught
immediately via the harness's own "file changed on disk" notice and
reverted with `git checkout --` before it could be mistaken for a review
step; the correct edit was then made in the isolated worktree instead —
recorded here rather than omitted).

## B. Priority findings (full detail in the companion documents)

| priority | verdict | evidence |
|---|---|---|
| 1 — Experimental exit lifecycle | **confirmed + fixed** | `PRIORITY1_EXPERIMENTAL_EXIT_LIFECYCLE.md` |
| 2 — Original warmup/readiness | **expected (external provider), documented, no fix** | `PRIORITY2_ORIGINAL_WARMUP.md` |
| 3 — operator-visible correctness | **4 confirmed + fixed, 1 addressed via P1, 1 not reproduced** | `PRIORITY3_OPERATOR_VISIBLE_CORRECTNESS.md` |
| (found during restart) checkpoint-daemon stale stop-flag | **confirmed + fixed** | this document, §D, §E |

## C. Validation (isolated hotfix worktree, before deployment)

- Targeted new tests: 16 (P1 exit lifecycle) + 4 (P3 digest) + 2 (P3
  message count) + 3 (checkpoint-daemon restart) = **25 new tests, all
  passing**.
- Regression sweep (`-k "dashboard or digest or pipeline or delivery or
  intelligence or eod_reconcil or supervisor or authoritative or task118a
  or task99a or task99b or task100 or prospective or task117_phase0"`):
  **835 passed**, 1 pre-existing failure (`test_100a::test_2_no_producer_
  yields_no_active_producer`, confirmed identical on the untouched
  pristine release worktree — a pre-existing PID-liveness-detection flake
  unrelated to any change here) plus 9 pre-existing failures caused
  entirely by gitignored `results/` artifacts absent from this freshly
  created worktree (confirmed by diffing against the real worktree; not a
  code regression).
- V2 fingerprint verified unchanged both by direct inspection (no
  `talonx_v2/*` file touched) and by the supported `preflight` gate
  (`v2_fingerprint: [OK]`) both before and after deployment.
- A full untargeted `pytest tests/ -q` run was started in the background
  for maximum coverage; stopped early (after the targeted+broad sweep
  above already gave strong, clean confidence and the deployment window
  was time-sensitive) rather than left to consume CPU indefinitely
  alongside the live session — noted honestly rather than claimed
  complete.

## D. Restart scope chosen, and why

**Full-stack restart** (`stop_stack` + `start`), not a single-component
restart. Reasoned explicitly: the P3(f) fix touches
`talonx_ops/supervisor.py` — the supervisor's **own** code, not just a
component it spawns. Since the currently-running supervisor process
already has that module loaded in memory (Python does not hot-reload),
only restarting the supervisor process itself picks up that change, which
in this stack's architecture means a full `stop`/`start` cycle. A
component-only restart would have left the supervisor running an
incompatible (pre-fix) revision while its children ran the new one —
exactly the "dependent components running an incompatible revision" this
task's process instructs against.

`close` was **not** used as the stop mechanism — `run_close()` was
inspected first and confirmed it does nothing (does not call
`stop_stack`) when EOD is not due and `force` is not passed; calling it
with `--force` instead would have written a real EOD reconciliation
record hours before the actual close, exactly the misuse this task
prohibits. The actual, already-existing, ownership-safe
`talonx_ops.prospective.proc.stop_stack(session_dir)` was invoked
directly instead — the same tested mechanism `close` itself uses
internally, without the EOD side effect.

## E. Controlled deployment — executed sequence

1. **Pre-deployment cutoff**: `2026-09-11T11:53:10Z`.
2. **Stop**: `stop_stack(results/prospective_2026-09-11)` — clean:
   checkpoint_daemon (tree 3), v2_companion (tree 3), supervisor (tree 11)
   all `status: stopped`, `residual_talonx_processes: []`, ports
   8787/8760/8770/8501 all closed, `startlock_released: true`,
   `v2_lane_db_intact: true`. Verified independently (not merely trusting
   the return value) via direct `psutil`/`tasklist` process lookup and a
   Windows process-list scan — zero processes with `prospective`, `v2`,
   `supervisor`, `talonx_signals`, or `intelligence.service` in their
   command line remained.
3. **Backups** (writers confirmed stopped; `v2_lane.db` WAL-checkpointed
   first): `v2_lane.db`, `ingestion_ledger.db`, `exp_alerts.db`,
   `experimental_paper.db`, `.env` — all copied to
   `C:\Users\rites\talonx_activation_backups\*.pre_task118a_hotfix_20260911T115331Z`
   (outside every tracked path; secrets never printed).
4. **Deploy**: `git merge --ff-only hotfix/task118a-experimental-exit-lifecycle`
   in the release worktree → `72baca2` (P1/P2/P3), then, after the
   checkpoint-daemon defect below was found and fixed, a second
   fast-forward → **`c88f4d4600735dcc65fb5108c73489e877d16ebe`**. No
   broad research merge; release branch only.
5. **Migrations**: none required (no schema change in this hotfix).
6. **Restart**: same approved effective configuration —
   `--tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45
   --pricing-mode composite-yf --execution-scope resolved-active-watchlist
   --deliver --transport telegram`, same 6 `TALONX_INTEL_DELIVER_*` env
   vars re-exported before `start` (unchanged values). Started
   `2026-09-11T11:54:30Z`. Startup verdict **READY**.
7. Same ledger paths preserved throughout (`v2_lane.db` at the repo root,
   `ingestion_ledger.db` at `~/.talonx`) — no replacement campaign created.

### A second finding, during the restart itself: stale `stop.flag`

The freshly spawned checkpoint daemon (pid recorded as 11056) was
confirmed, via direct `psutil` lookup, to be **not running** seconds after
spawn, despite a clean spawn call and no error output. Traced to source:
`stop_stack()` (step 2) writes `<session_dir>/stop.flag`; `start_stack()`
never cleared it before spawning a new daemon, and `session_loop.py`
checks that flag **first**, before its first checkpoint — so the new
daemon saw the stale sentinel from step 2 and exited immediately (clean
exit 0, empty log — indistinguishable from "still starting" without this
investigation). This is a genuine defect in the same-session-restart path
this task specifically exercises, not a hypothetical.

**Immediate recovery** (same session, same supported `_spawn()` mechanism
used everywhere else, same argv/log path `prospective start` itself uses):
stale flag removed, checkpoint daemon manually respawned as pid **9612**,
confirmed alive via direct `psutil` inspection and still alive at the time
of this report.

**Permanent fix**: `_start_stack_locked` now clears a stale `stop.flag`
before spawning anything (`talonx_ops/prospective/proc.py`), with 3 new
tests including two real-subprocess reproductions of the exact bug
(`tests/test_task118a_checkpoint_daemon_restart.py`). Committed
(`c88f4d4`) and merged into the release branch (inert for the currently
running processes — `proc.py` is not imported by any of them at runtime;
it only affects the *next* `start`/`close` invocation). **A third live
restart was deliberately not performed today** to pick this up
immediately — today's session is already healthy via the manual recovery,
and the fix has zero effect on anything already running; forcing another
full-stack interruption for a fix that only matters on the *next* restart
would not be proportionate. It will take effect automatically the next
time `prospective start` runs.

## F. Post-restart acceptance — verified against the live process, not a fixture

- **Startup**: `READY` within the bounded grace period; all mandatory
  components (supervisor, V2 companion, `:8787` dashboard) and the
  checkpoint daemon (after the manual recovery above) confirmed alive by
  direct process inspection, not merely a printed summary.
- **One writer per ledger, one Telegram polling owner**: `preflight`
  (post-deploy, `--expected-sha c88f4d4...`) — all 17 gates `[OK]`,
  including `telegram_logical_owner`, `v2_ledger_continuity`,
  `v2_ledger_not_recreated`.
- **V2 scope/fingerprint/cash/positions/ABCL disposition preserved**:
  live `/api/section/v2_active_strategy` — fingerprint `11107198c5b81237`
  unchanged, scope 39/45-day/composite-yf unchanged, cash $300,000, 0
  positions, **the identical ABCL stale episode id `07242bc857569f60`**
  (not a new/different one — no replay), `campaign_day: 4` (campaign-day
  counter continuity preserved across the restart, not reset).
- **No duplicate entries/exits/deliveries**: `card_delivery.by_state`
  unchanged (`SENT: 6, EXPIRED: 9850`) immediately post-restart — no
  historical-alert flood, nothing re-sent. `messages_sent_today: 1` now
  correctly distinguishes cards from messages (the P3(c) fix, confirmed
  live).
- **Experimental exits now receive valid market observations — confirmed
  live, not merely by test**: within minutes of restart, **VRT's exit
  fired for real** through the newly-wired path — `exit: $251.0872125`,
  `exit_reason: confirmed_bearish` (mapped from `stop_loss`),
  `net_pnl: -$213.72`, `closed_at: 2026-09-11T07:53:51-04:00` (the tick's
  own causal time, not wall-clock, not backdated to the original breach).
  Authoritative-ledger reconciliation confirmed directly:
  `positions` row for VRT gone, a single new `trade_history` SELL row
  (id=6, no duplicate), `portfolio_state.current_cash` correctly
  increased to $89,786.28, `win_count/loss_count` updated. The
  display-log row (`exp_alerts.db.experimental_trades`, same `trade_id`
  as the original BUY) was updated in place, not duplicated.
  `live_external_sends: 0` throughout — no Telegram send for this exit,
  by design.
- **Remaining existing positions**: BLSH, AMD, STX, SPCX still open,
  unaffected — correct, since their live prices have not (yet) crossed
  their recorded stop/target; each will resolve independently on its own
  first qualifying tick, per the same established gap/fill policy.
- **Dashboard values agree with authoritative state**: cross-checked
  `/api/section/v2_active_strategy`, `/api/section/overview`,
  `/api/section/intelligence`, `/api/section/validation` against direct
  SQLite reads of `v2_lane.db`, `ingestion_ledger.db`,
  `experimental_paper.db` — all consistent.
- **Redis**: not flushed, not restarted — `redis_reachable: [OK]` in
  preflight, no Redis mutation performed at any point.
- **No unrelated process affected**: process/port scan post-restart shows
  only the expected supervisor tree + companion + checkpoint daemon; no
  PIV, Streamlit, or other unrelated TalonX process was touched.
- **No real-capital, short, or broker activity**: `real_capital_off:
  [OK]`, `active_profile_is_v2: [OK]`, unchanged.

No natural V2 trade was required for, or used to claim, this acceptance —
`business_activity: NO_OPPORTUNITIES` throughout, honestly reported.

## G. Today's EOD

Not yet due (`NOT_DUE_YET`, checked repeatedly through
`2026-09-11T12:05 UTC`; close is `20:00 UTC`). **Required operator
action**: `python -m talonx_ops.prospective close`, at/after
**2026-09-11T20:00:00Z**, complete by **21:30:00Z**. No recurring job or
background monitor was created — this session does not run unattended
past this report.

## Evidence

`docs/audits/task118a_priority_hotfixes_2026-09-11/` (this file +
PRIORITY1/2/3); commits `72baca2` (P1/P2/P3) and `c88f4d4`
(checkpoint-daemon fix) on `hotfix/task118a-experimental-exit-lifecycle`,
merged into `research/talonx-strategy-validation`; backups under
`C:\Users\rites\talonx_activation_backups\*_20260911T115331Z`.
