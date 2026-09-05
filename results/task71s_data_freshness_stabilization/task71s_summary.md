# Task 71S -- PIV Stabilisation Phase 2: Missing-Minute and Stale-Data Semantics

**Mode:** PAPER / NO REAL CAPITAL. No order was submitted, no
broker-trading endpoint was called, and no live PIV trading session was
started at any point in this task. All Alpaca calls made by this task were
read-only historical-bars GETs (`feed=iex`), reproducing the exact feed the
live system already uses for the same purpose.

## Task 70S integration audit (Phase A) -- verdict: NOT BLOCKED

See `task70s_runtime_diff_audit.md` for the full walkthrough. Summary:
Task 70S's `636fa9c..54ae8ff` diff is confined to historical
1-minute-warmup provider selection (`talonx_piv/{warmup,decision_engine,
cli,alpaca_historical_warmup}.py`); the readiness/ready-flag computation
block in `warmup.py` has zero added/removed lines, `decision_engine.py`'s
`on_bars` (the only method touching candidate generation/signal
publication) is untouched, and no `talonx_quant` file appears in the diff
at all. The 35/35 live-verified result was independently re-confirmed to
use bars strictly before its declared causal cutoff (`future_bars_dropped
== 0` for all 35 symbols).

## Root causes of the 72 stale events (Phase B)

**All 72/72 are `CONFIRMED_NO_IEX_TRADE`** -- genuine, per-symbol,
per-minute absence of any IEX-reported trade, independently verified
against Alpaca's own historical IEX 1-minute archive (the same feed the
live poll uses). For 71 of the 72, the historical archive shows the last
real bar exactly 3 minutes before the flag instant (a clean, consistent
signature: a bar prints, then two full minutes pass with nothing, crossing
the 120-second/2-poll-cycle threshold on the third). The remaining one
(REGN's very first stale event of the day, 09:32 ET) simply has no prior
bar to find because it was the first two minutes of the session -- also
correctly classified `CONFIRMED_NO_IEX_TRADE`. Zero events were found to
be a live-ingestion defect, a missed poll, or a subscription/pipeline gap.
See `stale_event_timeline.csv`.

The isolated `BROKER_ERROR reason=PREMARKET_RADAR_FETCH_FAILED_ConnectTimeout`
(10:51:16 UTC) is unrelated to the 72 STALE_DATA events: it is a single,
already-correctly-isolated failure on the premarket radar's OWN,
observational-only `/v2/stocks/snapshots` endpoint (a different code path
that never touches the decision path, per `premarket_radar.py`'s own
module docstring), and it does not appear in the main `fetch_bars_latest`
poll's own error surface at all (which had zero failures the entire day).

**Important architectural correction to the task's own framing:** this
codebase's live feed is a per-symbol-batched **REST poll**
(`fetch_bars_latest`, every `poll_interval_seconds`=60s) against Alpaca's
`/v2/stocks/bars/latest`, not a WebSocket subscription. "A missed WebSocket
bar" / "a broken subscription" (as literal sockets) do not map onto this
architecture; the closest real analogues are "a missed poll cycle" and "a
gap in the batched poll response," both of which this task's evidence
rules out for 2026-08-26 (zero fetch-level failures were recorded on the
main poll all day).

## Missing-minute classifications (Phase B)

**All 121/121 missing opening minutes (across the 15 `DATA_NOT_READY`
symbols) are `CONFIRMED_NO_IEX_TRADE`**, with zero disagreements against
the historical archive. See `missing_opening_minutes.csv` and
`gap_classification_evidence.csv`. A striking but fully-explained pattern:
individual minutes were frequently missing for MANY different symbols at
once purely by coincidence (e.g. 8 of 15 symbols simultaneously missing
09:33 ET) -- this is why provider-wide inference from symbol-count alone
would be unsound (see `provider_vs_symbol_health.md`).

## REGN conclusion (Phase B item 8)

REGN's 21 missing opening minutes and its 5 STALE_DATA events that day are
**legitimate IEX print sparsity, not an ingestion defect** -- REGN's own
historical 1-minute archive for the full regular session shows only
70/390 minutes with any bar at all (vs. 375-390 for the most liquid
symbols in the universe, and 30/30 for AAPL in the opening window alone).
REGN is simply a thin-IEX-print name on this specific venue; its gaps are
real market characteristics, independently confirmed minute-for-minute
against Alpaca's own archive, not a bug.

## Files changed

- `talonx_piv/freshness.py` (new) -- `FreshnessTracker`: symbol freshness
  (FRESH/STALE/RECOVERED/DATA_GAP/UNKNOWN) and provider health
  (HEALTHY/DEGRADED/PROVIDER_UNAVAILABLE) state machine, gap-driven (no
  duplicated timestamp bookkeeping -- reads the SAME facts
  `session_runner.py` already computes).
- `talonx_piv/gap_forensics.py` (new) -- read-only, evidence-based
  classifier (CONFIRMED_NO_IEX_TRADE / LIVE_STREAM_BAR_MISSED /
  SUBSCRIPTION_OR_PIPELINE_GAP / PROVIDER_WIDE_INTERRUPTION /
  LOCAL_PROCESSING_DELAY / HISTORICAL_DATA_DISAGREEMENT / UNKNOWN), reusing
  `alpaca_historical_warmup.py`'s existing request/parse helpers. This is
  the exact methodology used to produce every classification in this
  task's own artifacts.
- `talonx_piv/session_runner.py` -- `fetch_bars_latest` now catches its own
  transport exception (previously uncaught at this level; the outer
  per-tick try/except from commit `b935588` remains the last-resort net)
  and records an explicit `_last_fetch_ok` side-channel; `process_tick`
  feeds this into `FreshnessTracker.record_provider_fetch_result`, emits
  `PROVIDER_RECOVERED`/`BROKER_ERROR` on a provider-state transition, calls
  `observe_fresh`/emits `DATA_RECOVERED` on a symbol's stale->fresh
  recovery, adds an explicit STALE/DATA_GAP exclusion to
  `decision_eligible`, resets `_freshness` on a new ET session date, and
  writes a new `freshness_report.json` (+ graduates any still-STALE symbol
  to `DATA_GAP` with a `BROKER_ERROR status=DATA_GAP` event) at session
  end. `_check_stale`'s existing `_stale_flagged` dedup and event/format
  strings are UNCHANGED (only kept in sync with the new tracker).
- `talonx_piv/events.py` -- two new whitelisted event types
  (`DATA_RECOVERED`, `PROVIDER_RECOVERED`), both classified
  `notification_class="SYSTEM"`.
- `tests/test_task71s_data_freshness_stabilization.py` (new) -- 29 tests.

No file in `talonx_quant/{strategy,indicators,consumer,config}.py` was
opened for editing. No order/broker-trading endpoint is reachable from any
new code path (every fake transport in the new tests raises
`AssertionError` on `.post()`/`.delete()`).

## Behaviour before versus after

**Before:** a symbol going quiet for >120s emitted one `STALE_DATA` event
(deduplicated) and silently cleared when a bar returned -- no distinction
between "confirmed market sparsity" and "something is actually broken," no
recovery event, no provider-vs-symbol health separation, and a fetch-level
exception inside `fetch_bars_latest` would skip the entire tick (via the
outer `run()` handler) rather than being classified.

**After:** the exact same `STALE_DATA` dedup/event/threshold behavior is
preserved byte-for-byte (see `test_stale_data_flagged_once_when_no_new_bar_arrives`,
still passing unmodified), PLUS: a `DATA_RECOVERED` event on genuine
recovery, a separate `provider_health` field/state machine that cannot be
falsely tripped by ordinary per-symbol sparsity, an explicit (if
currently-redundant-by-construction) guard preventing a STALE/DATA_GAP
symbol from ever reaching the decision path, a `freshness_report.json`
evidence artifact, and a reusable, tested, read-only historical classifier
for retrospective gap analysis.

## Tests and exact results

See `regression_test_results.txt` for the full run. Summary: 29/29 new
Task 71S tests pass; all directly-related pre-existing PIV/warmup/readiness
suites (180 tests across 11 files, including Task 70S's own 26) pass
unchanged; full-repository suite result compared honestly against the
known `test_run_historical_regimes.py` baseline failure (see that file for
the exact comparison).

## Confirmation that stale data cannot reach signals/orders

See `recovery_evidence.json`'s dedicated section: a symbol only ever
appears in a tick's `new_bars` when a genuinely new bar just arrived (the
same tick recovery is detected), `decision_eligible` now ALSO explicitly
excludes STALE/DATA_GAP symbols, and this task's own cross-reference of
2026-08-26's `quant_funnel_report.json` confirms none of the day's 3,925
evaluated candidates originated from any of the 15 DATA_NOT_READY symbols.
Of the 16 symbols that went stale at least once, 6 (ADBE, AMAT, AMD, AMZN,
CMCSA, PYPL) were otherwise session-readiness-READY -- these are exactly
the symbols this task's new explicit guard specifically protects (not
merely a redundant restatement of pre-existing behavior for them).

