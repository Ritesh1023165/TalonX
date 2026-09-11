# Next-session handoff (finalized 2026-09-11, post-canonical-close)

**Do not launch the next session automatically — this is a handoff
document, not a scheduler. No GO is declared here; GO/NO-GO is a
preflight-time decision at next start.**

## Candidate release for the next session

- **SHA**: `5c0b3f3ccfef45ff8438e75f8f614b738deefc9a` (unchanged since
  Task 118F's deployment; this session's canonical close made no code
  change).
- **Effective configuration**: V2 fingerprint `11107198c5b81237`, 39-name
  `resolved-active-watchlist` execution scope, 45-day lookback,
  `composite-yf` pricing, official V2/Intelligence Telegram delivery
  enabled, Experimental external delivery OFF, `--tick-seconds 150
  --heartbeat-seconds 30`.
- **Env vars required before `start`**: `TALONX_INTEL_DELIVER_CARDS=1`,
  `TALONX_INTEL_DRY_RUN_DELIVERY=0`, `TALONX_INTEL_DELIVER_PER_CYCLE=20`,
  `TALONX_INTEL_DELIVER_TIMEOUT_SECONDS=20`,
  `TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS=21600`,
  `TALONX_INTEL_DELIVER_AGE_CUTOFF=1`.

## Startup / warmup recovery procedure and readiness checks

1. `python -m talonx_ops.prospective preflight --expected-sha 5c0b3f3...`
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
  on its own next qualifying tick; no manual action.
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
  dataset (research-replay-only; irrelevant to live trading).
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

See `PRODUCT_REQUIREMENTS_AND_NEXT_DECISION.md` — **Option 3, selected**:
an attributable, per-lane paper-performance reconciliation surface
(zero new data, reuses existing reconciled figures, produces a usable
capability with stated acceptance criteria). Live volatility tracking
(Task 118E/F protocol) continues in parallel but is explicitly not the
sole programme.
