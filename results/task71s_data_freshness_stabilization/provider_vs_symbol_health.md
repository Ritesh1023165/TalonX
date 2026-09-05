# Provider Health vs. Symbol Freshness -- Task 71S

## Why these must be two independent dimensions

The 2026-08-26 session's own data makes the case on its own: **8 of the 15
DATA_NOT_READY symbols shared the identical missing ET clock-minute** (e.g.
09:33 ET was missing for REGN, GILD, TXN, PEP, PANW, COST -- six symbols at
once), purely by coincidence of independent thin IEX printing (see
`missing_opening_minutes.csv` / `gap_classification_evidence.csv` -- every
one of these is `CONFIRMED_NO_IEX_TRADE`, verified against Alpaca's own
historical archive). If "many symbols stale in the same tick" were treated
as evidence of a provider-wide outage, this ordinary, healthy session would
have raised a **false PROVIDER_UNAVAILABLE alarm at almost every single
minute of the 09:30-09:59 opening window** (every minute in that window had
between 1 and 8 of the 15 tracked symbols missing it -- see the earlier
per-minute distribution in this task's forensic notes). That would have
been actively misleading: the feed itself was never unavailable that day
(zero non-200/exception failures were ever observed on the main
`fetch_bars_latest` poll path; the ONE real connectivity failure that day
was an isolated, already-correctly-classified premarket-radar snapshot
timeout on a wholly separate, non-decision-path endpoint).

## The design this task implements

`talonx_piv/freshness.py`'s `FreshnessTracker` keeps two **completely
independent** state dimensions:

1. **Per-symbol freshness** (`FRESH` / `STALE` / `RECOVERED` / `DATA_GAP` /
   `UNKNOWN`) -- driven purely by "has THIS symbol produced a new bar
   recently," exactly as `_check_stale` already computed before this task
   (unchanged gap/threshold logic).
2. **Provider health** (`HEALTHY` / `DEGRADED` / `PROVIDER_UNAVAILABLE`) --
   driven **only** by whether the single batched `fetch_bars_latest()` HTTP
   call itself succeeded (status 200) or failed (raised, or non-200) THIS
   tick. One isolated failure is `DEGRADED`; two or more CONSECUTIVE
   failures escalate to `PROVIDER_UNAVAILABLE`. This is never inferred from
   how many symbols are individually stale.

This means: 16 symbols independently going stale at different points
across the day, for reasons entirely explained by real market sparsity,
correctly leaves `provider_state == HEALTHY` throughout (see
`test_one_stale_symbol_does_not_mark_provider_unavailable` /
`test_provider_wide_interruption_marks_provider_health_correctly` in
`tests/test_task71s_data_freshness_stabilization.py`) -- while a genuine
fetch-level failure (the kind that actually crashed the process 34 minutes
into an earlier session, per the pre-existing `b935588` commit) is now
directly, immediately classified as `DEGRADED`/`PROVIDER_UNAVAILABLE`
rather than only being inferable, minutes later, from a pile-up of
per-symbol staleness.

## What actually happened on 2026-08-26, classified under this design

- **Provider health:** `HEALTHY` for the entire regular session on the main
  decision-path poll. Zero fetch-level failures were recorded on
  `fetch_bars_latest`.
- **One isolated, separate degradation:** the premarket radar's own
  `/v2/stocks/snapshots` call hit a `ConnectTimeout` once, at 10:51:16 UTC
  (06:51 ET -- inside the retry-window premarket period). This is a
  DIFFERENT endpoint/code path from the main poll (see
  `premarket_radar.py`'s own module docstring: "never touches
  lifecycle/broker") and was already correctly isolated and classified
  (`RADAR_TICK_SKIPPED`, non-fatal, one tick skipped, loop continued). It
  has no bearing on symbol freshness or the decision path.
- **Per-symbol freshness:** 16 symbols went `STALE` a total of 72 times,
  every one of them `CONFIRMED_NO_IEX_TRADE` against the historical
  archive (see `stale_event_timeline.csv`), and every one of them
  automatically recovered before the 15:50 ET EOD flatten (see
  `recovery_evidence.json`).

## Symbol-level degradation never falsely marked the feed disconnected

Under the OLD code's single combined `feed_health` string
(`"DEGRADED (N stale)"` whenever `_stale_flagged` was non-empty), the
`/ping` status would have shown "DEGRADED" for large parts of the session
purely from ordinary per-symbol sparsity -- technically accurate as a
"count of currently-stale symbols" but easily misread as "the feed is
unhealthy." This task does not remove that existing string (kept
byte-for-byte, since `talonx_dispatch`'s `_pipeline_status` already reads
it verbatim in a cross-module contract -- see
`tests/test_task69q_evidence_upgrade.py`), but adds a SEPARATE
`piv_info["provider_health"]` field carrying the new, independent
provider-only classification, so an operator (or a future dashboard) can
now distinguish "N symbols are individually quiet right now" from "the
market-data provider itself is unreachable" at a glance.
