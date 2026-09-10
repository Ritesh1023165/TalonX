# The four-hour timestamp pattern — root cause, impact, migration proposal

## Root cause: **Eastern wall-clock incorrectly labelled UTC** (a combination, but dominated by this)

SEC EDGAR renders every acceptance wall-clock in **US Eastern** (the 5:30 PM ET cut-off that
rolls a filing to the next business day is an Eastern rule). The `data.sec.gov/submissions` feed
nonetheless stamps `acceptanceDateTime` with a bare `...Z`.

`talonx_ingest/intelligence/edgar_normalize.parse_acceptance_datetime` (pre-fix) did
`s.replace("Z", "+00:00")` then `astimezone(timezone.utc)` — i.e. it **trusted the `Z`**. So an
Eastern instant of `14:28:59` was persisted as `2026-09-10T14:28:59+00:00`, which is
**4 h (EDT) / 5 h (EST) earlier than the true instant.**

### Evidence it is a timezone mislabel and not a real ingestion delay

| record | persisted "accepted" | `retrieved_at` (a real `utc_now()`) | gap if persisted is UTC | gap if persisted is really ET |
|---|---|---|---|---|
| PG `…161` | 14:28:59 | 18:35:53 | **4 h 07 m** | 6 m 54 s |
| V `…118` | 16:01:48 | 20:06:07 | **4 h 04 m** | 4 m 19 s |
| ORCL `…387905` | 16:16:50 | 20:24:11 | **4 h 07 m** | 7 m 21 s |
| ADP `…7726` | 16:23:38 | 20:30:55 | **4 h 07 m** | 7 m 17 s |
| JPM `…7727` | 16:27:42 | 20:31:00 | **4 h 03 m** | 3 m 18 s |

A real processing backlog would vary wildly across filings hours apart. The gap is
**~4 h ± 4 min for every one of them** — a constant offset is a timezone, not a queue. Under the
ET reading the poll latency is a consistent ~3–7 min, which is exactly what a continuously-running
poller does.

### Independent confirmation — Oracle earnings

Oracle reports **after the close**. The ORCL earnings 8-K (`…387905`) real acceptance is
**16:16:50 ET = AMC**. The system persisted `16:16:50 UTC`, `sessions.bucket_session` converted
it to `12:16:50 ET`, and stored **`session_bucket = RTH`**. The Sep-10 `intelligence_delivery`
cards for ORCL literally say **"regular hours"**. That is a user-visible correctness error caused
by this bug.

### Not an export-only error

The mislabel is in the **persisted** `text_events.accepted_at_utc`, `insider_filings.accepted_at_utc`,
`insider_transactions.accepted_at_utc`, `insider_filing_evidence.exact_timestamp`, and the
derived `text_events.session_bucket`. The published audit's exports faithfully reproduced the
persisted (wrong) values.

## The fix (this task)

`parse_acceptance_datetime` / new `parse_acceptance_datetime_ex`:

| input | old | new |
|---|---|---|
| `2026-07-31T18:05:12Z` / `+00:00` / naive | `18:05:12 UTC` | `18:05:12` **ET** → `22:05:12 UTC` (EDT) — flagged `acceptance_tz_assumed_eastern` |
| `2026-01-15T18:05:12Z` | `18:05:12 UTC` | `23:05:12 UTC` (EST) |
| `2026-07-31T14:05:12-04:00` (efts.sec.gov / RSS) | `18:05:12 UTC` | `18:05:12 UTC` — **explicit offset trusted, no flag** |

One switch, `EDGAR_ACCEPTANCE_ASSUMES_EASTERN = True`, to revert for exact pre-fix reproduction.
Every converted row carries the `acceptance_tz_assumed_eastern` data-quality flag so the
assumption is auditable and reversible per row.

Tests: `tests/test_task117_acceptance_timezone.py` — UTC persistence, EDT & EST, both DST
transitions, BMO/RTH/AMC incl. the exact ORCL case, pre-open/after-close, UTC-midnight crossing,
as-of causal cut-off, second-owner activation + eligible entry session, explicit offsets,
garbage. Updated `test_intelligence_edgar_normalize.py` and `test_intelligence_pipeline.py` whose
fixtures encoded the bug (fixture Z-strings are now the intended ET wall-clocks).

## Impact assessment

