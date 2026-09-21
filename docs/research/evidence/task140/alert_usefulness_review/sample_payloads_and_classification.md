# Sample Payloads, Evidence-to-Payload Comparison, and Classification

All payloads below are the REAL production policy/renderer run against
the isolated copy (full raw output: `rendered_samples_post_fix.txt`).
Classifications: `USEFUL_SUPPORTED_INFORMATION`,
`GENERIC_OR_INSUFFICIENT_CONTEXT`, `MISLEADING_OR_INCONSISTENT`,
`REDUNDANT_WITH_RELATED_EVENT`.

---

## 1/2. Insider purchases (buy clusters) — ABCL, ABT — content-only, EXPIRED

**ABCL** `SEC:0001628280-26-058684:INSIDER_TRANSACTION` (accession
`0001628280-26-058684`), accepted `2026-08-24T21:21:48Z`.

```
[INFO] ABCL — Insider ownership filing (Form 3/4/5)
3 distinct insiders bought in the open market within 30 days (4 transactions, ~$1,545,680 total)
Source: 2026-08-24 21:21 UTC (source age: 519.4h)
⚠️ Ingestion feed-poll currency not tracked for this source (the filing date/age above is exact and unaffected)
Reply "details" for facts and filing link.
ℹ️ Information, not advice. TalonX makes no prediction about future price or returns.
```

Evidence-to-payload: `insider_activity.clusters = [('MULTIPLE_OPEN_MARKET_BUYERS', 3, 30)]`;
30d aggregate: 3 purchasers, 4 txns, largest $570,442 → cluster total
~$1,545,680, matching the payload exactly.

