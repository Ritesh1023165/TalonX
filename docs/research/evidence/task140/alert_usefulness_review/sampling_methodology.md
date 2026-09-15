# Sampling Methodology and Population Counts

**Scope**: this is a review, not a correction cycle by default. The live
stack was kept running throughout with configuration unchanged; no
delivery row was claimed, enqueued, sent, or altered on the live
production database. All rendering/policy evaluation was performed
against an **isolated file copy** of the production ledger
(`~/.talonx/ingestion_ledger.db` → a scratch copy, made once via plain
file copy, never re-synced), using the actual production
`classify_disposition`/`render_concise`/`expire_one_if_stale` functions
— never mocked. The one demonstrated defect this review found (see
`../notification_policy.py`'s `4a4657a` commit) was fixed under the
directive's own "fix only demonstrated requirement failures" authority,
with its own focused cutover recorded separately in this bundle.

## Population (real production `intelligence_delivery`, route=IMMEDIATE)

`population_survey.txt` — full counts:

- **18,321 total rows** ever routed `IMMEDIATE`.
- By state: `EXPIRED` 18,060 (before this review's cutover run — see
  below), `SENT` 218, `PENDING` 41 (at survey time; naturally decayed to
  0 by the time of this review's own cutover — see
  `reclassify_pending_live_run.txt`), `AMBIGUOUS` 2.
- By band: `HIGH` 16,681, `MEDIUM` 1,522, `CRITICAL` 118.
- By event type (top): `INSIDER_TRANSACTION` 14,924, `REGULATION_FD`
  744, `QUARTERLY_FILING` 642, `EARNINGS_RESULTS` 518, `EXECUTIVE_CHANGE`
  417, `MATERIAL_AGREEMENT` 379, `DEBT_FINANCING` 250, others smaller.
- **787 accessions** have more than one `IMMEDIATE`-route event
  (same-accession multi-event groups) — see `redundancy_findings.md`.

## Selection method (deterministic, not cherry-picked)

1. Built full category buckets by joining `intelligence_delivery` (route
   `IMMEDIATE`) against the latest `event_significance.reasons_json` per
   event and, for `INSIDER_TRANSACTION` events, `insider_transactions.
   classification` — `category_candidates.txt` records the exact bulk
   SQL/Python used and the resulting bucket sizes (e.g. `buy_cluster:
   453`, `sell_cluster: 10830`, `insider_purchase: 305`, `insider_sale
   (non-cluster): 539`).
2. Within each required category (insider purchase, insider sale, buy
   cluster, filing comparison, same-accession multi-event), **preferred
   `PENDING`/`SENT` rows** (currently live-relevant) over `EXPIRED` ones;
   used `EXPIRED` only where a category had **zero** `PENDING`/`SENT`
   candidates — every such case is labelled `content-only, not currently
   sendable` per the directive's own distinction, never presented as
   deliverable.
3. Selected the most-recently-enqueued candidate(s) within each category
   bucket (deterministic ordering, not a manual "best-looking" pick).
4. **Honest population gap, not invented**: zero `PENDING`/`SENT`
   insider-**purchase** events exist in the current population (305
   purchase events exist historically, all `EXPIRED`) — both purchase
   samples are therefore `EXPIRED`/content-only, disclosed as such, not
   substituted with an invented purchase example.

## Final sample — 12 events

| # | Category | Event | Band | State (at inspection) |
|---|---|---|---|---|
| 1 | insider purchase (buy cluster) | ABCL `SEC:0001628280-26-058684:INSIDER_TRANSACTION` | HIGH | EXPIRED (content-only) |
| 2 | insider purchase (buy cluster) | ABT `SEC:0000902132-26-000005:INSIDER_TRANSACTION` | HIGH | EXPIRED (content-only) |
| 3 | insider sale + sell cluster | DD `SEC:0001628280-25-054484:INSIDER_TRANSACTION` | HIGH | PENDING → EXPIRED by cutover (see below) |
| 4 | insider sale + sell cluster | DD `SEC:0001062993-24-009906:INSIDER_TRANSACTION` | HIGH | PENDING → EXPIRED by cutover |
| 5 | buy cluster | ABCL `SEC:0001834423-26-000008:INSIDER_TRANSACTION` | HIGH | EXPIRED (content-only) |
| 6 | filing comparison | ADM `SEC:0000007084-24-000054:QUARTERLY_FILING` | CRITICAL | SENT |
| 7 | filing comparison | ALK `SEC:0000766421-24-000082:QUARTERLY_FILING` | CRITICAL | SENT |
| 8 | same-accession pair A (already-fixed AXON case) | AXON `SEC:0001193125-26-391320:DEBT_FINANCING` | CRITICAL | SENT |
| 9 | same-accession pair A partner | AXON `SEC:0001193125-26-391320:REGULATION_FD` | CRITICAL | SENT |
| 10 | same-accession pair B (common pattern, 787 occurrences) | ABCL `SEC:0001703057-26-000044:EARNINGS_RESULTS` | HIGH | EXPIRED |
| 11 | same-accession pair B partner | ABCL `SEC:0001703057-26-000044:REGULATION_FD` | HIGH | EXPIRED |
| 12 | pre-existing historical (predates the content gate entirely) | PSA `SEC:0001628280-26-061900:REGULATION_FD` | HIGH | SENT |

Note on #3/#4: at survey time both were genuinely `PENDING` (verified,
used as the deterministic sample). By the time this review reached its
own cutover step, the **live, still-running** Intelligence process had
naturally expired them via the pre-existing, unrelated send-time
freshness gate (6h `IMMEDIATE` cutoff, `enqueue_at_utc` well past it) —
confirmed in `reclassify_pending_live_run.txt`. This is normal,
unrelated system operation, not an artifact of this review; it means
neither ever reached the operator with the defective text this review
found (see `demonstrated_fix.md`).