## Limitations and unresolved unknowns

- This task's forensic classification is retrospective (run after the
  fact, using real historical data); it is not wired into the live `eod`
  path automatically (see `remaining_stabilization_issues.md` item 2) --
  a deliberate "smallest safe correction" scope decision, not an oversight.
- `FreshnessTracker` state is in-memory only, matching the pre-existing
  `_stale_flagged`/`_last_seen_wall` posture -- a process restart mid-session
  does not currently restore prior freshness state (item 4).
- Zero real `PROVIDER_WIDE_INTERRUPTION` examples exist in this day's data
  to validate that escalation path against (item 3) -- unit-tested with
  synthetic data only.

## Remaining stabilisation phases

See `remaining_stabilization_issues.md` for the full, carried-forward list
(dashboard/EOD surfacing, live-wired gap classification, cross-process
persistence, orchestration, alerts/shadow ledger, complete PAPER
end-to-end re-verification, and the still-open `REQUIRED_1M_BARS`/
`min_bars_required` decoupling from Task 70S).

## Branch, starting/final SHA

- Branch: `research/talonx-strategy-validation`
- Starting HEAD: `54ae8ff`
- Final HEAD: see the final chat report for the actual commit SHA (written
  after this file, once the full regression run is captured in
  `regression_test_results.txt` and the git-instructions gate is applied).

## Commit/push status; Final verdict

See the final chat-message report.
