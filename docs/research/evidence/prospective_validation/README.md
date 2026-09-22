# V2-PAPER-RC1 prospective validation: classification model and ingestion-coverage evidence

This is a reporting taxonomy and evidence procedure only. It does not change or reinterpret any frozen V2 rule (`v2-paper-rc1`, strategy fp `e2acf6454789217e`, provider fp `ac5e51aa3599d6c9`).

Companion files:
- [ECONOMIC_LEDGER.md](ECONOMIC_LEDGER.md): the cumulative per-opportunity and per-trade record
- [NEXT_SESSION_RUNBOOK.md](NEXT_SESSION_RUNBOOK.md): the procedure for the next market day

## 1. The frozen timing facts the taxonomy relies on

These are quoted from the code as it stands, not re-derived:

- **Cluster:** at least 2 distinct owner CIKs with code-P purchases within 10 trading days (`V2Config.min_distinct_owners=2`, `cluster_window_trading_days=10`).
- **Activation:** the filing date of the filing that brings in the 2nd distinct owner. `causal_event_ts` is 23:59:59Z on that date.
- **Entry session:** the next session after activation (`entry_offset_sessions=1`).
- **Intent creation:** happens only on a V2 tick where `today <= entry session` (`service.py:960`), and only **strictly before the entry session's RTH open** (`_verify_temporal_boundary`, `service.py:1149`).
- **No cold-start entry:** an episode first seen after its entry session, with no prior PENDING intent, is recorded terminal as `SKIPPED_NO_PRIOR_INTENT` (`service.py:642-661`, Task 131 Directive 2).
- **Staleness:** more than 3 sessions past the entry session gives `SKIPPED_ENTRY_STALE`.

The **actionable window** for a cluster therefore runs from the SEC acceptance of the activating filing to the RTH open of its entry session. TalonX must have ingested the filing *and* run a V2 tick inside that window.

## 2. Classification taxonomy (exactly one per potential opportunity)

Apply the categories in this order. The first one that matches wins.

| # | Category | Definition | Evidence required |
|---|---|---|---|
| 7 | `IMPLEMENTATION_DEFECT` | The frozen contract required progression, but TalonX did not progress the cluster (for example, received on time and in scope, but no intent and no rule-based disposition). | Forensic review showing that the state contradicts the contract |
| 4 | `RECEIVED_ON_TIME_FILLED` | A valid intent progressed to a paper fill. | `positions`/`trades` row linked to the `episode_id` |
| 3 | `RECEIVED_ON_TIME_ADMITTED` | Received in time and a valid PENDING intent was created, but it did not fill (for example, it expired or failed with no market data). | `pending_entry_intents` row with its terminal status |
| 2 | `RECEIVED_ON_TIME_REJECTED_BY_RULE` | Received in time, but a frozen rule rejected it: liquidity (`close<$5` or `MDV<$5M`), capacity, account block, cooldown, or out of scope. | disposition or decision rationale naming the rule |
| 5 | `MISSED_DUE_TO_INGESTION_DOWNTIME` | SEC acceptance was **before** the entry-session RTH open, but TalonX was not operating during the actionable window, so it received the filing only after the window closed. | `accepted_at_utc` < RTH open ≤ `ingested_at_utc`, **and** no prospective session covering the window (section 3) |
| 6 | `LATE_SOURCE_OR_LATE_RECEIPT_CORRECTLY_REJECTED` | Durable receipt came after the window for any other reason (SEC acceptance itself after the deadline, or TalonX running but receiving late), and the frozen rule correctly refused it (`SKIPPED_NO_PRIOR_INTENT` / `SKIPPED_ADMISSION_DEADLINE_PASSED` / `SKIPPED_ENTRY_STALE`). | receipt after the window, with coverage present, and a terminal disposition |
| 1 | `NO_QUALIFYING_CLUSTER` | No cluster satisfying the frozen contract existed for the day. This is a day-level result, recorded once when no other row applies. | funnel `clusters_ge2_distinct_insiders` has no new episode; the frozen `detect_episodes` agrees |

Rules:
- Categories 5 and 6 are **cause** categories. A category-5 or category-6 opportunity is still *correct system behaviour* when the ledger shows the frozen terminal disposition. The strategy rule is never weakened to recover it.
- The dashboard/funnel label `fresh_eligible` / `REVIEW_POSSIBLE_SUPPRESSION` is **not** a classification input. It ignores terminal dispositions (known bounded observability follow-up). Always classify from `processed_episodes`, `pending_entry_intents`, `positions` and the timestamps.
- Clusters whose entry session falls **before the campaign was created** (2026-09-21 18:38:19Z) are pre-campaign. They are listed but excluded from prospective opportunity counts.

## 3. Ingestion-coverage evidence (Task F)

