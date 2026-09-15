# Demonstrated Defect and Its Fix

## The defect

`classify_disposition` selects a single "evidence_text" for an
`IMMEDIATE` card from the FIRST `SUBSTANTIVE_REASON_CODES` hit it finds.
For an `INSIDER_TRANSACTION` event carrying BOTH `LARGE_OPEN_MARKET_
TRANSACTION` (a bare dollar figure, no direction) AND a real insider
cluster (`INSIDER_CLUSTER`, which states direction/count/window but is
NOT itself a `SUBSTANTIVE_REASON_CODES` member), the dollar-only reason
always won — the richer, already-computed cluster fact was silently
discarded.

**Real, concrete proof** (not inferred from code reading alone):
`SEC:0001628280-25-054484:INSIDER_TRANSACTION` (DD, real PENDING row at
sample time) would have sent:

```
an open-market insider transaction of about $3,026,466 was reported
```

— giving no indication whether this was a purchase or a sale — despite
the SAME event's own persisted reasons already containing:

```
2 distinct insiders reported open-market sellers within 30 days
```

This directly fails this review's own checklist: *"Are purchase/sale,
transaction count, distinct owners and roles clear?"* — No, for
direction; count and window were available but never surfaced in the
concise push. Classified `GENERIC_OR_INSUFFICIENT_CONTEXT`: a real
dollar amount and a populated, well-formed description were present —
and still insufficient, matching this review's own stated bar that
neither alone establishes usefulness.

## Trace

`talonx_ingest/intelligence/significance/rules.py::insider_activity()`
computes BOTH facts independently and correctly (the cluster reason's
own description already states "sellers"/"buyers" correctly — the bug
was never in fact computation). `notification_policy.py::classify_
disposition`'s evidence-selection order was the sole cause: it checked
`_substantive_evidence(reasons)` (dollar-only) before ever checking for
a cluster, and returned as soon as that check succeeded.

## Fix (commit `4a4657a`)

When `LARGE_OPEN_MARKET_TRANSACTION` is the ONLY reason making an event
eligible AND a real cluster (buy or sell) also exists for it, the
cluster's own description is used instead. Scope, deliberately narrow:

- Does **not** widen eligibility — a cluster with no other qualifying
  reason still only grants `IMMEDIATE` on the BUY side
  (`_has_buy_cluster`, unchanged); a sell-cluster-only event still
  correctly falls to `DIGEST` on its own (verified:
  `test_sell_cluster_alone_still_does_not_grant_eligibility`).
- Does **not** touch a genuinely different substantive code (a
  filing-comparison code is never overridden — verified:
  `test_filing_change_code_is_never_overridden_by_an_unrelated_cluster`).
- Fixed a **second, latent bug** found while making this change:
  `_cluster_evidence_text` hardcoded "bought" regardless of the
  cluster's actual `kind` — never previously exercised for a sell
  cluster (only `_has_buy_cluster`, buy-only, ever called it before this
  fix); now states the real direction, mirroring `rules.py`'s own
  side-derivation.

**Real post-fix output for the same event**:
```
2 distinct insiders sold in the open market within 30 days (2 transactions, ~$594,513 total)
```

## Old PENDING rows

`reclassify_pending_rows` gained an optional `events_store` parameter:
when supplied, a `PENDING` row that stays `IMMEDIATE` but whose
evidence_text selection improves is re-rendered via the real
`render_concise` and its `text`/`content_hash` corrected in place —
route/state/attempts untouched. Omitting `events_store` (every existing
caller's current usage) preserves the exact prior route-only behavior
(verified:
`test_reclassify_pending_rows_without_events_store_preserves_old_text_only_behavior`).

Run against live production (`reclassify_pending_live_run.txt`): the
two real DD rows had already naturally expired (via the pre-existing,
unrelated 6h freshness gate) between this review's sampling and its own
cutover — `scanned: 0, content_refreshed: 0`, an honest "nothing
currently pending to correct" result. **Neither row was ever actually
delivered to the operator with the defective text** either before or
after this fix.

## Tests

9 new tests, `tests/test_task140c_cluster_evidence_preference.py`, all
passing — reproduces the real DD reasons/cluster shape, proves the
corrected text via the real `render_concise`, proves buy-side
co-occurrence says "bought" not "sold", proves the no-cluster case is
byte-for-byte unchanged, proves a filing-change code is never
overridden, proves eligibility is not widened, and proves the
`PENDING`-row content-refresh end-to-end with and without `events_store`.
Broader regression: 529 passed (intelligence/delivery/significance/
enrichment sweep) + 145 passed (directly-related focused suites), 0
failed.

## Cutover

Committed (`4a4657a`) before restart, per the directive. Only
`talonx_ingest/intelligence/delivery/notification_policy.py` was
modified (the sole importer is Intelligence; `run_talonx.py`/Original
never imports it — confirmed, same as the prior two Task 140
corrections this session). Minimal managed restart: Intelligence only
(shim stopped, supervisor auto-respawned it — `cutover_before_cluster_
fix.json` / `cutover_after_cluster_fix.json`). Original's own pid
(`13616`) and `commit_sha` unchanged throughout — never restarted.
Single Telegram `get_updates` owner maintained. GATED admission, V2,
digest-OFF, campaign/accounting state untouched (this fix touches no
file V2/execution/accounting import — confirmed empty grep, same check
as the prior two corrections).
