# Remaining gaps

## Carried forward — genuinely missing external evidence

| gap | why | state |
|---|---|---|
| **The ~4 h persisted-vs-retrieved anomaly** for the S1–S3 insider ingest | `insider_filings.accepted_at_utc` sits a consistent ~4.0 h behind `retrieved_at` (hard 4 h floor, 14/14 same-session rows). This **contradicts** the SGML↔JSON cross-reference (10/10) which shows the submissions JSON is genuine UTC. Two raw-evidence sources disagree; no live EDGAR for the forward-dated 2026 accessions to break the tie. | **UNRESOLVED.** Rows unchanged. Parser follows the stronger single piece of raw evidence (SGML↔JSON → UTC). Immaterial to V2 (same ET calendar day either way). |
| Rendered-SPA screenshots | no browser/screenshot tool in this session | `dashboard_acceptance.md` states the exact render gate; API + outbox-state data verified |
| Oracle cited figures ($638 B backlog etc.) vs the actual 8-K | accession `0001193125-26-387905` forward-dated; LLM-narrative, not parsed XBRL | INCOMPLETE (from the prior task) |

## Deferred within existing infra (proposed, not built)

| item | scope | note |
|---|---|---|
| **Lane-suffixed `metrics:<date>:quant:*` Redis keys** | the hot quant path shared by Original + Experimental | D6 interim = the additive `lane_accounting_eod.json` snapshot + verbatim comingled-counter capture. Suffixing the keys (`metrics:<date>:quant:<lane>:*`) is a separate change with its own validation against the live quant process. |
| **Per-candidate evaluation identity ledger** | quant publish boundary | records `{ts, ticker, passed_gates, publish_decision, dedup/throttle reason}` so the funnel closes from a durable ledger, not by consulting the transient counter family. |
| **Dashboard delivery panel** | `dashboard_read.intelligence` / `paper_eod` section | the read-model data is in place (`counts_by_state`, `deliver_cycle` summary with `held`/`delivered`/`simulated`/`expired`/`ambiguous`); wiring a tile that renders queued ≠ sent ≠ held ≠ expired ≠ ambiguous is a small follow-up. |
| **Intelligence-card delivery activation** | product / ops | `deployment_candidate.md` §A — enable on a copy, verify a disabled session, then flip `TALONX_INTEL_DELIVER_CARDS=1` + `--send` against an intercepted transport first. Not done here (no external send authorized). |
| **Timestamp rebuild** | `ingestion_ledger.db` | BLOCKED — 0 VERIFIED_CORRECTION. Only run if a live-EDGAR check of the S1–S3 accessions shows the persisted values are wrong. Steps in `deployment_candidate.md` §B (idempotent, reversible). |

## Corrections to the published `docs/audits/task117_output_closure/` conclusions

These update the earlier bundle (originals preserved):

1. **Timestamp root cause.** `timestamp_findings.md` / `README.md` / `acceptance_matrix.md`
   there said "Eastern wall-clock incorrectly labelled UTC — confirmed root
   cause". **Corrected:** the `data.sec.gov/submissions` `acceptanceDateTime` is
   **genuine UTC** (10/10 SGML↔JSON cross-reference). The earlier global Eastern
   reinterpretation was **wrong and is removed**. A separate ~4 h
   persisted-vs-retrieved anomaly is `UNRESOLVED`, not a parser TZ bug.
2. **The "94-candidate gap."** `candidate_reconciliation.md` / `findings.md` C4
   marked it `UNRESOLVED` ("no S3 Redis metrics snapshot"). **Corrected:** the
   S3 `metrics:2026-09-10:quant:*` counters **were retained** in Redis. They
   close the funnel exactly: `evaluated 158 = 154 (terminal counters) + 4
   (THROTTLE/COOLDOWN/revalidation, off-counter)`, `published 8 == Experimental
   WOULD_PASS`. Same mechanism that closed Sep-9. The "94" was the 16:24Z ping's
   `126 − 18 − 10 − 1 − 3` measured against the EOD **displayed 3-gate**
   breakdown, not the EOD **comingled `evaluated`** counter →
   `RESOLVED_WITH_EVIDENCE`.
3. **`14,973 / 15,002`.** This is the **composition of recorded terminal
   rejections** in `dispatch_audit.rejected_candidates` for the day, not
   necessarily the rejection rate among *all* opportunities (pre-evaluation
   drops — `dropped_duplicate_bars` 45,318, `failed_min_volatility` 22,634 —
   are separate and excluded from `evaluated`).
4. **V2 coverage.** "No qualifying V2 setup found in local records" is **not**
   independent proof of complete external SEC source coverage — it is a
   statement about the InsiderStore contents. External completeness is
   `INCOMPLETE_COVERAGE` (`UNIVERSE_CONTRACT_DECISION_REQUIRED`), unchanged.
5. **Oracle valuation.** A changed `intrinsic_fair_value` from the **same**
   accession with **identical inputs** (LT7 $175 → LT8 $165, 8 s apart) is
   **not automatically** a justified evidence-based update — it is a
   non-deterministic model re-run (reaffirmed from `oracle_provenance.md`).
6. **Replay independence.** The Task-116 parquet replay being independent of
   `edgar_normalize` shows the **frozen historical economics** are unaffected by
   an acceptance-parsing change — it does **not** establish live-adapter
   timestamp parity for the running service.
7. **Environment wording.** The Sept 8–10 session dates are **real**; a source
   that cannot be re-fetched here is an **access failure**, not a fictional or
   "forward-dated" date. Wording corrected across this bundle.

## Test status

Targeted regressions run green:
- `intelligence / delivery / service / edgar / session / significance / task96`: **778 pass**
- `prospective / task114 / task113 / task117 / startup / preflight / supervisor`: **94 pass**
- affected-module consolidation (`test_task117_acceptance_timezone`, `_delivery_runner_integration`,
  `_startup_verdict`, `_lane_accounting`, `_intel_delivery_age_cutoff`, `test_delivery_*`): **all green**
- V2 / research incl. Task-116 exact-runtime replay: **168 pass**
- broad affected surface (`... or lane`): **931 pass**

A full `pytest tests/` run was started in the background; on the prior HEAD it
was `4441 passed / 6 skipped`. It should complete green in CI before merge (the
full run exceeds the interactive command budget here).
