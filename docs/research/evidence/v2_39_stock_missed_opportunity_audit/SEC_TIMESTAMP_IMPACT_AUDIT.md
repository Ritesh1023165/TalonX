# SEC acceptance-timestamp semantics and V2 decision impact

**TIMESTAMP VERDICT: `RELEASE_BLOCKING_ADMISSION_DEFECT`** (accepted by the gatekeeper; release classified `RELEASE_BLOCKED`).
**NO KNOWN HISTORICAL PURCHASE DECISION CHANGED: YES.**
**PROSPECTIVE LIVE ADMISSION CAN CHANGE: YES** (before the fix).

The audit below was preserved as written when the task stopped. The fix, backfill and post-fix recheck are in [`../v2_sec_filing_date_release_fix/`](../v2_sec_filing_date_release_fix/README.md).

Scope: read-only. The only external calls were public SEC reads (`data.sec.gov` submissions JSON, `Archives/*.hdr.sgml`, `-index.htm`, the EDGAR Atom feed) using the ingester's User-Agent. The ingestion ledger was opened `mode=ro`. Base `main` is `3e2067c`. Release `v2-paper-rc1` is intact, and the release gate reports READY (strategy fp `e2acf6454789217e`, provider fp `ac5e51aa3599d6c9`). Raw data: `extracts/sec_timestamp_impact.json`.

## 1. Correction of the previous finding F1 / erratum E1 (retraction)

Audit F1 claimed that "`accepted_at_utc` is SEC New York wall-clock time labelled UTC". **That is only partly true.** Erratum E1 changed the ADC time to 11:00:24 ET and **is wrong; it is hereby retracted.**

Against the authoritative raw SGML `<ACCEPTANCE-DATETIME>` (Eastern-naive):

| Accession | SGML (ET) | Submissions JSON now | Stored `accepted_at_utc` | Ingested (UTC) |
|---|---|---|---|---|
| ADC 0001348490-26-000006 | 2026-09-17 07:00:24 | 11:00:24.000Z | 11:00:24 | 2026-09-21 18:42:40 |
| ADC 0001528153-26-000015 | 2026-09-17 07:00:41 | 11:00:41.000Z | 11:00:41 | 2026-09-21 18:42:40 |
| DELL 0001193125-26-396717 | 2026-09-21 16:30:08 | 20:30:08.000Z | 20:30:08 | 2026-09-22 06:51:56 |
| AFL 0001104659-26-109651 (≈30 min old at check) | 2026-09-22 16:27:06 | **16:27:06.000Z** | not ingested | n/a |
| 0002016161-26-000012 | 2026-09-09 16:12:00 | 20:12:00.000Z | **16:12:00** | 2026-09-09 20:13:19 |
| 0001104659-26-106155 | 2026-09-09 09:00:06 | 13:00:06.000Z | **09:00:06** | 2026-09-09 13:01:33 |
| 0000080424-26-000164 | 2026-09-10 14:33:42 | 18:33:42.000Z | **14:33:42** | 2026-09-10 18:35:53 |
| 0001225208-26-007727 | 2026-09-10 16:27:42 | 20:27:42.000Z | **16:27:42** | 2026-09-10 20:31:00 |
| 0001193125-26-391971 | 2026-09-15 16:23:38 | 20:23:38.000Z | **16:23:38** | 2026-09-15 20:27:16 |
| 0000002488-26-000178 | 2026-09-14 16:19:52 | 20:19:52.000Z | **16:19:52** | 2026-09-14 20:24:14 |