### V2 economics — bounded, mostly benign, one real exposure

V2's `cluster_engine` works on **dates**, not datetimes. V2's live `from_insider_store` used
`t.filing_date or t.accepted_at_utc.date()`. Under the bug, `.date()` of an ET-clock-labelled-UTC
value **equals the ET calendar date** — two wrongs cancel, so the eligible-entry-session
computation was correct for every filing **except** those accepted 20:00–23:59 ET, where
`.date()` of the (wrong) value is the ET day but `.date()` of the corrected UTC value is the
next day.

- **`from_insider_store` (fixed here):** now keys the missing `filing_date` on the acceptance
  instant's **Eastern** calendar date, so it is robust regardless of the acceptance-tz fix. A
  late-evening-ET Form 4 keeps its ET date (= dissemination date for NYSE-session purposes).
- **`causal_cutoff` in as-of replay (real exposure, now corrected):** the cutoff is compared to
  the full `accepted_at_utc` datetime. Under the bug a filing looked public ~4 h early → a
  bounded **look-ahead** window in any as-of backtest that used the live InsiderStore. The frozen
  **Task 116 replay is UNAFFECTED** — it reads the Task 107A parquet (`filing_date` column), not
  `parse_acceptance_datetime`, and does not import `edgar_normalize`.
- **Fingerprint:** unchanged (`11107198c5b81237`); none of `config/cluster_engine/liquidity/
  quant_bridge/brain_bridge` touched. **An unchanged fingerprint is not proof of economic
  parity** — but the Task 116 economic path is provably independent of the fixed code.
- **For the Sep 8–10 sessions specifically:** V2 made 0 signals; the only in-scope cluster (ABCL)
  activated mid-August with an activation filing well inside RTH, so its eligible entry session
  (2026-08-17) is identical under both timestamp readings. The corrected timestamps do **not**
  change any Sep 8–10 V2 outcome.

### Session classification — real, corrected

`text_events.session_bucket` was double-wrong for 8-K/10-Q/10-K events (store ET-as-UTC, then
`sessions.py` subtracts the ET offset again). Insider events were persisted `UNKNOWN` (the insider
path never buckets), so no insider bucket is wrong — but any downstream that computes a bucket
from the persisted `accepted_at_utc` was 4–5 h early.

### Human-facing timestamps

Every dashboard / card / export "when did this happen" for a non-explicit-offset SEC event was
4 h (EDT) / 5 h (EST) early. Fixed at the source.

## Migration / rebuild proposal — NOT executed

Rebuild is **not run** in this task (production DB mutation is not authorized). Proposed, on a
**copy**:

1. **Copy** `~/.talonx/ingestion_ledger.db` → `ingestion_ledger.db.tzrebuild`.
2. For every `text_events` / `insider_filings` / `insider_transactions` /
   `insider_filing_evidence` row **without** the `acceptance_tz_assumed_eastern` flag and whose
   `accepted_at_utc` (or `exact_timestamp`) has a zero/`Z`/absent offset:
   `new = localize(value_as_naive, "America/New_York").astimezone(UTC)`; append the flag.
   Rows that already carry an explicit non-zero offset or the flag are left alone (idempotent).
3. Recompute `text_events.session_bucket` for every affected event via `sessions.bucket_session`.
4. Re-run the significance ruleset for events whose `session_bucket` changed (session is an input
   to some significance components).
5. **V2 side:** re-run the Task 116 exact-runtime replay against the rebuilt store's dissemination
   dates on a copy of `v2_lane.db` and diff the chronological portfolio. Expected: **no change**
   for the current in-scope universe (no in-scope cluster has a 20:00–23:59 ET activation filing
   in the replay window) — but this must be *verified*, not assumed. If any entry session shifts,
   report the P&L delta; do not modify the frozen baseline to match.
6. Acceptance to activate the rebuild in production: (a) the rebuild is idempotent (re-running is
   a no-op), (b) `session_bucket` changes are all in the after-close/pre-open direction and
   explainable, (c) the V2 replay diff is empty or fully explained, (d) a spot-check of 10
   corrected rows against the real EDGAR filing-index "Accepted" timestamp.

Step 6(d) requires live EDGAR access to the 2026 filings, which is **not available in this
environment** — the accessions are forward-dated. That verification cell is **incomplete**; see
`remaining_gaps.md`.
