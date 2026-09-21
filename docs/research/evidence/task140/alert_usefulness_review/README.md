# Bounded Alert-Usefulness Acceptance Review — Task 140 (segment)

**Objective**: determine whether currently-eligible informational alerts
explain (1) what specifically happened, (2) the supported factual
reason for attention, (3) any essential uncertainty — a dollar amount,
document-change score, populated description or band label alone does
not establish usefulness. The AXON category-only CRITICAL bypass
(`../axon_live_defect/`) was NOT reopened; no new evidence contradicts
that fix.

## What this review did

1. Surveyed the real production `intelligence_delivery` population
   (18,321 `IMMEDIATE`-route rows, all-time) and selected a **12-event,
   deterministic sample** covering insider purchases, insider sales, buy
   clusters, filing comparisons, and same-accession multi-event pairs —
   `sampling_methodology.md`.
2. Ran the REAL `classify_disposition`/`render_concise`/`expire_one_
   if_stale` (never mocked) against an isolated copy of the production
   ledger for every sample, capturing event identity, accession, source
   timestamp, policy decision, qualifying reason, supporting structured
   facts, and the real send-time freshness-gate verdict —
   `rendered_samples_post_fix.txt`, `sample_payloads_and_classification.md`.
3. Classified each payload and checked the full requirement checklist
   (direction/count/owners, comparisons/windows, interpretation vs.
   fact, essential qualifications, "details" consistency, redundancy).
4. Checked all 787 same-accession multi-event groups for actual
   redundant `IMMEDIATE` pairs — `redundancy_findings.md`.
5. **One demonstrated defect found and fixed** (commit `4a4657a`,
   smallest compatible correction, regression fixture, positive case
   preserved, old `PENDING` rows enforced) — `demonstrated_fix.md`.
6. No live message was sent, enqueued, claimed, replayed, or altered on
   the production database at any point in this review; the one fix
   applied went through: commit → isolated verification → bounded
   `reclassify_pending_rows` live run → minimal (Intelligence-only)
   managed restart → verification.

## Result summary

- **12 samples inspected.** 7 payloads classified `USEFUL_SUPPORTED_
  INFORMATION` (specific development, real direction/count/window,
  interpretation separated from fact). 3 classified `GENERIC_OR_
  INSUFFICIENT_CONTEXT` — the 2 real DD cases (now fixed, see below) and
  1 historical pre-content-gate send (PSA, would not send today). 0
  `MISLEADING_OR_INCONSISTENT`. 0 `REDUNDANT_WITH_RELATED_EVENT` (the
  4 same-accession samples never both reach `IMMEDIATE` under the
  current policy at all).
- **1 demonstrated, real defect fixed**: `LARGE_OPEN_MARKET_TRANSACTION`'s
  direction-less dollar figure was shown even when a richer,
  direction-stating insider-cluster fact was already computed for the
  same event. Fixed narrowly (evidence-text selection only, eligibility
  untouched), with a positive case and an eligibility-not-widened case
  both preserved by regression test.
- **No redundant same-accession sends exist or are at risk** — checked
  exhaustively (0 of 787 multi-event accessions have ever had two events
  both independently qualify). No consolidation subsystem built.
- **No other code change made.** Every other sampled payload passed the
  content contract as-is.

## Corrected scope of acceptance claims

This review is **not** a universal acceptance result. It covers 12 of
18,321 historical `IMMEDIATE`-route rows (a bounded, deterministic, but
small sample), drawn overwhelmingly from `INSIDER_TRANSACTION` and
`QUARTERLY_FILING`/`ANNUAL_FILING` event types (the categories the
directive named); `REGULATION_FD`, `EXECUTIVE_CHANGE`, `MATERIAL_
AGREEMENT`, `DEBT_FINANCING` and smaller categories were inspected only
via the 2 same-accession pairs and the 1 historical PSA sample, not
independently sampled for their own content quality at the same depth.
A passing focused/broad test suite is evidence the code behaves as
specified in the cases tested — it is not itself proof that the sampled
or unsampled population is uniformly useful; the actual rendered
payloads above are the load-bearing evidence, not the test count.

**Genuine, disclosed limitation not fixed in this review**: neither the
`INSIDER_TRANSACTION` cards' "Why surfaced" section, the `EVENT_
TYPE_LABEL` header line, nor the corrected cluster text states the
specific insider **role** (CEO/CFO/director/10%-owner) — only distinct
owner count. This was visible across every insider sample and is a real,
minor gap against the checklist's own "roles clear?" question; it was
NOT treated as a defect requiring a fix in this bounded review (no
concrete misleading/incorrect content resulted, only a modest
completeness gap), and is recorded here as the next concrete,
narrowly-scoped candidate if the operator wants it addressed.

## File index

| file | contents |
|---|---|
| `sampling_methodology.md` | selection method, population counts, the 12-sample table |
| `sample_payloads_and_classification.md` | every sample's real payload, evidence-to-payload comparison, classification + checklist answers |
| `redundancy_findings.md` | same-accession redundancy check (787 groups, 0 real double-qualifying pairs), correction of the prior evidence bundle's claim |
| `demonstrated_fix.md` | the one real defect found, its trace, fix, tests, and cutover |
| `population_survey.txt` | raw population counts by state/band/event-type, same-accession group count |
| `category_candidates.txt` | raw bulk categorization query output |
| `rendered_samples_post_fix.txt` | full raw output of all 12 samples through the real policy/renderer |
| `reclassify_pending_live_run.txt` | the live cutover `reclassify_pending_rows` run (0 rows to correct — naturally expired first) |
| `focused_test_run_output.txt` | the 9 new regression tests, all passing |