**Checklist**: identifies the development (a buy cluster, not just "a
filing exists") ✓. Attention reason is more than "large amount" — states
direction, distinct-owner count, window ✓. Purchase/sale, count, owners
clear ✓ (roles not shown — a real, minor gap, see Limitations). Would
NOT pass the real send-time freshness gate today (`EXPIRED`,
`stale_card: 266.5h old by enqueue_time > 6h IMMEDIATE cutoff`) —
correctly labelled content-only, not sendable.

**Classification: `USEFUL_SUPPORTED_INFORMATION`.**

**ABT** `SEC:0000902132-26-000005:INSIDER_TRANSACTION` — same shape (2
distinct buyers, 30d, ~$1,127,837 total). Same classification, same
freshness-gate result (`EXPIRED`, content-only).

---

## 3/4. Insider sales + sell clusters — DD ×2 — **defect found and fixed**

`SEC:0001628280-25-054484:INSIDER_TRANSACTION`, accepted
`2025-12-01T21:58:23Z`. Real persisted reasons include BOTH
`LARGE_OPEN_MARKET_TRANSACTION` ("an open-market insider transaction of
about $3,026,466 was reported" — no direction) AND `INSIDER_CLUSTER`
("2 distinct insiders reported open-market sellers within 30 days").

**BEFORE this review's fix** (what the pre-existing code would have
sent — see `demonstrated_fix.md` for the full trace):
```
[INFO] DD — Insider ownership filing (Form 3/4/5)
an open-market insider transaction of about $3,026,466 was reported
Source: 2025-12-01 21:58 UTC (source age: 6902.8h)
...
```
Checklist: does the message identify the actual development? **No** —
"an insider transaction" could be a purchase or a sale. Is the attention
reason more than "large amount"? **No** — it is *exactly* "large
amount". Are purchase/sale, count, owners clear? **No.**

**Classification (before): `GENERIC_OR_INSUFFICIENT_CONTEXT`.** A real
dollar figure and a populated description are present — and still
insufficient, exactly matching this review's own stated bar.

**AFTER the fix** (real output, this review's own cutover):
```
[INFO] DD — Insider ownership filing (Form 3/4/5)
2 distinct insiders sold in the open market within 30 days (2 transactions, ~$594,513 total)
Source: 2025-12-01 21:58 UTC (source age: 6902.9h)
⚠️ Ingestion feed-poll currency not tracked for this source (the filing date/age above is exact and unaffected)
Reply "details" for facts and filing link.
ℹ️ Information, not advice. TalonX makes no prediction about future price or returns.
```

**Classification (after): `USEFUL_SUPPORTED_INFORMATION`.** Direction,
count, window, and dollar total (now the cluster's own 30-day total,
correctly scoped to the window it names, not the largest single
transaction across a different window) are all explicit.

Freshness-gate re-check: `EXPIRED` (`stale_card: 6902h old`) — genuinely
ancient content-only data, correctly not sendable regardless of the text
fix; the SAME symbol/accession's counterpart row
(`SEC:0001062993-24-009906`, accepted 2024-05-10) shows the identical
before/after pattern.

Both rows were `PENDING` at the moment they were selected for this
sample (the deterministic reason they were chosen); by the time this
review reached cutover, the live system's own unrelated freshness gate
had already expired both naturally — see `sampling_methodology.md`'s
note. **Neither the pre-fix nor the post-fix text was ever actually
delivered to the operator** for these two specific rows; the defect is
demonstrated and fixed for every future occurrence of this shape.

---

## 5. Buy cluster — ABCL — content-only, EXPIRED

`SEC:0001834423-26-000008:INSIDER_TRANSACTION`: "3 distinct insiders
bought in the open market within 30 days (3 transactions, ~$975,237
total)". Same shape/quality as #1. **`USEFUL_SUPPORTED_INFORMATION`**,
content-only (freshness-gate: `EXPIRED`).

---

## 6/7. Filing comparisons — ADM, ALK — SENT, CRITICAL

**ADM** `SEC:0000007084-24-000054:QUARTERLY_FILING`:
```
[INFO] ADM — Quarterly report (Form 10-Q)
Liquidity & Capital Resources rewrite in the top decile of this filing type's history (change magnitude 40%)
Source: 2024-11-18 21:05 UTC (source age: 15975.7h)
...
```
Evidence-to-payload: `SECTION_CHANGE_DECILE` reason names the SPECIFIC
section ("Liquidity & Capital Resources", not a bare percentage) and the
decile-ranked magnitude (40%) — this is a supported substantive change,
not merely a change-percentage score. **`USEFUL_SUPPORTED_INFORMATION`.**
Was genuinely `SENT` (real delivery); re-checking the send-time
freshness gate NOW correctly reports `EXPIRED` (27h old > 6h cutoff) —
the message *was* sendable when it was sent, and is honestly *not*
resendable today; this distinction (content eligibility vs. current
delivery eligibility) is preserved correctly by the existing gate,
unmodified by this review.

**ALK** `SEC:0000766421-24-000082:QUARTERLY_FILING`: "Risk Factors
rewrite in the top decile of this filing type's history (change
magnitude 85%)" — same shape/quality. **`USEFUL_SUPPORTED_INFORMATION`.**

---

## 8/9. Same-accession pair A — AXON (already-fixed CRITICAL bypass)

`SEC:0001193125-26-391320:DEBT_FINANCING` / `:REGULATION_FD` — **not
re-diagnosed here** (fixed and evidenced in
`../axon_live_defect/root_cause_and_fix.md`; no new evidence contradicts
that fix). Under the current policy, **both now resolve to `DIGEST`**
(`evidence_text=None`), confirmed again in this review's own isolated
re-run. No message is currently generated for either — no classification
applies (not sent). See `redundancy_findings.md`.

## 10/11. Same-accession pair B — ABCL EARNINGS_RESULTS + REGULATION_FD

The single most common same-accession shape (787 occurrences
system-wide is dominated by this exact pairing — an 8-K reporting
earnings almost always also carries a Reg FD item). Both events' real
persisted reasons are category-only (`EVENT_TYPE_BASE`, `EVENT_CLUSTER`,
`ON_WATCHLIST`) — **both correctly resolve to `DIGEST`** under the
current policy (verified directly, not assumed). No redundant `IMMEDIATE`
pair exists for this, the most common real-world same-accession case.

---

## 12. Pre-existing historical send — PSA — predates the content gate

`SEC:0001628280-26-061900:REGULATION_FD`, `sent_at_utc`
`2026-09-14T21:16:36Z` — tier `EXPANDED` (not `CONCISE`), sent **before**
the Task 138 Workstream 2 concise-alert commit even existed
(`5734b8c`, `2026-09-14T23:31:08Z` — over two hours later). Its real
"Why surfaced:" section is category-only (`EVENT_TYPE_BASE`,
`EVENT_CLUSTER`, `ON_WATCHLIST`) — under the CURRENT policy this
correctly resolves to `DIGEST` (verified). Historical residue from
before any content gate existed, not a currently-reproducible risk.
**`GENERIC_OR_INSUFFICIENT_CONTEXT`** as historically sent; would not be
sent today.

---

## Summary counts by classification

| Classification | Count | Samples |
|---|---|---|
| `USEFUL_SUPPORTED_INFORMATION` | 6 | 1, 2, 3(after), 4(after), 5, 6, 7 *(7 total — see note)* |
| `GENERIC_OR_INSUFFICIENT_CONTEXT` (as originally/historically evaluated, before this review's own fix) | 3 | 3(before), 4(before), 12 |
| `MISLEADING_OR_INCONSISTENT` | 0 | — |
| `REDUNDANT_WITH_RELATED_EVENT` | 0 | — (8/9, 10/11 never both reach IMMEDIATE; see redundancy findings) |
| Not sent under current policy (no classification applies) | 4 | 8, 9, 10, 11 |

*(Note: 3/4 are counted once each, showing their own before→after
transition; the "USEFUL" count of 7 in the table body above reflects
1,2,5,6,7 plus 3-after and 4-after = 7 distinct useful payloads across
the 12-sample set.)*