| Question | Existing durable source | Survives restarts / gaps? |
|---|---|---|
| Filing first available at SEC | `insider_transactions.accepted_at_utc` (`~/.talonx/ingestion_ledger.db`). **Mixed legacy semantics:** SEC serves fresh filings as New York wall-clock labelled `Z` and rewrites them to true UTC about 5.5 h later, and TalonX stored whichever it saw. For an exact instant, use the raw SGML `<ACCEPTANCE-DATETIME>` (ET). **The filing calendar date is `filing_date` (SEC `filingDate`),** which V2 now uses exclusively in release mode. See `../v2_sec_filing_date_release_fix/TIMESTAMP_SEMANTICS.md`. | Yes |
| Filing first received by TalonX | `insider_filings.ingested_at_utc`; also `intel_event_processing.discovered_at_utc` | Yes |
| Activation timestamp / entry session | activation date = the activating filing's `filing_date` (SEC `filingDate`); `processed_episodes.eligible_entry_session` for dispositioned episodes; otherwise rebuild read-only with frozen `talonx_v2.pipeline.detect_episodes` against a **copy** of the ledger | Yes |
| Intent timing (if any) | `pending_entry_intents.created_at_utc`, `source_event_ts_utc`, `receipt_ts_utc`, `target_entry_session` | Yes |
| TalonX operational on a given day | `results/prospective_<date>/session.pids.json` (start), checkpoints every 30 min, `eod.json` (controlled stop time) | Yes, but only for days run via `talonx_ops.prospective` |
| Ingester process start / uptime (current run) | `~/.talonx/intelligence/service.metrics.json` (`started_at_utc`); checkpoint `supervisor.producers.intelligence.heartbeat_at` | **Current run only** (overwritten) |
| Last successful SEC poll | `python -m talonx_ingest.intelligence.service status` → `source_freshness.*.last_poll_success_utc`; backed by table `source_freshness` | **Latest value only** (one row per source, overwritten) |
| Filing-store freshness | checkpoint `intelligence.processing_log_age_s` and `newest_insider_event_utc`; `status` → `source_freshness.*.status` | Every 30 min while a session runs |
| Polling gaps | checkpoint `intelligence.processing_log_age_s` (30-min granularity); days with **zero** `insider_filings` ingested (for example, 0 rows on 2026-09-16 to 09-20) | Coarse / inferred |

**Assessment: sufficient for classification.** Every opportunity has durable SEC-acceptance and TalonX-receipt timestamps. Daily prospective-session artifacts show whether TalonX was running in the actionable window. Together these separate "strategy produced nothing" (category 1) from "opportunity existed but the system was offline" (category 5). A missed filing is also detected **retroactively**: when the ingester next runs it catches up, the cluster appears, and its receipt-after-window is visible, exactly as happened with ADC.

**Bounded observability gap (non-blocking):** there is no durable per-poll-cycle history and no ingester start/stop log outside prospective-session artifacts. `source_freshness`, the heartbeat and the metrics files hold only the latest value. Exact downtime intervals between sessions are therefore inferred (from absent ingestion rows and absent session dirs) rather than recorded. This is not required for the taxonomy above, and it is not fixed in this task.

## 4. Classification of opportunities to date

| Cluster | Symbol | SEC-accepted (activating, ET) | TalonX receipt (UTC) | Entry session | Ledger disposition | Category | Note |
|---|---|---|---|---|---|---|---|
| `07242bc857569f60` | ABCL | 2026-08-14 12:04:25 ET (16:04:25Z) | 2026-09-04 10:18:49Z | 2026-08-17 | `SKIPPED_ENTRY_STALE` | `MISSED_DUE_TO_INGESTION_DOWNTIME` (pre-campaign; ingestion not yet deployed, first ran 09-04) | excluded from in-campaign counts |
| `19f814d1f3ec3250` | ADC | 2026-09-17 07:00:24 ET (11:00:24Z) | 2026-09-21 18:42:40Z | 2026-09-18 | `SKIPPED_NO_PRIOR_INTENT` | `MISSED_DUE_TO_INGESTION_DOWNTIME` (pre-campaign) | ingester offline 09-16 to 09-20; campaign created 09-21. System response = LEGITIMATE_TIMING_REJECTION ([forensic](../v2_full_day_session_02/cluster_19f814d1f3ec3250_forensic.md); times corrected; audit erratum E1 RETRACTED) |

The full 39-symbol audit of 2026-09-16 → 09-22 is in [v2_39_stock_missed_opportunity_audit/](../v2_39_stock_missed_opportunity_audit/README.md): 2 clusters, 0 received on time, 0 implementation defects, 0 undelivered alerts.

## 5. Bounded follow-ups (known, not in scope now)

1. **SHUTDOWN notification timing.** The SHUTDOWN event is enqueued at `close` but stays PENDING because the stack stops before draining it. The 2-hour STARTUP/SHUTDOWN expiry prevents out-of-order delivery the next day. Reproduced in Session 02.
2. **Funnel `fresh_eligible` ignores terminal state.** `talonx_ops/prospective/funnel.py:158-165` counts terminally dispositioned episodes as fresh-eligible, which yields a spurious `REVIEW_POSSIBLE_SUPPRESSION` (ADC in Session 02). This is observability only, with no admission or accounting effect. `BOUNDED_OBSERVABILITY_FOLLOWUP`, not changed.
3. **No durable ingestion poll history / ingester start-stop log** (section 3). Exact inter-session downtime is inferred, not recorded. Non-blocking.
4. ~~`accepted_at_utc` is SEC New York wall-clock time labelled UTC~~ **Superseded:** the field is mixed ET/UTC, and V2 used its date for session mapping. This was a `RELEASE_BLOCKING_ADMISSION_DEFECT`, now **fixed** by the SEC filing-date release-fidelity fix (`filing_date` from SEC `filingDate`, release mode fails closed without it). For forensic lag arithmetic, take SEC acceptance from the SGML header, not `accepted_at_utc`.
