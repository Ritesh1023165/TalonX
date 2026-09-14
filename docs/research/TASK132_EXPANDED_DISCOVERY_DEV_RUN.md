# Task 132 — Enable Expanded Discovery in the Existing End-to-End Development Flow

Branch `feature/task131-option-a-integration` (no new branch), on top of
`4f0af50`. **Explicit user authorization overriding the prior blanket
activation HOLD**, scoped precisely: "go live" here means live data, the
existing Telegram destination, local paper tracking and dashboards — NOT
real-money trading or a public product launch. Full evidence bundle
(configuration snapshot, development-run report with real counters):
`results/task132_development_run/` (gitignored, like every other
`results/` evidence directory in this repo).

## What this task found and fixed

Two concrete, verified (not guessed) operational blockers, discovered by
inspecting the actual launch scripts and process ownership before writing
any code — both purely additive, both off-by-default, both proven against
the real running process tree, not merely the invoking shell.

### 1 — `.env` was never loaded by the real trading/ingestion process tree

`run_talonx.py`, `talonx_ops/supervisor.py`, `talonx_v2/run.py`, and
`talonx_ops/prospective` never called `load_dotenv()` — only `dashboard.py`
and `talonx_ops/cli.py` did. `TELEGRAM_BOT_TOKEN`/`CHAT_ID` and the
`TALONX_*` toggles configured in the repo's own `.env` were invisible to
the live stack unless an operator manually exported them in the exact
shell used to launch it — "a setting visible only in a shell or dashboard
process," precisely the failure mode this task was told to close.

Fixed with `load_dotenv()` (same resolution pattern as `dashboard.py`:
absolute path, `override=False` so a real shell-set var always wins) in
`talonx_ops/supervisor.py`, `talonx_v2/run.py`, and — most importantly —
`talonx_ops/prospective/__main__.py`, since `proc._spawn()` merges
`{**os.environ, **env}` for every child it spawns (supervisor, V2
companion, checkpoint daemon); loading `.env` into THAT process's own
`os.environ` before anything is spawned is what makes every downstream
child correct regardless of the launching shell's state.

**Verified, not assumed**: with `TELEGRAM_BOT_TOKEN`/`CHAT_ID` explicitly
unset in a clean subshell, merely importing `talonx_ops.prospective.
__main__` (which `python -m talonx_ops.prospective ...` always does)
populated both into `os.environ` from `.env`.

### 2 — the real V2 launcher had no way to request expanded discovery

`talonx_ops.prospective start` (the established, atomic-single-writer-
locked, restart-safe V2 launcher — Task 112T: never `supervisor
include_v2`, which reads stale parquet) had no flag threading
`talonx_v2.run`'s own `--enable-broad-discovery` through to the spawned
companion. The only way to get expanded execution scope into a live V2
companion was an unsupervised, ad-hoc `python -m talonx_v2.run`
invocation that bypassed the real launcher — its single-writer lock, its
restart-recovery verification, its EOD close command — entirely.

Fixed by threading `enable_broad_discovery` through `start_stack()` ->
`_start_stack_locked()` -> the companion's own `v2_argv`, and a new
`prospective start --enable-broad-discovery` CLI flag. OFF by default;
every existing caller/test is unaffected.

### A design decision reverted before committing

An earlier draft also added a `--send-intelligence` CLI flag to
`talonx_ops/supervisor.py`, to enable the intelligence service's own
informational-card delivery. Reverted after discovering (by reading, not
guessing) that `TALONX_INTEL_DELIVER_CARDS` / `TALONX_INTEL_DRY_RUN_
DELIVERY` env vars already provide the identical capability via plain
env-var inheritance, and that `tests/test_task117_supervised_
intelligence.py::test_intelligence_argv_never_includes_a_second_send_flag`
explicitly documents why a CLI flag baked into that always-running
component's argv is the wrong shape (an unreviewable, silent default).
Only the `.env`-loading and `--enable-broad-discovery` changes remain.

## What was deliberately NOT touched

- No strategy file (the 5 fingerprinted `talonx_v2/{config,cluster_
  engine,liquidity,quant_bridge,brain_bridge}.py`) — fingerprint
  `11107198c5b81237` verified unchanged throughout.
- No threshold, filter, or admission-policy semantics — `TALONX_V2_
  DURABLE_STORE_ENABLED=true` (GATED) is a pre-existing, already-tested
  toggle from Task 131, not a new mechanism.
- No Supervisor lifecycle redesign — the existing 4-component supervised
  stack (Original/Experimental/Intelligence/Dashboard) and the existing
  standalone V2-companion pattern (Task 112T) are both used exactly as
  designed; nothing merged, nothing replaced.
- No second SEC poller, no second paper engine, no new Telegram
  recipient, no broker API, no real capital.
- No reset of the existing $300,000 campaign ledger — cash and the (zero)
  open-position count were verified identical immediately before and
  after this task's launch.

## Isolated verification before the live launch

