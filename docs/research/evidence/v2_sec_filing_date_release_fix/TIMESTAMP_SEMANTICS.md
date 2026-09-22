# SEC acceptance-timestamp semantics (corrected record)

## 1. What SEC actually serves

| SEC surface | Field | Semantics (verified) |
|---|---|---|
| Raw filing header `Archives/.../<acc>.hdr.sgml` | `<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS` | New York wall clock, no offset. Authoritative instant. |
| Filing index `-index.htm` | "Accepted" | New York wall clock (matches the SGML header) |
| EDGAR Atom feed | `<updated>` | explicit offset (e.g. `-04:00`) |
| **Submissions JSON** `data.sec.gov/submissions` | `acceptanceDateTime` (`...Z`) | **Unstable.** For about the first 5.5 h after acceptance it is the **New York wall clock labelled `Z`**; later SEC re-renders the same filing as the **true UTC** instant. |
| Submissions JSON | `filingDate` | SEC's calendar filing date. For Form 4 it equals the ET acceptance day, including filings accepted 20:00–22:00 ET (verified on all 425 audited filings). |

Evidence for the transient rendering (raw SGML vs the stored value vs the current JSON; the full table is in `../v2_39_stock_missed_opportunity_audit/SEC_TIMESTAMP_IMPACT_AUDIT.md` §1):
- **AFL `0001104659-26-109651`**, checked about 30 min after acceptance: SGML `16:27:06` (ET), JSON `16:27:06.000Z`, Atom `16:27:06-04:00`. The JSON was still ET-labelled.
- **Six filings TalonX ingested within 1–5 min of acceptance:** stored value = SGML ET wall clock, while SEC's JSON now shows ET + 4 h (true UTC).
- **ADC and DELL filings ingested days or hours later:** stored value = true UTC = SGML + 4 h.
- In the 425-filing sample, every value ingested ≤ 342.8 min after acceptance was ET-labelled, and every value ingested ≥ 324.7 min after was true UTC. The re-render therefore happens about 5.4–5.7 h after acceptance.

Task 117's contract ("submissions JSON `acceptanceDateTime` is VERIFIED UTC", `edgar_normalize.py`) was verified on older, already re-rendered filings. It holds for those, but not for fresh ones.

## 2. What TalonX stored

`parse_acceptance_datetime_ex` trusts the `Z`, so `insider_*.accepted_at_utc` holds whichever rendering SEC served at ingest:
- **STORED_TIMEZONE:** mixed. 397/425 true UTC and 28/425 New York wall clock in the audited sample.
- **FIELD_NAME_ACCURATE:** NO.
- **ACTUAL_TIME_VALUE_CORRECT:** CONTEXT_DEPENDENT. It is correct when ingested after SEC's re-render, and 4 h (EDT) / 5 h (EST) early when ingested fresh.
- The value was **not rewritten** by this fix. History is preserved, and the field is now documented as mixed legacy semantics.

## 3. Why it was release-blocking

`filing_date` was never populated on the live SEC poll path (0/34,253 filings; `ownership_xml.py` hard-coded `None`). V2 therefore derived the filing calendar date as `accepted_at_utc.date()` (`form4_source.py`, `service.py` dissemination lookup). For a filing accepted **20:00–22:00 ET** (EDT; from 19:00 ET in EST) and ingested after SEC's re-render, the UTC `.date()` is the **next** day. That moves the activation date, the entry session (one session later), the staleness boundary, and the cold-start test. A late cold start the contract refuses could then be admitted for the shifted session (demonstrated in `tests/test_v2_sec_filing_date_admission.py::test_5`).

## 4. Corrected record for ADC and ABCL (erratum E1 retracted)

| | SEC accepted (America/New_York) | UTC | TalonX receipt (UTC) | Delay | Filing date | Entry session |
|---|---|---|---|---|---|---|
| ADC `0001348490-26-000006` (activating) | 2026-09-17 **07:00:24** | **11:00:24** | 2026-09-21 18:42:40 | ≈ **4 d 7 h 42 m** | 2026-09-17 | 2026-09-18 |
| ABCL `0001834411-26-000008` (activating) | 2026-08-14 **12:04:25** | 16:04:25 | 2026-09-04 10:18:49 | ≈ 20 d 22 h 14 m | 2026-08-14 | 2026-08-17 |

**ERRATUM E1 RETRACTED.** E1 (PR #16) said ADC was accepted at "11:00:24 ET = 15:00:24Z", a 4 d 3 h 42 m delay. It assumed `accepted_at_utc` always held SEC local wall-clock time mislabelled UTC, but the field is mixed and depends on SEC's feed state at ingest. **The original Session 02 ADC forensic UTC value was correct.**

Classification is unchanged: ADC stays `LEGITIMATE_TIMING_REJECTION` / `MISSED_DUE_TO_INGESTION_DOWNTIME`, the decision did not change, and the Session 02 verdict stays `FULL_DAY_PASS_WITH_FINDINGS`.

## 5. The three timestamps V2 distinguishes after the fix

| Concept | Field | Used for |
|---|---|---|
| Filing calendar date | `filing_date` (SEC `filingDate`) | cluster window, activation date, entry session, staleness, cold start (release: **only** this; fail closed if absent) |
| SEC acceptance instant | `accepted_at_utc` (mixed legacy semantics) | the dissemination-before-RTH-open guard only (unchanged; its 4–5 h looseness cannot flip the result because the entry session is the next session and EDGAR closes at 22:00 ET) |
| TalonX durable receipt | `insider_filings.ingested_at_utc` (true UTC) | the binding late-receipt refusal (unchanged) |