What this shows:
- **SEC submissions JSON first publishes a fresh filing's `acceptanceDateTime` as the Eastern wall-clock with a `Z` suffix, then re-renders it to the true UTC instant.** In the sample, the re-render happens about 5.4–5.7 h after acceptance: every value ingested ≤342.8 min after acceptance was still ET, and every value ingested ≥324.7 min after was already UTC.
- **TalonX stores whatever value SEC served at ingest.** `parse_acceptance_datetime_ex` (`edgar_normalize.py:126-129`) trusts the `Z`, which is correct only after SEC's re-render. Task 117's contract ("JSON is VERIFIED UTC") was verified on older, already re-rendered filings, so it holds for them but not for fresh ones.
- **ADC corrected (true):** SEC accepted 2026-09-17 **07:00:24 America/New_York = 11:00:24 UTC**. TalonX receipt was 2026-09-21 18:42:40 UTC, a delay of **4 d 7 h 42 m**. The **original** Session 02 forensic values were correct.
- **ABCL corrected:** the activating filing was accepted 2026-08-14 **12:04:25 ET = 16:04:25 UTC**. OPPORTUNITY_LEDGER.md and README E1 labelled 16:04:25 as ET, which is wrong.
- Answers for this audit:
  - `SEC_SOURCE_TIMEZONE`: submissions JSON is ET wall-clock labelled `Z` for roughly the first 5.5 h, then true UTC. SGML/index pages are ET-naive. Atom carries an explicit offset.
  - `STORED_TIMEZONE`: mixed. 397/425 true UTC and 28/425 ET wall-clock in the sample, depending on when each filing was ingested.
  - `FIELD_NAME_ACCURATE`: NO. The value is not reliably UTC.
  - `ACTUAL_TIME_VALUE_CORRECT`: CONTEXT_DEPENDENT. It is correct for late ingests and 4–5 h early for fresh ingests.

## 2. Dependency map (Task B)

| # | Stage | Location | Notes |
|---|---|---|---|
| 1 | Source | SEC `data.sec.gov/submissions` `filings.recent.acceptanceDateTime` | the semantics above |
| 2 | Parse | `talonx_ingest/intelligence/edgar_normalize.py:77-158` → `NormalizedFiling.acceptance_datetime` | a `Z` is taken as UTC with no ET correction |
| 3 | Propagate | `service/poller.py:206`, `backfill.py:268`, `replay.py:80`, `intelligence/pipeline.py:160` → `accepted_at_utc=` | verbatim |
| 4 | Store | `text_events.accepted_at_utc`, `insider_filings.accepted_at_utc`, `insider_transactions.accepted_at_utc` | `filing_date` column exists but is **never populated** (0/34,253 filings, 0/115,461 txns) |
| 5 | Read / filter | `insider/store.py query_transactions` causal_cutoff (`accepted_at_utc <= cutoff`) | live cutoff = end of UTC as-of day, so it excludes nothing live |
| 6 | **V2 date** | `talonx_v2/form4_source.py:130`: `fd = t.filing_date or t.accepted_at_utc.date()` | **always `accepted_at_utc.date()`**, which is the source of cluster window, activation date, entry session, staleness and cold-start timing |
| 7 | V2 dissemination check | `talonx_v2/service.py:436-442` (lookup keyed by `fd`), `:1215-1235` (`ts >= rth_open` refuses) | the ET-labelled value is 4–5 h early; the check is looser but cannot flip, because the entry session is the next session after the ET date and EDGAR closes at 22:00 ET |
| 8 | V2 receipt check (binding) | `service.py:1254-1261` using `ingested_at_utc` | true UTC and correct |
| 9 | Display / reporting | `talonx_ingest/intelligence/sessions.py:98` (session bucket for Intelligence cards), `talonx_ops/prospective/funnel.py:130` (`code_p_today`), `checkpoint.py:179` (`newest_insider_event_utc`), forensic docs | a presentation- or bucketing-level error for fresh ingests |

## 3. Decision impact (Task D)

| Path | Uses `accepted_at_utc` | Impact |
|---|---|---|
| Cluster activation date | YES (`form4_source.py:130`) | **SESSION_MAPPING_RISK.** A true-UTC value for a filing accepted **20:00–22:00 ET** (EDT; 19:00+ in EST) gives the next UTC date, one day after SEC's ET filing date. |
| Entry session | YES (derived: `next session after activation date`) | **LIVE_ADMISSION_RISK**: entry is one session later than the ET-filing-date contract |
| Freshness / staleness | YES (derived from the entry session) | SESSION_MAPPING_RISK: the stale boundary shifts one session |
| Session-gap counting / cluster window | YES (10 trading days on `fd`) | SESSION_MAPPING_RISK at window edges |
| Receipt / deadline comparison | ingested_at (true UTC) for receipt; accepted_at for the dissemination check | receipt check: NONE. Dissemination check: NONE (cannot flip; see §2 row 7). |
| Cold-start | YES (`eligible_entry_session < today`) | **LIVE_ADMISSION_RISK**: a filing whose contract entry session already passed (a cold start that should be refused) can instead get an intent for the shifted, later session and be entered |
| Liquidity window | derived (sessions strictly before the entry session) | follows the shifted entry session |
| Corporate actions / dividends | NO | NONE |

