# Historical recheck under the fixed filing-date logic

## 1. Backfill of existing rows (applied 2026-09-22T22:10Z)

Tool: `python -m talonx_ingest.intelligence.insider.filing_date_backfill --apply`. The report is in `extracts/filing_date_backfill_report.json`.

- Source order: persisted SEC metadata (`text_events.filing_date`), which was empty for insider events, then SEC's submissions feed `filingDate` (`filings.recent` plus older shards).
- `accepted_at_utc.date()` is **never** used.
- The only write is `UPDATE … SET filing_date = ? WHERE accession = ? AND filing_date IS NULL`. It is idempotent and never overwrites.
- Safety backup taken first: `~/.talonx/backups/ingestion_ledger.db.pre-filing-date-backfill-20260922T220012Z` (SHA-256 prefix `77666693e02fc1fe`, identical to the pre-run ledger).

| Table | Rows total | Already populated | Backfilled | Unresolved |
|---|---|---|---|---|
| `insider_filings` | 34,253 | 0 | **34,253** | **0** |
| `insider_transactions` | 115,461 | 0 | **115,461** | **0** |

- Accessions resolved: 34,253 of 34,253, all from the SEC submissions `filingDate`.
- CIK fetch errors: 0. Unresolved code-P accessions: **0**.
- Integrity check against the backup: row counts identical. Content hashes of every other column (`accepted_at_utc`, `ingested_at_utc`, symbol, CIK, `transaction_date`, owner, code, value, classification) are **unchanged**; only `filing_date` changed.

## 2. The audited sample (39-symbol V2 scope, 45-day lookback)

Source for the "true ET date": SEC's current, re-rendered `acceptanceDateTime` converted to America/New_York (`../v2_39_stock_missed_opportunity_audit/extracts/sec_timestamp_impact.json`).

| Metric | Count |
|---|---|
| FILINGS REVIEWED | **425** |
| PURCHASE FILINGS | **9** |
| SESSION DATE DIFFERENCES UNDER OLD LOGIC (`accepted_at_utc.date()` vs ET filing day) | **34** (all accepted 20:00–22:00 ET; 33 would move the entry session) |
| SESSION DATE DIFFERENCES UNDER NEW LOGIC (`filing_date` vs ET filing day) | **0** |
| PURCHASE ENTRY SESSION CHANGES (old logic / new logic) | **0 / 0** |
| KNOWN HISTORICAL LIVE ADMISSION CHANGES | **0** |

SEC `filingDate` equals the ET acceptance day for all 425 filings, including the 34 evening filings. It is the correct calendar key.

## 3. ADC / ABCL end-to-end on the backfilled real data

Frozen `detect_episodes` was run over `form4_source.from_insider_store(..., require_filing_date=True)` for the 39 symbols (a scratch copy of the backfilled ledger), as of 2026-09-21 and 2026-09-22. It found 10 code-P records, **0 missing filing dates**, and exactly two episodes, with IDs identical to the ledger:

| Cluster | Symbol | Filing (activation) date | Entry session | Ledger disposition | Intent |
|---|---|---|---|---|---|
| `19f814d1f3ec3250` | ADC | **2026-09-17** | **2026-09-18** | `SKIPPED_NO_PRIOR_INTENT` | NOT_REACHED |
| `07242bc857569f60` | ABCL | 2026-08-14 | 2026-08-17 | `SKIPPED_ENTRY_STALE` | NOT_REACHED |

- ADC TalonX receipt: 2026-09-21 18:42:40 UTC. The late receipt is still rejected (also covered by `test_7_adc_entry_session_and_late_receipt_rejection_unchanged`).
- Classification: **LEGITIMATE_TIMING_REJECTION**. The Session 02 verdict is unchanged.
- No V2-PAPER-RC1 campaign state was touched: no intent, position or P&L change, no re-init.
