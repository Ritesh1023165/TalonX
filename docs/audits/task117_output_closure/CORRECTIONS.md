# Corrections to this bundle

Issued by `docs/audits/task117_delivery_timestamp_completion/` (which completes
the unfinished work). Originals in this directory are **unchanged**; read them
with these deltas.

1. **Timestamp root cause was mis-stated.** `timestamp_findings.md`, `README.md`
   §1 (TZ), `acceptance_matrix.md` §2 claimed "SEC `acceptanceDateTime` is US
   Eastern, not UTC — confirmed root cause", and shipped a global
   reinterpretation of `Z`/`+00:00`/naive as Eastern. **A 10-accession
   cross-reference of the raw Form-4 SGML `<ACCEPTANCE-DATETIME>` header against
   the `data.sec.gov/submissions` JSON shows the submissions JSON is GENUINE
   UTC** (JSON = SGML-Eastern + 4h; SEC already converts). The global
   reinterpretation was **wrong and has been removed**. The ~4-hour
   persisted-vs-`retrieved_at` gap is a **separate UNRESOLVED anomaly**, not a
   parser timezone bug, and was never a valid basis for the rule (inferring tz
   from that gap is explicitly disallowed). See
   `../task117_delivery_timestamp_completion/timestamp_source_contract.md`.

2. **The "94-candidate gap" is RESOLVED with evidence.**
   `candidate_reconciliation.md` (S3), `findings.md` C4 marked it UNRESOLVED for
   want of an S3 Redis metrics snapshot. That snapshot **was retained** in Redis
   (never flushed). EOD comingled counter: `evaluated 158 = 154 terminal
   counters + 4 off-counter (THROTTLE/COOLDOWN/revalidation)`; `published 8` all
   Experimental. Same mechanism that closed Sep-9 exactly. The "94" came from
   measuring the 16:24Z ping's `126 / 3` against the EOD *displayed 3-gate*
   breakdown instead of the EOD *comingled `evaluated`* counter. See
   `../task117_delivery_timestamp_completion/startup_accounting_acceptance.md` §D6.

3. **`14,973 / 15,002`** describes the composition of *recorded terminal
   rejections* for the day, not necessarily the rejection rate among *all*
   opportunities (the pre-evaluation `dropped_duplicate_bars` 45,318 and
   `failed_min_volatility` 22,634 are separate and excluded from `evaluated`).

4. **"No qualifying V2 setup in local records"** is a statement about the
   InsiderStore contents — **not** independent proof of complete external SEC
   source coverage. External completeness remains `INCOMPLETE_COVERAGE`.

5. **Oracle LT7 $175 → LT8 $165** (same accession, identical inputs, 8 s apart)
   is **not automatically** an evidence-based update — it is a non-deterministic
   model re-run (already the finding in `oracle_provenance.md`; reaffirmed).

6. **Parquet replay independence** (Task 116) shows the frozen historical
   economics are unaffected by an acceptance-parsing change — it does **not**
   establish live-adapter timestamp parity.

7. **The Sept 8–10 session dates are real.** A source that cannot be re-fetched
   in this environment is an **access failure**, not a fictional/forward-dated
   date. Any wording implying otherwise in the earlier bundle is withdrawn.

8. **D5 delivery** is no longer just "mechanics complete": the drain is **wired
   into `IntelligenceService.run_poll_loop`** (safe disabled default). See
   `../task117_delivery_timestamp_completion/delivery_integration.md`.
