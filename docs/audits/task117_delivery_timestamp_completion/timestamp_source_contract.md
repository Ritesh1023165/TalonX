# SEC acceptance-timestamp source contract

## What was wrong at `e3e7303`

`edgar_normalize.parse_acceptance_datetime` **globally** reinterpreted every
bare `Z` / `+00:00` / naive acceptance value as US/Eastern and shifted it +4h/+5h.
That was based on the observed ~4-hour ingestion gap — a basis the corrective
brief explicitly disallows ("Never infer timezone solely from the observed
four-hour ingestion gap").

## What the raw source evidence actually shows

Cached raw primary sources from the Task-117 phase-0 coverage audit
(`results/task117_phase0_source_coverage_audit_20260909T205439Z/primary_sources/`,
retrieved from `www.sec.gov` / `data.sec.gov` with a real UA + contact email):

- **Raw Form-4 SGML header** (`*.txt` / `*.hdr.sgml`): `<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS`
  — 14 digits, **no offset marker**.
- **`data.sec.gov/submissions` JSON**: `acceptanceDateTime` = `...T..:..:...000Z`.

**Cross-reference — 10 accessions present in BOTH, all EDT (Aug–Sep 2026):**

| accession | SGML `<ACCEPTANCE-DATETIME>` | submissions JSON `acceptanceDateTime` | Δ |
|---|---|---|---|
| `0001140361-26-034741` | `2026-08-27T18:30:30` | `2026-08-27T22:30:30.000Z` | +4h |
| `0001552781-26-000454` | `2026-08-19T16:15:48` | `2026-08-19T20:15:48.000Z` | +4h |
| `0002071761-26-000011` | `2026-09-08T07:02:11` | `2026-09-08T11:02:11.000Z` | +4h |
| `0001525321-26-000009` | `2026-08-18T19:20:49` | `2026-08-18T23:20:49.000Z` | +4h |
| … 10/10 … | consistently `SGML + 4h` (EDT) | | +4h |

**Conclusion (VERIFIED):** the SGML `<ACCEPTANCE-DATETIME>` is the **Eastern
wall-clock** (naive); the `data.sec.gov/submissions` JSON `acceptanceDateTime`
is that instant **already converted to UTC** by SEC, then marked `Z`. **The
submissions JSON `Z` value is a genuine UTC instant.** The earlier global
"Eastern" reinterpretation was wrong.

## The contract now in code

`ACCEPTANCE_SOURCE_TZ` (in `edgar_normalize.py`) + `parse_acceptance_datetime_ex(raw, *, source=...)`:

| `source` | field | rule | evidence |
|---|---|---|---|
| `"submissions"` (the **wired** path) | `data.sec.gov/submissions` `acceptanceDateTime` | a bare `Z` / `+00:00` **is** the UTC instant — no shift. Naive → UTC + `acceptance_offset_absent` flag (naive is technically ambiguous but the field's contract is UTC). | 10/10 SGML↔JSON cross-ref |
| `"sgml_header"` (not wired; tested) | Archives `*.hdr.sgml` `<ACCEPTANCE-DATETIME>` | naive → **US/Eastern**, DST-correct. Spring-forward gap → +1h; fall-back overlap → earlier instant; both flag `acceptance_dst_wallclock_adjusted`. Also carries `acceptance_tz_source_sgml_eastern`. | the same cross-ref (SGML = Eastern) |
| `"fulltext"` | `efts.sec.gov` | carries an explicit non-zero offset anyway → trusted verbatim | RSS/EFTS format |
| explicit non-zero offset, any source | — | trusted verbatim, converted to UTC, no flag | ISO-8601 |

Genuine UTC values **do not shift**. Explicit offsets are respected. Only a
value from `source="sgml_header"` with no offset is localized to Eastern — and
that path is **not wired into the pipeline**; it is tested so the machinery is
correct if a caller ever parses that field.

## Retained provenance

`parse_acceptance_datetime_ex` returns `(dt, flags)`; `iter_normalized_filings`
records the flags on `NormalizedFiling.flags` → persisted on the event. So each
row carries: the normalized UTC value, and (when relevant)
`acceptance_offset_absent` / `acceptance_tz_source_sgml_eastern` /
`acceptance_dst_wallclock_adjusted`. The raw string, the source field and the
parser version are recorded per row in `timestamp_correction_manifest.csv`.

## The unresolved anomaly (carried forward, NOT a parser bug)

The **persisted** `insider_filings.accepted_at_utc` for the S1–S3 live ingest
sits a consistent **~4.0 h behind** `insider_filing_evidence.retrieved_at`, with
a hard 4 h floor across 14 same-session records (0 under 0.5 h). That is
inconsistent with the SGML↔JSON cross-reference (which says the submissions JSON
is genuine UTC and the parser now agrees). The two raw-evidence sources
**disagree for the live-ingest rows**, and there is no live EDGAR for these
forward-dated 2026 accessions to break the tie. → **`timestamp_source_contract`
= PARTIAL**: the `submissions` contract is VERIFIED; the specific persisted
S1–S3 values are **UNRESOLVED** and left unchanged (`remaining_gaps.md`).

For V2 specifically this is immaterial: `from_insider_store` keys a missing
`filing_date` on `accepted_at_utc.date()`, and both readings put those records
on the **same ET calendar day**, so no eligible-entry-session changes.