**Concrete live scenario.** A second-owner code-P Form 4 is accepted Tuesday 21:00 ET (Wed 01:00Z). The stack stops about 16:05 ET and restarts around 03:00 ET Wednesday, about 6 h later, which is after SEC's re-render. The stored value is `Wed 01:00Z`, so the activation date is Wednesday and the entry is **Thursday open** instead of the contract's **Wednesday open**. If the stack had instead started after Wednesday's open, the contract would refuse the entry (`SKIPPED_NO_PRIOR_INTENT`), but the runtime would create a Thursday intent and enter. The outcome is not deterministic: it depends on how many minutes after acceptance TalonX happens to ingest the filing.

## 4. Historical sample (Task F): 39 symbols, 45-day lookback, 425 Form 4 accessions

| Metric | Count |
|---|---|
| Filings reviewed | 425 (9 code-P) |
| Stored true-UTC / stored ET wall-clock | 397 / 28 |
| True acceptance ≥ 20:00 ET | 34 |
| Session (calendar) date would change (runtime vs SEC ET date) | **34** (all non-P) |
| Entry session would change | **33** (all non-P; one Friday filing maps to Monday either way) |
| Freshness outcome would change (for any V2-relevant code-P record) | **0** |
| Live admission would change (code-P, V2-relevant) | **0**: none of the 9 code-P filings was accepted ≥ 20:00 ET |
| Clusters affected (ABCL, ADC) | **0** |

The DST transition (2026-11-01) is outside the sample, so its behaviour is not observed and not claimed. Midnight-UTC boundary cases are exactly the 34 rows above.

## 5. ADC recheck (Task E)

- Correct times: SEC 2026-09-17 07:00:24 ET = 11:00:24 UTC; receipt 2026-09-21 18:42:40 UTC; delay 4 d 7 h 42 m.
- Intended entry session: **2026-09-18** (unchanged, since the ET date and the UTC date are both 09-17).
- No valid intent could be created on 09-21 (the entry session had passed). `LEGITIMATE_TIMING_REJECTION` and `MISSED_DUE_TO_INGESTION_DOWNTIME` still hold, and the Session 02 verdict is unchanged. **Decision changed: NO.**
- The Task L erratum text proposed in the task brief (11:00:24 ET / 15:00:24 UTC / 4 d 3 h 42 m) is **not correct** and was not written. The correct values are above.

## 6. Classification (Task G)

**`RELEASE_BLOCKING_ADMISSION_DEFECT`**, applied under this task's rule ("if code inspection proves live admission can be wrong: STOP").

Nature of the defect: V2 derives the filing date from a timestamp whose semantics depend on SEC's transient rendering and on TalonX's ingestion timing. For filings accepted 20:00–22:00 ET and ingested after the ~5.5 h re-render, the entry session is mapped **one session late**. That can also admit a late cold-start entry the contract refuses.

What it does **not** do:
- cause look-ahead or an earlier-than-allowed entry
- affect cash or accounting
- trigger any historical V2 decision: 0 intents ever, and 0 affected code-P filings in the sample

The gatekeeper may judge this a fidelity/timing defect rather than a safety one. That decision is theirs.

## 7. Single bounded fix candidate (not implemented)

Make the V2 activation date come from **SEC's own Eastern filing date**, not from `accepted_at_utc.date()`. The domain already supports this: `form4_source.py` prefers `filing_date`, and `insider_filings` / `insider_transactions` / `text_events` have a `filing_date` column. The live poll path simply never populates it (`ownership_xml.py:140`). Plumb submissions `filingDate` into it, backfill existing rows from SEC, and separately normalise `accepted_at_utc`. That last step means either converting ET-labelled fresh values or reading the SGML header, and must be re-verified around the DST change. This touches ingestion runtime code and would need its own review. It changes no strategy rule.

## 8. Deferred at the STOP, now completed

- The continuous-ingestion operational contract (`FULL_PROSPECTIVE_COVERAGE`) is now in `prospective_validation/NEXT_SESSION_RUNBOOK.md`.
- The bounded fix in §7 is implemented in the SEC filing-date release-fidelity fix PR.
