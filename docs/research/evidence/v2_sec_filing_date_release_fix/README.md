# V2 SEC filing-date release-fidelity fix

- **Release:** `v2-paper-rc1`, frozen strategy SHA `a56ec8c8d10adb36a113ebd373204f297c230081`
- **Base:** `main` `3e2067c`
- **Branch:** `fix/v2-sec-filing-date-admission`

**TIMESTAMP VERDICT (before the fix): `RELEASE_BLOCKING_ADMISSION_DEFECT`.** No known historical purchase decision changed: YES. Prospective live admission could change: YES. **After the fix: `RELEASE_BLOCK_CLOSED`**, pending review and one bounded post-fix re-acceptance.

## 1. Defect

SEC's submissions feed first serves a fresh filing's `acceptanceDateTime` as New York wall-clock time labelled `Z`, and rewrites it to true UTC about 5.5 h later. TalonX stored whichever version it saw, so `accepted_at_utc` is mixed. `filing_date` was never populated on the live poll path (`ownership_xml.py` set it to `None`). V2 therefore derived every filing's calendar date from `accepted_at_utc.date()` (`form4_source.py`, `service.py`).

For a second-owner filing accepted 20:00–22:00 ET (from 19:00 in EST) and ingested after SEC's rewrite, that date lands on the next day. The consequences:
- the entry session maps one session late
- the staleness and cold-start boundaries shift
- a late cold start the frozen contract refuses could be admitted

Full detail: [TIMESTAMP_SEMANTICS.md](TIMESTAMP_SEMANTICS.md).

## 2. Evidence corrections

- **ERRATUM E1 RETRACTED** (PR #16). ADC was accepted at **07:00:24 America/New_York = 11:00:24 UTC**. TalonX receipt was 2026-09-21 18:42:40 UTC, a delay of ≈ **4 d 7 h 42 m**. The original Session 02 forensic UTC value was correct.
- **ABCL corrected:** its trigger was accepted at **12:04:25 ET** (16:04:25 UTC), not "16:04:25 ET".
- Audit finding F1 is marked **SUPERSEDED**. `OPPORTUNITY_LEDGER.md` carries a correction banner, with every code-P time shown in ET plus true UTC.
- The timestamp-impact audit is preserved: `../v2_39_stock_missed_opportunity_audit/SEC_TIMESTAMP_IMPACT_AUDIT.md` and `extracts/sec_timestamp_impact.json`.
- ADC stays `LEGITIMATE_TIMING_REJECTION` / `MISSED_DUE_TO_INGESTION_DOWNTIME`. **Decision changed: NO.** Session 02 stays `FULL_DAY_PASS_WITH_FINDINGS`.

## 3. Live ingestion path (traced before the change)

EDGAR submissions JSON → `edgar_normalize.iter_normalized_filings` (`NormalizedFiling.filing_date` ← `filingDate`; `acceptance_datetime` ← `acceptanceDateTime` via `parse_acceptance_datetime_ex`) → `service/poller.py` / `backfill.py` / `replay.py` → `service/_insider.ingest_form_ownership` → `insider/pipeline.ingest_form4_xml` → `insider/ownership_xml.parse_ownership_xml` (builds `InsiderFiling`/`InsiderTransaction`) → `InsiderStore.upsert_batch`. That call persists `accepted_at_utc` and `filing_date` on filings and transactions, and `ingested_at_utc` on filings.

## 4. Fix (bounded; strategy rules unchanged)

| Change | Files |
|---|---|
| **Persist SEC `filingDate` on live ingest.** `nf.filing_date` is forwarded poller/backfill/replay → `ingest_form_ownership` → `ingest_form4_xml` → `parse_ownership_xml`. It is never fabricated: if SEC gives none, it stays `None`. It is not part of the content-addressed transaction ID, so this is idempotent. | `talonx_ingest/intelligence/service/{poller,backfill,replay,_insider}.py`, `talonx_ingest/intelligence/insider/{pipeline,ownership_xml}.py` |
| **Release fail-closed reader.** `from_insider_store(require_filing_date=True)` uses **only** `filing_date`. Any issuer with a code-P record lacking it is excluded entirely (no partial cluster) and reported as `MISSING_AUTHORITATIVE_FILING_DATE`. V2 `require_authoritative_filing_date` defaults to `release_mode`. The dissemination lookup is keyed the same way. The count and symbols appear in V2 status `source.missing_authoritative_filing_date`. Non-release/replay behaviour is unchanged. | `talonx_v2/form4_source.py`, `talonx_v2/service.py` |
| **Backfill** existing rows from SEC `filingDate` (persisted metadata first, then the SEC submissions feed plus shards). It writes `filing_date` only where NULL, never uses `accepted_at_utc`, and never re-ingests (so receipt times are preserved). | `talonx_ingest/intelligence/insider/filing_date_backfill.py` (new) |
| **Release gate:** `authoritative_filing_date_readiness`. FAIL if any code-P row in the last 60 days lacks `filing_date`, or if the ledger is absent. WARN when an injected test env configures no ledger. | `talonx_v2/release_gate.py` |
| **Freeze preflight:** a separate, closed `FREEZE_RELEASE_FIDELITY_FIX_FILES` list, guarded by a test (no strategy-fingerprint / provider / pricing / accounting / ledger file). The ops-hardening list and its test are untouched. | `talonx_ops/prospective/preflight.py` |

Unchanged:
- distinct-owner logic, cluster spacing, durable-receipt gating, cold-start gating, freshness thresholds (they now receive the correct date)
- the dissemination-before-open guard
- sizing, liquidity, pricing, provider, accounting, notifications and the campaign
- `accepted_at_utc` history: not rewritten, and documented as mixed legacy semantics

**Decision dependency after the fix:**
- V2 SESSION/ENTRY DATE DEPENDS ON `filing_date`: **YES**
- V2 SESSION/ENTRY DATE DEPENDS ON `accepted_at_utc`: **NO** (release mode)
- Cold start uses the correct session date: **YES**

## 5. Backfill and historical recheck

- Backfilled 34,253/34,253 filings and 115,461/115,461 transactions. Unresolved 0. Other columns byte-identical to the backup.
- Over the audited 425 filings: session-date differences went from **34 (old) to 0 (new)**. Purchase entry-session changes: 0. Known historical live-admission changes: **0**.

Details: [HISTORICAL_RECHECK.md](HISTORICAL_RECHECK.md).

## 6. Release identity

| | Before | After |
|---|---|---|
| Strategy fingerprint | `e2acf6454789217e` | `e2acf6454789217e` (the hashed files `config.py`, `cluster_engine.py`, `liquidity.py`, `quant_bridge.py`, `brain_bridge.py` are untouched) |
| Provider contract fingerprint | `ac5e51aa3599d6c9` | `ac5e51aa3599d6c9` |

## 7. Continuous ingestion and observability

- `FULL_PROSPECTIVE_COVERAGE` (`YES` / `YES_WITH_INFERENCE` / `NO`) is now an explicit operational requirement in `../prospective_validation/NEXT_SESSION_RUNBOOK.md`.
- Observability: **CURRENT_OBSERVABILITY_SUFFICIENT_WITH_INFERENCE**. Known gap: there is no durable per-poll history or start/stop timeline. That is a bounded future enhancement and is not implemented here.

## 8. Tests

See [REGRESSION_RESULTS.md](REGRESSION_RESULTS.md).
