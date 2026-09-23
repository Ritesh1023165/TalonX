# Session 03: V2 opportunities and classification (2026-09-23)

Classification follows `../prospective_validation/README.md` §2, applied to the ledger and timestamps, not to the dashboard `fresh_eligible` label.

## Funnel (execution scope 39, live lookback 45 days, release mode)

| Stage | Count |
|---|---|
| Code-P records in window / new today | 11 / **1** (ADC, Erlich Craig) |
| Distinct code-P issuers in window / today | 3 (ABCL, ADC, INTC) / 1 (ADC) |
| Out-of-scope code-P records dropped (broad universe) | 43 per tick (not V2-eligible by design) |
| ≥2-owner episodes (frozen `detect_episodes`) | 2, both pre-existing: ABCL `07242bc857569f60`, ADC `19f814d1f3ec3250` |
| New episodes today | **0** |
| Ripe / intents / fills / exits | 0 / 0 / 0 / 0 |
| `MISSING_AUTHORITATIVE_FILING_DATE` | 0 |

## Per-item classification

| Symbol | Item | Classification | First decisive reason |
|---|---|---|---|
| ADC | New code-P filing `0001747962-26-000007` (owner 0001747962, SEC filingDate 2026-09-23, accepted 07:00:20 ET, received 11:01:43Z) | `NO_QUALIFYING_CLUSTER` (single-owner in a new window) | Frozen greedy, non-overlapping clustering (`cluster_engine.py:129-178`): the existing ADC episode's 10-trading-day window (09-02 → 09-17) is already consumed. The 09-23 filing is 14 trading days after 09-02, so it opens a new window with one distinct owner. A new episode needs a second distinct ADC owner filing by about 10-07. The user *was* informed through the separate Intelligence lane: an `[INFO]` card was SENT at 11:03:11Z ("3 distinct insiders bought … within 30 days, ~$4.14M"; its displayed source time is wrong, see README). That card is informational and is not a V2 trade event. |
| ADC | Episode `19f814d1f3ec3250` (entry 2026-09-18) | `MISSED_DUE_TO_INGESTION_DOWNTIME` (pre-campaign), terminal `SKIPPED_NO_PRIOR_INTENT` | Unchanged since 09-21 (`LEGITIMATE_TIMING_REJECTION`). It was skipped each tick (`stale_entry` count 2 includes it) and never re-admitted. |
| ABCL | Episode `07242bc857569f60` (entry 2026-08-17) | `MISSED_DUE_TO_INGESTION_DOWNTIME` (pre-campaign; ingestion not yet deployed), terminal `SKIPPED_ENTRY_STALE` | Unchanged |
| INTC | Single-owner code-P (08-14) | `NO_QUALIFYING_CLUSTER` | 1 distinct owner |

**Day-level: `NO_QUALIFYING_CLUSTER`.** No new ≥2-owner episode had an actionable window today.

The funnel's `REVIEW_POSSIBLE_SUPPRESSION` is the known observability artefact: ADC's terminal episode is still counted as "fresh-eligible" until its staleness cut, which was 2026-09-23. It is not suppression.

## No-trade discipline

- **Qualifying clusters existed:** none new. The two known episodes were already terminal.
- **Ingestion coverage complete:** YES_WITH_INFERENCE (`INGESTION_COVERAGE.md`). The one new code-P filing was received about 1.4 min after SEC acceptance.
- **Candidates rejected correctly:** yes, by the frozen clustering rule, not by a gate failure.
- **Operational miss:** none today.
- **Implementation defect:** none.
