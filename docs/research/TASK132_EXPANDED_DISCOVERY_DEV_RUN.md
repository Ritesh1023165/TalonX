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

## Addendum — Operational Closure (same day, same live run, same branch)

A follow-up directive on the SAME still-running development stack asked
for the historical observations above to be **refreshed against current
fact**, not restated. Full detail: `results/task132_development_run/
OPERATIONAL_CLOSURE_REPORT.md`. Summary of what changed:

### The real ingestion bottleneck, found and instrumented (not guessed)

The first expanded-scope poll cycle was still running after 2h45m+.
Direct inspection (not CPU/`Responding: True`) found two genuine,
distinct phases inside `EdgarPoller.poll_once()`, only the SECOND of
which is the actual bottleneck:

1. **Per-symbol SEC fetch loop** (`for rs in cycle_symbols`) — evidence
   (528/569 symbols with newly-ingested filings) shows this phase is far
   along or complete.
2. **Per-NEW-EVENT enrichment loop** (`for eid in result.new_event_ids:
   await self.enrichment.process_event(eid, ...)`) — runs strictly AFTER
   phase 1, ONE event at a time, each doing its own SEC EDGAR fetch(es)
   for filing comparison (+ XBRL, `enable_xbrl=True` by default). Direct
   count: of 27,598 new text-filing events discovered by this run, only
   ~2,986 (~11%) had been enriched after 2h45m — a real, demonstrated
   "expensive comparison/parsing" cost (Directive category, not network
   stall or reprocessing), at a rate that would take on the order of a
   day to fully drain at this scope multiple, not a "one-time cost" to
   hand-wave.

**Why both phases were externally invisible**: the service's only
progress signal (`service.heartbeat.json`) is written once per FULL
`poll_cycle()` (fetch + enrichment together) — for a first cycle this
large, that is a single write at start and none again for hours.

**Fix applied** (`talonx_ingest/intelligence/service/{poller,runner,
config}.py`): two new optional callbacks on `EdgarPoller.poll_once()` --
`progress_cb` (per symbol) and `enrich_progress_cb` (per enriched event)
-- both `None` by default (byte-identical no-op for every existing
caller). `IntelligenceService.poll_cycle()` wires both into a new,
throttled (`progress_write_min_interval_seconds`, default 10s)
`service.progress.json` snapshot distinguishing `phase: "polling"` /
`"enriching"` / `"done"`, elapsed time, and done/total counts for
whichever phase is active. 8 new focused tests
(`tests/test_service_poller.py`, `tests/test_service_runner_singleton.py`).

**Why this was NOT fixed by restarting with a bounded per-cycle window**:
directly queried — 24,958 of the 27,598 newly-ingested filing events
have a `text_events` row but NO `intel_event_processing` row yet (the
processing row is created lazily, only when enrichment actually reaches
that event). Since `ingest_symbol_filings` treats an already-persisted
filing as a duplicate (correctly — dedup must never regress), a restart
of the Intelligence component NOW would silently orphan those ~25,000
already-ingested events: the restarted cycle would never re-surface them
as "new", so they would never reach enrichment/significance/delivery at
all. **The current cycle must run to completion (or a proper resume/
sweep mechanism must exist) before any restart of this component** — the
progress-reporting fix above takes effect on the NEXT cycle, not this
one, by design. This is the single most important operational finding
of this task.

### Discovery-card delivery: real root cause, not a routing bug

`deliver_cycle()` (the ONLY call site for the informational-card drain)
runs strictly after `poll_cycle()` returns, inside `run_poll_loop`'s
single sequential loop body — confirmed directly from
`service.heartbeat.json` staying at `mode: "poll:start"` /
`last_cycle: None` for the entire observation window. Since `poll_cycle`
(fetch + enrichment) has not returned even once, `deliver_cycle()` has
never run even once. The originally-reported 10 cards were a small
sample of a much larger enqueue burst (2,414 rows at launch, now 2,950 —
growing as enrichment continues, all still `PENDING`); `SENT`/`EXPIRED`
are unchanged from before this run (last touched 2026-09-11) — direct
proof nothing has drained, nothing has been silently dropped, and no
card has been fabricated as delivered. Outcome: **waiting for a known
(if currently very slow) delivery schedule** — not suppressed, not
expired, not stranded by a missing consumer/setting. No delivery-path
code change was needed once this was understood; the real fix is
upstream (the enrichment bottleneck above).

