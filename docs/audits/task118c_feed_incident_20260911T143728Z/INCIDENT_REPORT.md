# Task 118C — regular-session feed incident (2026-09-11)

**Verdict: RECOVERED_TRANSIENT** (primary), with **INSUFFICIENT_EVIDENCE**
for the exact locus (producer heartbeat-write gap vs. a momentary
reader-side check) of the one-time DISCONNECTED reading. No active
implementation defect was proven — **runtime left unchanged, no
hotfix, no restart.**

## Baseline verified

Actual UTC time at investigation start: `2026-09-11T14:37:28Z` (regular
session, market open since 13:30Z). Repository HEAD `813bfc0`
(docs-only); the code SHA actually loaded by the running processes is
unchanged since Task 118A's deployment, **`c88f4d4600735dcc65fb5108c73489e877d16ebe`**
— no restart has occurred since then, confirmed by `session.pids.json`
(`started_utc: 2026-09-11T11:54:30Z`, same pids as Task 118A/B) and
`tasklist`/`psutil` direct inspection (same pids still alive throughout
this investigation). V2 fingerprint `11107198c5b81237`, scope 39/45-day/
composite-yf, Experimental external OFF — all unchanged.

## Part 1 — evidence captured before any action

Timestamped, read-only snapshots (`overview`, `v2_active_strategy`,
`intelligence`, `validation`, `premarket`, `paper_eod` live API reads,
plus the real `talonx:ingest:liveness` Redis key) saved to
`C:\Users\rites\talonx_activation_backups\task118c_evidence_20260911T143728Z\`
(outside any tracked path, per convention — no secrets in these files;
all are public counts/prices/timestamps). No Redis flush, no counter
reset, nothing erased.

**By the time of this investigation (14:37Z, ~8 minutes after the
reported 14:29:18Z ping), the feed had already recovered** — per this
task's own instruction, the incident is diagnosed from retained evidence
(logs, database state) rather than reproduced live.

## Part 2 — market path trace

| boundary | latest observed | age/status |
|---|---|---|
| Provider (yfinance) | per-symbol errors clustered `14:23:01Z`–`14:31:46Z`: `AAPL`/`JPM`/`STX`/`TSLA`/`UNH` — mix of `possibly delisted; no price data found` and `PROVIDER_SCHEMA_ERROR: 'currentTradingPeriod'` | **partial, per-symbol** — other symbols continued succeeding throughout (confirmed: `original.log` shows continuous activity, no gap in the process's own log output) |
| Liveness beacon write (`talonx:ingest:liveness`) | `updated_at: 2026-09-11T14:38:31Z`, then `14:40:53Z` on a second check — TTL 71–75s, refreshing normally | **currently healthy and advancing**; state at the exact `14:29:18Z` instant not directly recoverable (the key is TTL-expiring, not append-logged) |
| Consumer (bar buffer) | `last_market_event_age_seconds: 0.6` (second check) | fresh |
| V2 strategy tick | `tick: 66`, `last_tick_utc: 2026-09-11T14:37:19Z`, `heartbeat_age_s: 26.2` | fresh, advancing |
| Health reporting (`/api/section/overview`.market) | `state: HEALTHY`, `last_event_age_seconds: 21` (first check) | agrees with the authoritative Redis key |

**Root-cause reasoning**: `talonx_ingest/liveness.py`'s `LivenessBeacon`
is explicitly designed (Task 87B FC_03, its own docstring) to write on a
**fixed cadence independent of market-event flow**, specifically to avoid
exactly this class of false-DISCONNECTED read from a quiet-but-healthy
period. Its `DISCONNECTED` state means the beat itself is missing/expired
— i.e. the reader found no fresh key, not merely that no market bar had
arrived. The per-symbol provider errors found in this window are real but
**partial** (other symbols kept succeeding) and yfinance calls are
confirmed wrapped in `asyncio.to_thread` (not blocking the event loop the
beacon's own timer runs on) — so a simple "poll loop stalled on a slow
provider call" explanation is **not fully supported** by what was found.
No process restart, no gap in `original.log`'s continuous output, and no
Redis reconnect/failure counter increment (`transport_counters` all zero)
coincides with the window. **What could not be established**: the
precise reason one specific liveness-key refresh cycle (if it genuinely
lapsed, rather than the ping's own read momentarily failing) was delayed
— this is reported as unresolved, not assumed.

Multiple causes may coexist, per this task's own allowance: this is best
read as a **brief, real, self-recovering hiccup** (consistent with the
clustered per-symbol provider errors occurring in the same window) whose
**exact producer-vs-reader locus is not fully determined** from available
evidence — not a claim of "no retry logic," not a claim of provider rate
limiting, and not a claim of a proven code defect.

## Part 3 — readiness and position safety (market now open)

Full per-ticker table not re-published here (would duplicate Task 118B's
`TASK118B_READINESS.md` methodology at a different timestamp) — key
findings: `configured_symbols: 48, selected_symbols: 43, usable_coverage:
1.0` (live, current). `suppression_counts` for today (2026-09-11, live
query): `LOW_VOLATILITY 743 (21 tickers)`, `OPENING_BLACKOUT 13
(7 tickers)`, `LOW_CONFLUENCE 9 (5 tickers)` — **OPENING_BLACKOUT matches
the ping's reported 13 exactly**; LOW_CONFLUENCE (9 now vs. 8 at the
ping) differs by exactly one additional event since the ping — consistent
with genuine, continuing evaluation, not stale/frozen counters. Zero
suppression rows alone were not treated as proof of readiness-blocking —
corroborated against live `bar_buffer` state (established in Task 118B's
methodology) and the actual evaluation paths above.

**Experimental positions — real exits observed during this
investigation, none forced**: since Task 118A/B, **STX** (closed
`2026-09-11T08:30:51-04:00`, net −$25.38), **AMD** (closed
`08:30:56-04:00`, net −$8.22), and **BLSH** (closed `08:59:27-04:00`, net
−$77.14) have all closed for real, through the same live-tick exit path
verified in Task 118B. **Only SPCX remains open.** This is direct,
concrete evidence fresh market observations are reaching exit evaluation
continuously through the regular session — not merely inferred.

**V2**: independently verified — `form4_records_seen: 8` (SEC poll
producing data), strategy tick advancing (`tick 66`, 26s heartbeat age),
cash $300,000, 0 positions, `exit_unresolved: []`. No V2-side failure
found; the intraday market-feed incident above did not propagate to a V2
SEC/daily-price failure (the two are independently sourced, as expected).

## Part 4 — Telegram and counter reconciliation

**Zero Telegram pushes at the ping is correct for the domain it
measures, not evidence of a lost message.** `dispatch_audit.db.alerts`
(the Original/trading-signal domain, the domain the ping's "0 published;
0 Telegram pushes" figures come from) shows **0 alerts, 0 sends today**
— genuinely correct: 0 published upstream (LOW_VOLATILITY-dominated
funnel) means 0 downstream by the frozen gate ordering, exactly as
established in Task 118 Part 3/118B. This is a **different, separately-
scoped counter** from Intelligence's own card delivery
(`ingestion_ledger.db.intelligence_delivery`), which independently and
correctly shows `SENT: 6` today (this morning's acknowledged digest,
message_id 720) and is untouched by this incident — the two were never
the same counter, so there is no contradiction, only a cross-domain
comparison that looks like one without this context.

**"45 candidates" — UNRESOLVED, not force-reconciled.** The two
sub-reasons the ping displayed (`8 LOW_CONFLUENCE`, `13
OPENING_BLACKOUT`) are independently confirmed against
`dispatch_audit.rejected_candidates`/`quant.db.suppression_counts`
(13 OPENING_BLACKOUT matches exactly; LOW_CONFLUENCE differs by exactly
one additional event consistent with elapsed time). **No query available
in this investigation reproduces "45" as a total** — the dominant
`LOW_VOLATILITY` reason (743 today) is far larger than 45 and evidently
excluded from whatever "candidates" counts, and no other matching
breakdown was found. Per this task's explicit instruction, **the
residual is not assigned to an assumed rejection class** — this specific
counter definition is labelled **UNRESOLVED**, an open item for whoever
owns that specific dashboard tile to clarify its exact source query, not
guessed at here.

## Part 5 — fix and recovery

**No active implementation defect was proven** (Part 2's reasoning above)
— per this task's own instruction ("If no functional defect is
established, leave runtime unchanged"), **no hotfix was written, no
isolated checkout was needed, and no restart was performed.** The
smallest safe action given the evidence is exactly this: document,
verify continued health, and stand down.

## Part 6 — recovery acceptance

Verified over three spaced live checks (`14:37:23Z`, `14:38:31Z`,
`14:40:53Z`, each a genuine new read, not a cached repeat):
- Market timestamps advance monotonically (`last_market_event_age_seconds`
  21s → fresh → 0.6s across checks — never stuck).
- Producer (`talonx:ingest:liveness`) and consumer (V2 tick 66, advancing)
  progress agree.
- Per-symbol coverage reported honestly — no threshold changed to force
  green.
- Dashboard (`/api/section/overview`) agrees with the authoritative Redis
  liveness key at every check.
- Open-position exit checks are receiving valid prices — proven by three
  real closes (STX/AMD/BLSH) during this exact investigation window.
- V2 ledger/config/fingerprint continuity holds throughout.
- No duplicate entries/exits/deliveries observed (each of STX/AMD/BLSH
  has exactly one SELL row; `alert_outbox.total: 0` this V2 tick — no
  spurious V2 activity).
- One supervisor pid (22860), one V2 companion (22544), one checkpoint
  daemon (9612) — unchanged since Task 118A's restart, confirmed still
  running, no duplicate producer.
- Redis intact — `redis_reachable: true` in the liveness key itself; no
  flush performed by this investigation.

**Since the feed was found already recovered by the time of
investigation, underlying market processing is confirmed to have
continued essentially throughout** — the clustered per-symbol provider
errors were partial, not total, and the process never restarted or
gapped in its own log. This is stated explicitly per this task's
instruction for a telemetry-leaning finding.

## Evidence

`C:\Users\rites\talonx_activation_backups\task118c_evidence_20260911T143728Z\`
(outside Git, sanitized live-API snapshots); `results/task100b_runtime_integration/_supervisor_logs/original.log`
(log lines cited above, timestamped); `talonx:ingest:liveness` Redis key
(read three times, not mutated); `talonx_ingest/liveness.py` (source,
unmodified).
