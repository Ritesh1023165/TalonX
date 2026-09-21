# Accounting corrections (Task 117 §4)

File: `talonx_ops/prospective/lane_accounting.py` (writes `lane_accounting_eod.json`
via `talonx_ops.prospective.close`). Tests: `tests/test_task117_lane_accounting.py`.

## The problem being corrected

The earlier snapshot presented the final-day funnel residual (`evaluated −
Σ counter dispositions = 158 − 154 = 4`) as if the 4 were a *known
"THROTTLE / COOLDOWN / revalidation" disposition class*, and treated the mid-session
**16:24 ping** (`126 candidates / 3 publications`) and the derived **"94 candidate
gap"** as reconstructable / resolved. It also risked showing the comingled
Redis `metrics:<date>:quant:*` counter's `published` as an *Original official
publication* count.

## Corrections applied (smallest compatible)

1. **`off_counter_dispositions_from_records`** — queries
   `dispatch_audit.rejected_candidates` for `gate LIKE '%throttle%'` /
   `'%cooldown%'` / `'%reval%'` / `'%lockout%'` for the session date. **All
   return 0 — there are no such records anywhere.** The only gates that have
   ever existed are the five: `volatility`, `us_session`, `opening_blackout`,
   `confluence`, `trend`.

2. **`final_day_funnel_closure`** — still computes `residual = evaluated −
   Σ terminal counters`, but:
   - `residual_explained_by_records` is `True` **only if** `residual ==
     off_counter_total and off_counter_total > 0` — which is impossible here
     because `off_counter_total == 0`;
   - otherwise `residual_attribution` is the literal string *"NO corresponding
     disposition records found … the residual is NOT attributed to
     throttle/cooldown/revalidation (there are none on this day) and is NOT
     defined as the arithmetic remainder. UNEXPLAINED_FROM_RECORDS."*
   - `published_is_comingled: True`, `original_official_publications` =
     `dispatch_audit.alerts` count (0), `v2_publications: 0`.
   - The four off-counter dispositions, if they are ever to be named, must be
     **verified from records** — they are not defined as `residual`.

3. **`historical_16_24_ping_snapshot`** → `{"status": "NOT_RECONSTRUCTABLE", …}`.
   The `metrics:<date>:quant:*` counters are **cumulative**, not point-in-time;
   there is no 16:24:25 Z snapshot of them, and the end-of-day counter
   (`evaluated` is `None` in the durable capture) cannot reconstruct the
   mid-session `126 / 3`. Final-day reconciliation and the ping attribution are
   kept **separate**.

4. **`historical_94_candidate_gap`** → `{"status":
   "SUPERSEDED_BY_FINAL_DAY_RECONCILIATION", …}`. The "94" came from
   `126 − 18 − 10 − 1 − 3` — subtracting the EOD *displayed 3-gate breakdown*
   from the *16:24 ping candidate count*, an apples-to-oranges subtraction. The
   residual is **not** the 94 and is **not** the throttle class.

5. **`comingled_metrics_quant`** carries a `warning` that
   `metrics:<date>:quant:*` has no lane suffix (Original + Experimental
   increment the same keys), its `published` is **not** an Original
   official-publication count, and the dashboard does not display it as such.

## What is preserved

- Final-day counters and acquisition timestamps at EOD are read as-is from the
  durable stores; nothing is recomputed to force a balance.
- Lanes stay separate: `lanes.original_intraday` / `lanes.experimental` /
  `lanes.v2_trading`, each from its own durable store.
- **Unique setups vs repeated evaluations:** `distinct_tickers_with_a_rejection`
  and per-gate `terminal_dispositions_by_gate` count issuer×session, not
  re-evaluations.
- **Pending / in-flight included:** `in_flight` block reports
  `v2_pending_entry_intents` and `v2_alert_outbox_pending` with the note
  *"reconciliation must account for these before declaring a lane closed."*
- Historical evidence is kept honestly: the ping and the 94 are still recorded,
  labelled `NOT_RECONSTRUCTABLE` / `SUPERSEDED`, not deleted.

## Dashboard side

`authoritative_read_model.quant_signals()['published_proxy_alerts_today']` =
`dispatch_audit.alerts` row count (Original-attributable). No SPA surface shows
the comingled counter as an official publication. `dashboard_read.intelligence()`
`card_delivery.note` states *"cards QUEUED is not cards SENT."*

## Tests

- `test_lanes_are_separate_and_v2_read`
- `test_gap_is_unresolved_without_a_metrics_snapshot` — asserts
  `final_day_funnel_closure.status == "NO_METRICS_SNAPSHOT"`,
  `historical_94_candidate_gap.status == "SUPERSEDED_BY_FINAL_DAY_RECONCILIATION"`,
  `historical_16_24_ping_snapshot.status == "NOT_RECONSTRUCTABLE"`
- `test_residual_is_not_defined_as_throttle_by_arithmetic` — with a fake counter
  snapshot (158 = 154 + residual 4) asserts `residual_explained_by_records is
  False`, `"UNEXPLAINED_FROM_RECORDS" in residual_attribution`,
  `off_counter_dispositions_from_records.throttle == 0`,
  `original_official_publications == 0`
- `test_in_flight_is_reported`