### Scope reconciliation (569 vs 626)

- **Configured discovery universe**: 626 symbols (`discovery_universe_
  v1_626.json`, Task 131 Directive 6, static/versioned).
- **Resolved ingestion universe**: 569 — 626 minus 57 with no resolvable
  CIK in that manifest (`broad_discovery: 57/626 symbols unresolved`,
  logged, never silently dropped from observability).
- **Resolved execution (V2) universe**: 626 — the 39-name watchlist plus
  587 broad-discovery-only symbols; V2's own `execution_scope_enforced:
  true` / `execution_scope_out_of_scope_dropped_this_tick` counter
  (visible in `v2_service_status.json`, now surfaced on `/ping`) proves
  the allowlist is live-enforced, not advisory (16 dropped on the most
  recent tick observed).
- **Evaluation vs paper-entry-eligible**: unchanged from Task 131 — a
  symbol must have BOTH a resolved CIK (ingestion) AND pass V2's own
  liquidity/price mapping at entry time; `execution_scope_enforced`
  rejects anything outside the 626-name allowlist before an intent is
  ever created, so an ingestion-only (569-scope) name with no resolved
  execution-scope membership cannot reach a paper entry — verified by
  inspection, no code change required (no enforcement gap found).

### Full-suite gate (completed after commit `bb8478f`)

**4665 passed, 8 failed, 6 skipped** (53m47s) — the 8 failures are, by
exact name, the IDENTICAL set already documented above from the original
turn's own full-suite run against `aca1a4c` (4 pre-existing/unrelated; 4
environmental, the live stack's own real PIDs). Zero new failures.

### `/ping` extended (Directive section 5)

`talonx_dispatch/telegram_listener.py`: existing market/Quant sections
unchanged; new `_discovery_v2_section()` appends DISCOVERY / V2 /
DELIVERY, reading only already-existing snapshots (Intelligence's own
heartbeat + new progress file, the V2 companion's own status JSON, two
bounded `COUNT`/`GROUP BY`/`MAX` queries against the shared ledger, never
a full scan) — every field is "unknown" (never a fabricated 0) when its
source is unavailable. `_send_ping_reply()` reuses the delivery
pipeline's existing `MESSAGE_BUDGET` (Task 96F) to decide whether to
split into two Telegram messages, with a deterministic truncation
safety-net on each half. 13 new focused tests. One real, clearly-labelled
`[DEVELOPMENT TEST]` /ping was sent through the established destination,
standalone (not via the live supervised process, to avoid any restart)
— confirmed delivered (2/2 messages sent, no transport error).

## Addendum 2 — Task 133: Recoverable Ingestion and Timely Discovery Delivery

Full detail: `results/task132_development_run/TASK133_RECOVERABLE_
DELIVERY_REPORT.md`. Summary:

- **Recovery**: persisted-but-never-enriched events (the exact shape the
  addendum above found -- 24,958 orphans at the time) are now
  independently discoverable via two new, additive `ProcessingStateStore`
  queries (`find_undiscovered_events`, `next_for_processing`) and a new
  bounded `IntelligenceService.reconcile_and_enrich()` pass, reusing the
  existing state machine -- no new queue, no schema change. Proven with a
  genuine cross-process crash test (subprocess hard `os._exit` after
  persist, before enrich; a cold reopen of the same ledger file recovers
  and completes it).
- **Scheduling**: `poll_once()`'s inline enrichment and the new recovery
  pass are both bounded (count + time budget, per-event timeout);
  `deliver_cycle()` now gets a real turn every poll-loop iteration
  instead of waiting behind a potentially unbounded enrichment pass.
- **A genuine P0 found live, during the managed cutover, not staged**:
  `outbox.expire_stale()` (Task 96F/117, pre-existing) scanned every
  PENDING row with no LIMIT, doing one synchronous DB read per row when
  `deliver_cycle`'s `event_time_lookup` was given -- at ~4,000 PENDING
  rows that unbounded, `await`-free loop defeated `asyncio.wait_for`'s
  own timeout (a synchronous loop cannot yield for the timeout to
  preempt it), hanging the whole Intelligence process for several
  minutes. Fixed with a bounded, oldest-first `limit` (default unbounded
  preserved for every other caller/test).
- **Real result, not a transport test message**: after the fix and a
  second managed restart, one delivery cycle sent 20 real IMMEDIATE
  cards + 1 aggregated DIGEST message (21 real Telegram messages, IDs
  732-752) and correctly expired 600 genuinely stale backlog rows.
  `intelligence_delivery`: SENT 6 -> 46, EXPIRED 9,850 -> 10,450.
- **Scope/eligibility**, addressing the explicit "a counter is not
  identity proof" objection: traced the real entry path and found THREE
  independent guards, not just the execution allowlist -- (1) a sourcing
  gate (V2's Form4 feed is 100% derived from the CIK-driven ingestion
  pipeline, so an unresolved-CIK symbol can never produce a candidate at
  all), (2) the execution allowlist (symbol membership), (3) a real
  price-lookup guard at entry (`SKIPPED_NO_ENTRY_BAR` when no CSV bar
  exists for that symbol/session). No enforcement gap found.
- Two managed restarts of ONLY the Intelligence component (Original/
  Experimental/V2/Dashboard/checkpoint-daemon never touched); single-
  poller ownership verified after each; cash $300,000.00 / 0 positions /
  0 intents preserved throughout. 15 new focused tests, 204 passed
  across every directly-affected file, frozen fingerprint
  `11107198c5b81237` unchanged. Full-suite gate: **4,680 passed, 8
  failed, 6 skipped** (49m06s) at HEAD `309b845` -- the same 8 failures
  by exact name as Task 132's own baseline, zero new failures.

## Addendum 3 — Task 134: Fresh-Event Latency, Backlog Drainage and EOD Reconciliation

Full detail: `results/task132_development_run/TASK134_FRESH_LATENCY_
REPORT.md`. Summary:

- **No fresh SEC-published event existed in this observation window**
  (max `accepted_at_utc` across the whole ledger predates this run's own
  launch) -- reported as the limitation it is, not glossed over. Real
  LOCAL pipeline latency measured instead (25-sample, true wall-clock
  `intel_processing_log` timestamps, NOT the per-cycle-batch-fixed
  `ingested_at_utc`/`enqueued_at_utc` fields, which understated one
  sample's true latency by ~3.5 minutes -- itself a documented finding):
  enrichment ~0.2-0.3s once selected; queue-to-send 65-76s for this
  cycle's own inline work, up to ~17 minutes (bounded, never indefinite)
  for low-priority backfill-origin cards.
- **A second, genuine starvation defect found and fixed**: 296
  `intel_event_processing` rows (oldest discovered 10 days before this
  dev run started) were fully processed (`significance_state=DONE,
  delivery_state=DONE`) yet stuck at `stage=PARTIAL` (an `OPEN_STAGES`
  member) forever, because `EnrichmentEngine._rollup_stage` never
  special-cased `delivery_state==DONE` when the comparison sub-state was
  a PERMANENT data-quality PARTIAL flag -- re-selected and re-run (a
  real SEC comparison fetch) every single cycle with no progress and no
  backoff. Fixed (delivery_state==DONE now always closes the row;
  comparison_state itself stays observable); verified live after a
  third managed Intelligence-only restart -- the specifically tracked
  row resolved to COMPLETE, 20/296 affected rows resolved in the first
  post-restart cycle, the rest draining gradually at the same bounded
  per-cycle rate as everything else in this pipeline.
- Cards-to-Telegram-message mapping confirmed by CODE inspection (claim-
  before-send, mark-SENT-only-on-success, for both IMMEDIATE and DIGEST)
  as well as live data (2 DIGEST messages aggregating 26 cards; 9
  IMMEDIATE cards = 9 messages); both AMBIGUOUS rows re-checked still
  correctly un-retried.
- V2: zero entries this session, evidence-based (the insider-transaction
  candidate pool, `form4_records_seen`, has been static all session --
  not a pipeline defect, not loosened).
- Discovered (not previously documented): the live long-polling dispatch
  process has never actually loaded the Task 132 `/ping` extension --
  every `/ping` demonstration so far used a standalone script for
  exactly this reason; Original is healthy and was correctly NOT
  restarted just to pick it up.
- EOD mechanism inspected (not invoked -- still NOT_DUE_YET): `close`
  defaults to a full stack shutdown; `--no-shutdown` is the existing,
  correct option to preserve overnight ingestion given a real backlog
  remains.
- Cash $300,000.00 / 0 positions / 0 intents preserved throughout; one
  managed Intelligence-only restart; 3 new tests, 131 passed across
  every directly-affected file (full suite not repeated -- already run
  once for Task 133's larger change-set); frozen fingerprint
  `11107198c5b81237` unchanged.

## Addendum 4 — Task 135: Quant -> Brain Handoff Discrepancy

Full detail: `results/task132_development_run/TASK135_QUANT_BRAIN_
HANDOFF_REPORT.md`. Summary:

- Investigated /ping's Quant candidates=68 / published=1 / Brain
  received=0. Original (Quant/Brain/Core/Dispatch, all asyncio tasks in
  one `run_talonx.py` process) had never been restarted all session --
  confirmed via `git diff aca1a4c HEAD` that nothing in this whole
  Task131-135 arc touched that pipeline's code, so the discrepancy
  predates this work.
- **Root cause: a genuine, one-shot fire-and-forget Redis Pub/Sub
  delivery gap, not a config mismatch, crash, or counter bug.** Brain's
  subscription was proven alive and stable all day (no reconnects,
  actively processed a message on a sibling channel at 16:55) yet has
  zero log activity for `signals_channel`; Quant's publish genuinely
  succeeded (real same-day counter increment, fresh TTL). "published"
  has only ever meant "Redis accepted the command", never "a consumer
  received it" -- an evidence gap (the expected post-publish log line is
  itself absent from the whole multi-day log) is reported as such, not
  reconstructed.
- **Fix (bounded, no rewrite)**: capture Redis PUBLISH's own return
  value (subscriber count) instead of discarding it --
  `talonx_quant/consumer.py::_publish_signal` now logs a WARNING and
  increments a new `quant:published_no_subscriber` metric whenever a
  signal is accepted with zero live subscribers; `/ping`'s existing
  Quant section surfaces it when nonzero. 3 new tests reproduce the
  exact discovered gap (silent before, visible after) without changing
  the underlying accept/reject decision.
- Original restarted (first time all session) to load the fix -- the
  smallest component set able to (Quant/Brain/Core/Dispatch/the real
  Telegram listener are all inside it); Intelligence untouched. Verified
  by commit-vs-restart-time correlation that the loaded code is the
  fixed version, and that the real (not standalone-script) `/ping`
  listener is alive and polling -- explicitly NOT claiming a literal
  `/ping` round-trip was proven, since simulating an inbound Telegram
  message from outside the user's own account isn't possible here.
- Cash $300,000.00 / 0 positions / 0 intents preserved; SEC discovery/V2
  lane (Intelligence, PID unchanged since Task 134) untouched. 313 tests
  passed, zero regressions, frozen fingerprint `11107198c5b81237`
  unchanged. EOD still PENDING at report time (~2h before close);
  `--no-shutdown` remains the correct existing option.

## Addendum 5 — Task 136A: Stop Historical-Alert Noise and Reconcile Alert Content

Full detail: `results/task132_development_run/TASK136A_HISTORICAL_
ALERT_NOISE_REPORT.md`. Summary:

- User-reported incident: 4 real ACN Form 4s from May/July 2024
  (accessions ...175/176/205/206) delivered as live Telegram alerts on
  2026-09-14 (message IDs 934-937). Full scope, traced: 183 pre-2026
  cards sent today across ~150 messages -- happened during Task 133/134's
  delivery-fix verification, when the newly-unblocked queue drained
  without a send-time age gate catching them. SENT history left
  unchanged (not authorized to alter it).
- **Root cause 1 (why historical cards were sent)**: `outbox.pending()`
  orders by BAND PRIORITY first, `expire_stale()`'s bounded sweep orders
  by enqueue time only -- a HIGH-band historical card enqueued late
  (beyond the sweep's bound) can be selected for sending before the
  sweep ever reaches it. Fixed with a new `expire_one_if_stale()` gate
  applied immediately before every send (both IMMEDIATE and DIGEST),
  using the identical freshness-basis logic as the bulk sweep so the two
  paths cannot disagree. Reproduced the exact race in isolation, then
  shown fixed.
- **Root cause 2 (the $2,244,878 vs $12k / "4 sellers" vs "1 sale"
  reconciliation)**: `build_insider_activity()` always computed rolling
  windows "as of the most recent known activity" (effectively today),
  never the historical filing's OWN date -- blending current issuer-wide
  aggregates into a 2024 card's "why surfaced" without disclosure. Fixed
  by passing `as_of_date` derived from the event's own `accepted_at_utc`.
  Every figure on the ACN cards was individually correct for its own
  (undisclosed) window; the fix makes all windows consistently anchored
  to the filing's own date instead of today.
- 6 new tests (band-priority race reproduced/fixed; as_of_date verified
  against a real 2024 event), 184 passed, zero regressions, frozen
  fingerprint unchanged. Intelligence restarted (only component needing
  the fix); live post-cutover: the entire 206-row PENDING backlog at
  restart time correctly resolved to EXPIRED (0 sent) -- containment
  confirmed, though no natural fresh-card delivery example fell in this
  exact window (reported as that limitation, not manufactured).
- Cash/positions/intents unchanged; SEC ingestion/recovery and V2
  actionable delivery untouched. EOD still PENDING at report time.

## Addendum 6 — Task 136B: Close Freshness Edge Cases and Correct Acceptance Evidence

Full detail: `results/task132_development_run/TASK136B_FRESHNESS_EDGE_
CASES_REPORT.md` + `TASK136A_CORRECTIONS_ADDENDUM.md`. Summary:

- Two remaining Task 136A gaps, confirmed by the user's own review and
  closed: (1) an event whose publication time could not be established
  still qualified via a silent fallback to enqueue time; (2)
  `process_pending`'s per-row freshness check reused the single
  drain-level `now`, not a fresh clock read at each row's own send
  decision, so a card could cross its cutoff mid-batch and still pass.
- **Fix 1**: `_expire_row_if_stale` now returns a 4-way `_FreshnessOutcome`
  (OK / EXPIRED / UNQUALIFIED / DEFER) instead of `str | None`.
  UNQUALIFIED (a lookup ran and found nothing, or found an invalid
  timestamp) moves the row to SUPPRESSED with a truthful reason, never
  EXPIRED (no age was ever established) and never silently OK. DEFER (the
  lookup itself raised) leaves the row completely untouched for a bounded
  retry. Naive/future source timestamps explicitly rejected
  (`_validate_source_time`).
- **Fix 2**: `process_pending`/`process_digest`/`deliver_cycle` gain an
  injectable `clock` parameter, read fresh at each row's (or, for a
  digest, the whole batch's) final send decision -- defaults to reusing
  `now` when a caller pins it (test determinism preserved) or a real
  `datetime.now(timezone.utc)` read in production. A DIGEST batch is
  re-validated as one unit immediately before it is actually sent;
  ineligible cards are excluded and never marked SENT; an empty-eligible
  digest sends nothing at all.
- **Content correction**: traced the ACN incident's four disclosed
  figures precisely -- the "Why surfaced" reasons (significance engine)
  were ALREADY event-relative before Task 136A; only the "What changed"
  section's insider facts (a separate enrichment-engine build) used the
  wrong as-of basis. Task 136A's report and its own code docstring both
  overstated this as affecting every figure; both corrected.
- **BST/UTC correction**: `Get-CimInstance`'s `CreationDate` and raw log
  prefixes are host-local time (BST, UTC+1 in September), not UTC, as
  treated throughout Tasks 132-136A -- proven by direct comparison against
  each event's own embedded `_utc` field. Task 136A's "19:39:38 UTC"
  restart timestamp corrected to 18:39:38 UTC.
- **206 vs 229 reconciled**: 206 = a PENDING snapshot total; 229 = the
  interval count the first live cycle's route-UNFILTERED bulk
  `expire_stale()` sweep actually transitioned (verified in source: no
  `route` filter on that query) -- structurally can, and likely does,
  include some DIGEST-route rows the IMMEDIATE-labelled snapshot did not
  count, not a discrepancy in the underlying fix.
- 12 new regression tests (isolated queues + an injected `_StepClock`,
  never real wall time) plus 3 existing test files updated for the
  corrected semantics (a "no evidence" lookup result is UNQUALIFIED, not
  a silent enqueue-time pass). 558 tests passed; 3 pre-existing,
  unrelated failures reconfirmed present on unmodified HEAD via
  `git stash` (environmental/date-dependent, not caused by this change).
  Frozen fingerprint `11107198c5b81237` unchanged.
- Intelligence restarted (only component touched) via the supervisor's
  own dead-child detection; clean startup, unchanged 569-symbol scope,
  continued backfill with no gap, single supervisor ownership preserved.
  Cash $300,000.00 / 0 positions / 0 intents unchanged throughout. V2
  companion untouched. EOD still PENDING at report time (before 20:00 UTC
  close); `close --no-shutdown` remains the correct mechanism, owned by
  the running checkpoint daemon.