The existing, accepted Task 131 timing/concurrency/dashboard test suite
(15 files: `test_task131_*`, `test_task114_prospective.py`,
`test_task100b_runtime_integration.py`, `test_task78i_supervisor.py`,
`test_task117_single_writer_lock.py`, `test_task117_supervised_
intelligence.py`, `test_task112_tuesday_release.py`, `test_task113_
stale_entry_guard.py`) was re-run as-is — reused, not redesigned, per
explicit instruction — covering every journey stage named in the task
(discovery observation, rejected-but-observable candidate, timely intent
+ reservation, delayed reference-price reconciliation, restart/duplicate
handling, position/dashboard update, exactly-once exit settlement,
outbox recovery, missing-price expiry, EOD reconciliation). **224
passed, 0 failed.** 2 new tests added (`test_task114_prospective.py`)
covering the new `--enable-broad-discovery` argv wiring specifically,
using a monkeypatched `_spawn()` (no real process launched) and
`tmp_path`-redirected `V2_DB_PATH`/`V2_STATUS_PATH` (never the real
repo-root ledger).

## The live development run

Full detail, real log excerpts, and honest counter-by-counter reporting:
`results/task132_development_run/DEVELOPMENT_RUN_REPORT.md`. Summary:

- Launched via `talonx_ops.prospective start --expected-sha aca1a4c
  --execution-scope resolved-active-watchlist --enable-broad-discovery
  --deliver --transport telegram`, with `TALONX_INTEL_ENABLE_BROAD_
  DISCOVERY` / `TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY` / `TALONX_V2_
  DURABLE_STORE_ENABLED` / `TALONX_INTEL_DELIVER_CARDS` / `TALONX_INTEL_
  DRY_RUN_DELIVERY` set. Startup verdict **READY** (all mandatory
  components confirmed alive by the operator's own real health/heartbeat/
  dashboard checks).
- Expanded scope confirmed reaching the real processes via their OWN
  startup logs (not the launching shell): V2 execution scope 39 -> 626
  (39 watchlist + 587 broad-discovery-only); intelligence ingestion
  scope 39 -> 569.
- One clearly-labelled `[DEVELOPMENT TEST]` Telegram message sent to the
  established, verified destination — real message ID `724` returned.
- 10 real informational discovery-card rows enqueued for a genuine
  broad-discovery-only symbol (`A`), correctly `PENDING` (queued, not
  yet delivered) rather than silently dropped or fabricated as
  delivered.
- 0 entries, 0 exits, 0 new pending intents at report time — an honest
  reflection of pre-market timing (XNYS session today had not yet opened
  at report time) and the frozen strategy's own selectivity, not a
  failure.
- Existing $300,000 cash and 0 open positions preserved exactly,
  unchanged before and after launch.

## Validation summary

- Focused battery (prospective + supervisor + Task131 timing/concurrency
  + dashboard, 15 files, pre-launch): 224 passed, 0 failed.
- Full repository suite (post-launch, candidate `aca1a4c`): **4655
  passed, 8 failed, 6 skipped** (0:51:51).
- Frozen strategy fingerprint `11107198c5b81237`: verified unchanged
  before the launcher fix, before the live launch, and after the full
  suite run.

### 8 failures, compared by exact name AND exact reason — 4 pre-existing, 4 environmental, 0 new regressions

Running the full suite AFTER launching the live stack (rather than
before) was this task's own methodological mistake — it produced 4
failures beyond the documented baseline. Investigated precisely rather
than assumed:

- **4 confirmed pre-existing, unrelated to Tasks 131/132**:
  `test_task102_operational_finalization.py::test_36_original_strategy_
  unchanged` and `test_task104_p2_cleanup.py::test_32_33_original_
  strategy_and_thresholds_unchanged` — their exact diff content (`git
  diff --stat` against a frozen reference commit) was inspected for the
  first time in this task and traced, via `git log`, to commit
  `4531fe2` (Task 118F), confirmed present BEFORE `58044a6` (the first
  commit of the entire Task 131 arc). `test_task117_release_rehearsal.py::
  test_bounded_release_rehearsal` and `test_task118a_dashboard_message_
  count.py::test_immediate_and_digest_sends_count_messages_correctly` —
  both fully isolated-fixture tests, consistent by exact name with every
  prior baseline this session.
- **4 confirmed environmental interference from this task's OWN live
  processes, not a code regression**: `test_task114_prospective.py::
  test_start_stack_omits_enable_broad_discovery_by_default`,
  `::test_start_stack_passes_enable_broad_discovery_through_to_the_v2_
  companion` (this task's own new tests — proven to pass cleanly in the
  pre-launch 224-passed run), plus `test_task117_execution_scope.py::
  test_prospective_start_stack_passes_the_deployment_flags` (an
  UNMODIFIED, pre-existing Task 117 test) and `test_task100a_
  authoritative_read_model.py::test_2_no_producer_yields_no_active_
  producer` — all 4 raised/asserted on the EXACT PIDs of this task's own
  live-launched stack (`ConcurrentStartError: ... pid 7928; pid 13288;
  pid 17080; pid 19984; pid 21332; pid 23456` for 3 of them; a real-
  process-detected `ZERO_ACTIVITY` instead of the test's assumed
  `NO_ACTIVE_PRODUCER` for the 4th). Reproduced identically on a
  targeted 4-test re-run (0.93s — not a repeated full-suite cycle).
  Full detail: `results/task132_development_run/DEVELOPMENT_RUN_
  REPORT.md`.
