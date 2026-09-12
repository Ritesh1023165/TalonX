# Next-session handoff (finalized 2026-09-11, updated 2026-09-12 / Task119A+120)

**Do not launch the next session automatically — this is a handoff
document, not a scheduler. No GO is declared here; GO/NO-GO is a
preflight-time decision at next start.**

> **2026-09-12 update (Task119A/120)**: the candidate SHA changed from
> `5c0b3f3` to `f289869` — a dashboard-only integration (Task 119 +
> Task 119A's corrections: one Paper/EOD destination, truthful cost
> labels, a real exchange-calendar session boundary). **No strategy,
> threshold, scope, sizing, holding-period, or V2 fingerprint change** —
> verified: `talonx_v2/` and the fingerprint-defining module have a
> literal zero-line diff between `5c0b3f3` and `f289869`. This candidate
> has NOT been runtime-validated live (no application session was started
> this task) — the go/no-go conditions below still govern, unchanged in
> substance, just against the new SHA.

## Candidate release for the next session

- **SHA**: `f28986999eec5e313cfc89db24e4dbacfb378891` (`f289869`) — integrates Task 119 (`d65a410`) +
  Task 119A's corrections on top. Strategy-code-identical to `5c0b3f3`
  (Task 118F's deployment); only `dashboard_web.py`,
  `dashboard_web_static/index.html`, `talonx_ops/dashboard_read.py`,
  `talonx_ops/paper_performance.py` (new), and
  `talonx_signals/market_sessions.py` (+1 function) changed.
- **Effective configuration**: V2 fingerprint `11107198c5b81237`
  (unchanged, re-verified this task), 39-name `resolved-active-watchlist`
  execution scope, 45-day lookback, `composite-yf` pricing, official
  V2/Intelligence Telegram delivery enabled, Experimental external
  delivery OFF, `--tick-seconds 150 --heartbeat-seconds 30`.
- **Env vars required before `start`**: `TALONX_INTEL_DELIVER_CARDS=1`,
  `TALONX_INTEL_DRY_RUN_DELIVERY=0`, `TALONX_INTEL_DELIVER_PER_CYCLE=20`,
  `TALONX_INTEL_DELIVER_TIMEOUT_SECONDS=20`,
  `TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS=21600`,
  `TALONX_INTEL_DELIVER_AGE_CUTOFF=1`.
- **New this candidate**: the `:8787` cockpit's "Paper / EOD" tab now
  shows per-lane realized/unrealized P&L, equity, and arithmetic
  reconciliation (folded in from Task 119/119A); the "Active V2" tab's
  $300,000 campaign ledger card gains the same for V2. No new tab, no new
  env var, no new dependency.

## Startup / warmup recovery procedure and readiness checks

1. `python -m talonx_ops.prospective preflight --expected-sha f28986999eec5e313cfc89db24e4dbacfb378891`
   — all 17 gates must read `[OK]`.
2. `python -m talonx_ops.prospective start ...` (same flags as today,
   §Candidate release above).
3. Watch `original.log` for `Initial Quant preseed complete: N/43` then,
   **only if N<43**, `Bounded preseed recovery sweep complete: R/M ...`.
4. **Per-symbol unsupported-data handling**: any symbol still not-ready
   after the sweep is reported explicitly (never silently treated as
   ready) and is expected to close via ordinary live accumulation during
   the session — if a symbol remains persistently not-ready across
   multiple sessions, that is new evidence worth a fresh, bounded
   investigation (not covered by today's fix, which is a one-shot
   startup sweep only).
5. Verify readiness independently against `quant.db.bar_buffer`
   (≥120 1-minute bars), not the log summary alone.

## Open-position and pending-notification obligations

- **Experimental: SPCX carries over**, 16.865960 sh, entry $148.2276,
  stop $144.6133, target $152.0633 — resolves under its existing policy
  on its own next qualifying tick; no manual action. **Re-verified
  read-only 2026-09-12 (Task119A/120)**: unchanged since Task 118H's
  close — same entry/stop/target, position still open, last stored mark
  $151.2100 @ 2026-09-11T20:09:20Z (POST_CLOSE, +$50.30 unrealized on
  that stale mark — will refresh on the next live tick, not before).
- **V2**: 0 open positions, no pending entry/exit obligations, ABCL
  episode `07242bc857569f60` remains terminal (`SKIPPED_ENTRY_STALE`).
- **Intelligence**: 0 pending cards at last check.
- **No other obligation carries over.**

## Feed / exit-evaluation / delivery verification (next session)

- Confirm `talonx:ingest:liveness` key is present, TTL refreshing, and
  `last_market_event_age_seconds` stays low during the regular session.
- Confirm at least one Experimental exit-check log line appears for SPCX
  shortly after open (proves the exit path is live, independent of any
  new entry).
- Confirm Intelligence `card_delivery.messages_sent_today` (not just
  `sent_today`) if any new digest fires.

## Canonical EOD procedure (unchanged)

`python -m talonx_ops.prospective close`, at/after the verified XNYS
close for that session, target completion within 90 minutes. Verify
`base_reconciliation.mismatches == []` and clean shutdown (`psutil` pid
check + port check + `redis.ping()`), exactly as done today.

## Known limitations (carried forward)

- Heartbeat-lapse locus (Task 118C) — unresolved.
- Historical "45 candidates" counter source — unresolved.
- SHOP has no local daily-bar price coverage in the frozen research
  dataset (research-replay-only; irrelevant to live trading). **Task 120
  update**: 5 more live-scope names share this gap — ABCL, ACHR, ADC,
  AGNC, and (materially) MSTR — meaning no historical replay of the
  39-name scope to date has been fully representative of the live-traded
  population. Named as the smallest next evidence-acquisition task above.
- The bounded recovery sweep is startup-only — a mid-session bulk
  provider failure has no automatic recovery (explicit, known gap).

## Explicit go/no-go conditions for next start

**GO** if: preflight all-`[OK]`, no live prior stack detected, V2 ledger
continuity confirmed, Redis reachable. **NO-GO / investigate first** if:
any preflight gate fails, a competing writer is detected, or the V2
ledger fingerprint/md5 differs unexpectedly from this session's final
state. **This decision is made at next-session preflight time, not here.**

## Next market session

**Monday 2026-09-14**, re-verified via `talonx_v2.calendar.is_session`
(2026-09-12/13 correctly read as non-sessions).

## One next research/product action

**Option 3 (attributable per-lane reconciliation surface) is DONE** —
implemented, tested, rendered, and integrated (Task 119/119A), live in
this candidate's Paper/EOD and Active V2 tabs.

**Superseded 2026-09-12 (Task120A–C)**: Task 120's N=27/6-name-gap
finding was corrected (wrong replay method, wrong coverage check — see
`docs/research/TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md`). The
authoritative 39-name-scope result is now a **properly-powered
chronological replay** (the real `V2Service.tick()`, N=57, 19 distinct
issuers, full 2019–2026 available history): net@20bps=−0.85%, 95%
CI=[−4.57%, +1.11%] — **still inconclusive** (CI includes zero), but on
a correctly-engineered, tighter-CI basis. Original's economic evidence
was found to already exist (Task 93, exact frozen contract, 1 trade in
18.7 months — cited, not rerun). Product decision:
**`INSUFFICIENT_EVIDENCE_WITH_ONE_SPECIFIC_NEXT_ACTION`** — the one
named next action is Experimental's exact `EXPERIMENTAL_RELAXED_V1`
contract, never backtested as a combined whole, reusing Task 93's
already-built/validated `task93_canonical_v1` dataset and harness (no
new data collection, no new framework). See
`docs/research/PRODUCT_STATUS.md` for the one-page authoritative summary.
Live V2 observation continues in parallel but remains explicitly not the
sole programme.
