# Session 03: continuous insider-ingestion coverage

## Verdict: `FULL_PROSPECTIVE_COVERAGE: YES_WITH_INFERENCE`

The runbook's operational requirement (`../prospective_validation/NEXT_SESSION_RUNBOOK.md`) was met on every point. `YES_WITH_INFERENCE` rather than `YES` because continuity between 30-minute checkpoints is inferred: the heartbeat is overwritten and there is no durable per-poll history. No contrary evidence exists.

| Requirement | Evidence | Met |
|---|---|---|
| 1. Running before the actionable pre-open period | Ingester pid 7272 `started_at_utc` **2026-09-23T06:47:26Z**, 6 h 43 m before the 13:30Z open | YES |
| 2. Stayed running through the filing/admission windows | Same pid 7272 at start and at the final heartbeat (20:11:28Z); 0 unplanned restarts | YES |
| 3. Final SEC poll current | Last cycle **2026-09-23T20:09:51Z**, `FRESH`, 39/39 symbols, `symbols_failed` 0, errors 0 (controlled stop at 20:13:52Z) | YES |
| 4. No unhandled STALE/DOWN | Freshness `FRESH` at every sampled heartbeat. One Intelligence `DEGRADED_HEALTH` (Sentinel, created 12:53:21Z) was a transient: checkpoints at 12:47Z (log age 1 s) and 13:17Z (149 s) are both healthy. V2's Form-4 source was `ok` all day. | YES (handled) |
| 5. Gaps recorded | See below | YES |
| 6. Downtime opportunities classified | The pre-start gap contained **no code-P filing** in the 39-name scope (7 caught-up filings, all S/J/M), so nothing needed classification | YES |

## Timeline

- **Pre-start gap (recorded):** from Session 02's last poll at **2026-09-22 20:02:43Z** to this session's start at **2026-09-23 06:47:26Z**, about 10 h 45 m. The stack could not start before 00:00 UTC (the session directory is keyed by UTC date). A background start watcher was delayed and fired at 06:47Z, which the notification timing suggests was due to the machine sleeping. The gap ended **6 h 43 m before the open**. It was caught up within about 20 s of start: 7 filings (AFL, DELL ×3, NVDA, STX, MSTR), **none code-P**, all stored with `filing_date` 2026-09-22 = SEC `filingDate`.
- **Intraday continuity:** Intelligence processing-log age at each checkpoint (UTC): 06:47 38580 s (pre-start, stale from Session 02); 07:17 4 s; 07:47 59 s; 08:17 101 s; 08:47 117 s; 09:17 96 s; 09:47 126 s; 10:17 5 s; 10:47 121 s; 11:17 136 s; 11:47 1 s; 12:17 22 s; 12:47 1 s; 13:17 149 s; 13:47 85 s; 14:17 49 s; 14:47 54 s; 15:17 6 s; 15:47 4 s; 16:17 1 s; 16:47 61 s; 17:17 34 s; 17:47 8 s; 18:17 172 s; 18:47 156 s; 19:17 3 s; 19:47 185 s. The maximum after start was 185 s, far below the 900 s gap threshold.
- **Filings ingested today by UTC hour:** 06 → 7 (catch-up), 11 → 1, 13 → 1, 20 → 1.
- **Receipt latency (live):** ADC code-P `0001747962-26-000007` was accepted by SEC at **07:00:20 ET = 11:00:20Z** (raw SGML header) and received by TalonX at **11:01:43Z**, i.e. about 1.4 min.

## Filing-date fix: live watch

- New code-P filings in scope: **1** (ADC, above).
- SEC `filingDate` = **2026-09-23** and stored `filing_date` = **2026-09-23**: **MATCH**.
- `MISSING_AUTHORITATIVE_FILING_DATE`: **0**. V2 status at EOD: `source.missing_authoritative_filing_date = {required: true, count: 0}`, so release-mode fail-closed was active.
- Rows with NULL `filing_date` after the day's ingest: **0**. New ingests persist SEC `filingDate`.
- Observation (not a defect): 13 hours after acceptance, SEC's submissions JSON still showed this filing's `acceptanceDateTime` as `07:00:20.000Z`, the **ET** wall clock labelled `Z`. The stored `accepted_at_utc` is therefore the ET value. SEC's re-render timing is irregular; the earlier ~5.5 h estimate was sample-specific. This no longer affects V2, which maps by `filingDate`.
