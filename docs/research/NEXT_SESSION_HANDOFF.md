# Next-session handoff (prepared 2026-09-11, ~16:22 UTC)

**Do not auto-start the next session — this is a handoff document, not a
scheduler.**

## Candidate release for the next session

- **SHA**: `5c0b3f3ccfef45ff8438e75f8f614b738deefc9a` (release branch
  `research/talonx-strategy-validation`) — the currently-running,
  live-accepted revision.
- **Effective configuration**: V2 fingerprint `11107198c5b81237`, 39-name
  `resolved-active-watchlist` execution scope, 45-day lookback,
  `composite-yf` pricing, official V2/Intelligence Telegram delivery
  enabled, Experimental external delivery OFF, `--tick-seconds 150
  --heartbeat-seconds 30`.
- **Env vars required before `start`** (unchanged since Task 117):
  `TALONX_INTEL_DELIVER_CARDS=1`, `TALONX_INTEL_DRY_RUN_DELIVERY=0`,
  `TALONX_INTEL_DELIVER_PER_CYCLE=20`,
  `TALONX_INTEL_DELIVER_TIMEOUT_SECONDS=20`,
  `TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS=21600`,
  `TALONX_INTEL_DELIVER_AGE_CUTOFF=1`.

## Warmup recovery — observable acceptance criteria for the next startup

Expect, in `original.log`, shortly after `Initial Quant preseed complete:
N/43 symbol(s) ready`:
```
Bounded preseed recovery sweep complete: R/M previously not-ready
symbol(s) recovered in Xs (still incomplete: [...])
```
This fires **only** if `N < 43` at startup. Any still-incomplete symbol
after the sweep is expected to close via ordinary live accumulation
within the session (today: ~4 bars / a few minutes for the one remaining
case). **This is a bounded, once-per-startup sweep — not continuous
mid-session recovery.** If a bulk provider failure recurs mid-session
(not at startup), no automatic recovery exists for it; that remains a
known, undecided-scope gap for a future task, not silently claimed as
covered.

## Known data limitations / unresolved findings (carried forward, not re-litigated)

- Task 118C's heartbeat-lapse locus (exact producer-write-vs-reader-read
  cause of the one 14:29:18Z DISCONNECTED reading) — unresolved.
- The historical "45 candidates" counter's exact source query — unresolved.
- SHOP has no local daily-bar price coverage in the frozen research
  dataset (unrelated to live trading; a research-replay-only gap).

## Open positions / pending notifications / next lifecycle actions

- **V2**: 0 open positions, $300,000 cash, no pending entry/exit
  obligations. ABCL episode `07242bc857569f60` remains `SKIPPED_ENTRY_STALE`
  (terminal, no action needed).
- **Experimental**: **SPCX open** (16.86596 sh, entry $148.2276, stop
  $144.6133, target $152.0633) — carries over to the next session under
  its existing stop/target/gap policy; no manual action required or
  authorized.
- **Intelligence**: no pending PENDING-state cards at last check
  (`PENDING: 0`); nothing outstanding.
- **Immediate required operator action** (today, not next-session): run
  `python -m talonx_ops.prospective close` at/after
  **2026-09-11T20:00:00Z**, complete by **2026-09-11T21:30:00Z** — see
  `TASK118G_FINAL_ACCEPTANCE.md` for the pre-close acceptance evidence
  this handoff is based on.

## Next market session

**Monday 2026-09-14** (verified via `talonx_v2.calendar.is_session` —
2026-09-12/13 are a Saturday/Sunday, correctly non-sessions).

## One next research action

**Same as Task 118E/F's `ONE_TESTABLE_HYPOTHESIS` / `EXPLORATORY_ASSOCIATION_SUPPORTS_ONE_FURTHER_TEST`**
— unchanged, not re-opened or re-optimized in this task: track pre-entry
realized volatility for every new **live** 39-name-scope entry going
forward, and once N≥10 new live entries accumulate, test (within-scope
only) whether higher-volatility entries realize worse net returns,
matching the already-published protocol in
`docs/research/TASK118F_VOLATILITY_RETURN_TEST.md`. **New information
this provides**: the only genuinely unused data available to this
programme — every other analysis this session (A/B/C comparison,
composition check, volatility-return test) reused the same already-
inspected 2024–2026 history. No further backtest or historical re-slice
is proposed as a substitute.
