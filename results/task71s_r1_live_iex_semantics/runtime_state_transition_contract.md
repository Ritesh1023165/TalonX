# Runtime State-Transition Contract -- Before / After Task 71S-R1

## Symbol-level freshness states (`talonx_piv/freshness.py`)

| State | Meaning | Stored (persists across ticks)? | Emits an event? |
|---|---|---|---|
| `FRESH` | A new bar has been observed and the gap since is within `stale_seconds`. | Yes | No |
| `NO_NEW_IEX_BAR` *(new)* | This specific tick's poll succeeded but produced no new bar for this symbol, and the gap is still within `stale_seconds` -- entirely ordinary. | **No** -- transient, per-tick classification only; only increments a rolling counter. | **Never.** |
| `STALE` | Gap since last new bar exceeds `stale_seconds`. | Yes | `STALE_DATA` (once per episode) + *(new)* `DATA_NOT_READY reason=INSUFFICIENT_RECENT_IEX_PRINTS:{symbol} status=EXCLUDED_FROM_DECISION_PATH` (once per episode, same transition) |
| `RECOVERED` | Transient: returned only on the exact STALE/DATA_GAP -> fresh transition tick. | No (settles to `FRESH` immediately) | `DATA_RECOVERED` |
| `DATA_GAP` | Still `STALE` at session end -- never recovered that day. | Yes (persists in the end-of-session report) | `BROKER_ERROR reason=STALE_DATA_UNRESOLVED_AT_SESSION_END status=DATA_GAP` |
| `UNKNOWN` | Never observed at all this session. | Default (not stored) | None |

## Provider-level health states (independent dimension, unchanged by this task)

| State | Meaning | Driven by |
|---|---|---|
| `HEALTHY` | Last market-data fetch succeeded (HTTP 200). | `fetch_bars_latest`'s own directly-observed success/failure -- **never** inferred from symbol stale-count. |
| `DEGRADED` | One fetch failure (raised or non-200). | Same. |
| `PROVIDER_UNAVAILABLE` | Two or more CONSECUTIVE fetch failures. | Same. |

Emits `PROVIDER_RECOVERED` (HEALTHY transition) or `BROKER_ERROR
reason=MARKET_DATA_FETCH_FAILED status={DEGRADED|PROVIDER_UNAVAILABLE}`
(non-HEALTHY transition) -- unchanged from Task 71S.

## Before Task 71S-R1

- `_check_stale` only checked symbols currently in `_ready_symbols`
  (`None` = all, pre-finalization; a fixed set post-finalization). A
  symbol excluded at 09:59:59 ET (e.g. REGN, `DATA_NOT_READY`) was
  **invisible to staleness monitoring for the rest of the day** -- REGN's
  real 40 regular-session gaps produced only 5 observed/reported
  STALE_DATA events (the ones before 10:00 ET); the other ~35 never
  happened as far as the event ledger could show.
- No rolling per-symbol coverage was tracked anywhere.
- "No new bar this tick" and "genuinely broken" were both silently absent
  from any explicit vocabulary -- the only signal was the eventual
  `STALE_DATA` flag itself, which read (before Phase A's correction) as if
  it might indicate a problem, with no accompanying decision-relevant
  reason code.
- `freshness_report.json` carried only `provider_state` and a bare
  `symbols` state map -- no session/date/build identity.

## After Task 71S-R1

- `_check_stale` monitors **every** universe symbol that has ever produced
  a bar this session, regardless of `_ready_symbols` membership.
  Decision-ELIGIBILITY is completely unaffected (still gated by the same,
  unmodified `_ready_symbols`/`warmup_ready_symbols` intersection) -- only
  OBSERVATIONAL monitoring is widened.
- A quiet-but-healthy tick is explicitly classified `NO_NEW_IEX_BAR`
  (never an event; a rolling counter only) -- and never mislabeled as an
  error.
- The moment a symbol crosses the SAME, unchanged 120s (or configured)
  threshold, it now emits BOTH the existing `STALE_DATA` (raw feed
  observability, unchanged wording) AND a new `DATA_NOT_READY
  reason=INSUFFICIENT_RECENT_IEX_PRINTS:{symbol}
  status=EXCLUDED_FROM_DECISION_PATH` -- reusing the established,
  decision-relevant vocabulary (the same event type readiness.py's own
  opening-window gate already uses) instead of only a raw-sounding
  "STALE" warning.
- `FreshnessTracker` tracks rolling `fresh_bar_count` /
  `quiet_tick_count` / `stale_episode_count` per symbol, exposing a live
  `coverage_ratio` -- reported, never used to invent a new auto-exclusion
  threshold (see the R1 summary's threshold-reasoning section).
- `freshness_report.json` is now stamped with `session_id`,
  `trading_date_et`, `runtime_sha`, `config_hash` (best-effort, read from
  the already-written `session_identity.json` -- matching the exact
  pattern `cli.py`'s own `eod` command already uses).
- No configured universe symbol is ever silently dropped from the report
  -- a symbol with zero activity all day still appears in `config.universe`
  and would appear in the freshness snapshot the moment it's ever checked.

## What did NOT change

- The `120`-second `stale_seconds` threshold value itself (Task 71S's own
  `threshold_analysis.md` conclusion stands; no new evidence in this task
  justifies a different number -- see Phase B's own explicit
  no-invented-threshold constraint).
- `_stale_flagged`'s dedup contract and the exact `STALE_DATA` event
  wording (`reason=f"no new bar for >{stale_seconds}s"`) -- byte-for-byte
  preserved, still covered by the pre-existing regression test
  `test_stale_data_flagged_once_when_no_new_bar_arrives`.
- The `feed_health` string contract (`talonx_dispatch`'s
  `_pipeline_status` cross-module dependency) -- untouched.
- Any `talonx_quant` file, any order/broker call, any strategy threshold.
