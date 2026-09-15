# Task 140 Correction — Reply-for-Details Ordering, Index, Source Link, Wording

**Trigger**: the operator performed a REAL Telegram round trip against a
real historical digest (`message_id=958`, sent `2026-09-15T00:07:55Z`,
14 events, symbols `AKAM, AMZN, APO, CMG, CNP, D, FDX, FITB, MTB, NEE,
PH, SYY, TDG, TECH` in that exact displayed order) — replying `"Details"`
then `"Details 2"`. The response was wrong on five separate points. This
document is a correction appended to the Task 140 evidence bundle; it
does not alter or remove anything already published above.

## What was wrong (operator-reported, reproduced from real data below)

1. The index order returned by `"Details"` began `PH, APO, MTB, AKAM, D,
   FDX, ...` — not the digest's own displayed order.
2. `"Details 2"` resolved to `APO` — the digest's own second item was
   `AMZN`.
3. Only 6 items were shown, with `"...and 8 more"` and no way to reach
   the other 8.
4. The APO detail response promised source info but had no clickable
   filing link.
5. An expanded supporting card was labelled "Original notification text
   sent to you" — the text actually sent for a digest item is the
   compact digest line, not that fuller card.

## Root cause (#1/#2) — two independently-derived sort orders

`reply_correlation.py::find_delivery_rows_for_message` selected rows
`ORDER BY enqueued_at_utc ASC` (database insertion order). The real
digest renderer, `pipeline.py::_digest_text_from_rows`, sorted rows by
`(band_rank, symbol, event_id)` to build the text actually sent. These
were two separate, silently-disagreeing orders — nothing kept them in
sync.

**Verified against the real production rows for message 958** (all 14
have `band='MEDIUM')`: sorting those exact 14 rows by
`(band_rank, symbol, event_id)` reproduces the operator's reported order
**exactly** (`AKAM, AMZN, APO, CMG, CNP, D, FDX, FITB, MTB, NEE, PH, SYY,
TDG, TECH`), while `enqueued_at_utc` order does not. `APO` and `MTB`
share an identical `enqueued_at_utc` (`2026-09-14T20:24:00.169599+00:00`
— a timestamp tie from the same enrichment batch), which is exactly why
the old query's implicit SQLite tie-break put `APO` at position 2 instead
of the digest's real second item, `AMZN`.

### Fix

- `pipeline.py`: extracted the renderer's sort into a single shared
  function, `digest_display_order(rows)` — the renderer and the
  persistence path now both call this ONE function; they can no longer
  independently disagree.
- `outbox.py`: new additive column `intelligence_delivery.
  digest_item_ordinal` (nullable, migration-safe) — `mark_digest_sent`
  now takes `delivery_ids` in the exact order actually sent and persists
  each row's 1-based position as a durable fact.
- `pipeline.py::process_digest`: computes `ordered_rows =
  digest_display_order(...)` ONCE, uses it for both the rendered text
  and the ordinals passed to `mark_digest_sent` — one shared order, never
  two.
- `reply_correlation.py::_order_rows(rows)`: for any FUTURE digest (every
  row carries a stored `digest_item_ordinal`), sorts by that stored fact
  and reports `order_verified=True`. For a HISTORICAL digest sent before
  this column existed (message 958 included — all 14 of its rows predate
  this column), falls back to the SAME `digest_display_order` used at
  render time — a **verified deterministic reconstruction** (band/
  symbol/event_id are immutable once persisted, so this reconstruction
  is provably identical to what the renderer produced), explicitly
  labelled `order_verified=False` and disclosed in the reply text
  (`"... reconstructed from the original renderer's own ordering rule
  ... this is a verified deterministic reconstruction, not a stored
  record"`) — never silently presented as equivalent to a stored fact.
  This is NOT a hardcoded fix for this one message: the same
  reconstruction function applies to any pre-column digest, and is
  proven correct here specifically because it is independently checked
  against the operator's own real evidence, not assumed.

## Live re-verification against the REAL production message 958

Run via `build_intelligence_details_resolver` directly against the real
`~/.talonx/ingestion_ledger.db` (diagnostic resolver invocation — **not**
a live Telegram round trip; no message was sent, no chat was contacted).
See `reply_details_live_verification_message_958.txt` for the full
captured output. Summary:

- `"details"` index: `1. AKAM ... 2. AMZN ... 3. APO ...` through
  `14. TECH` — matches the operator's own reported display order
  exactly, labelled `reconstructed ... verified deterministic
  reconstruction` (correct: this message predates
  `digest_item_ordinal`).
- `"details 1"` → `AKAM` (matches the real first digest item).
- `"details 2"` → `AMZN` (matches the real second digest item — **not**
  `APO`, the confirmed real bug).

## #3 — full index / pagination (was: 6-item cap + dead end)

`_MAX_ITEMS_PER_REPLY = 6` (hardcoded) replaced with
`_INDEX_ITEMS_PER_PAGE = 20` and a full `_index_lines()` implementation.
For message 958 (14 items), all 14 now appear in ONE index response —
confirmed live above, no `"...and N more"` text anywhere. For a larger
set (tested with 25 synthetic items), pages are numbered globally and
stably: page 1 shows items 1-20, page 2 shows 21-25 (never restarting the
numbering), reachable via `"details page 2"`, and item numbers stay
identical across a close/reopen of the store.

## #4 — source link (was: silently omitted; risk: wrong-entity CIK)

Root cause of the missing APO link: `text_events.filing_index_url` is
`NULL` for this event (an upstream ingestion gap specific to Form 4/5 —
distinct from 8-K/10-Q, which do get a real index URL) — and the old
code silently dropped the "Filing link:" line whenever that field was
falsy, rather than saying so.

**A second, more serious risk was checked and confirmed against real
data**: the accession number's own prefix does NOT reliably identify the
issuer. For APO's actual accession `0001689315-26-000002`, the prefix
`0001689315` is the **filing insider's own CIK** (James Richard Belardi),
not Apollo Global Management's real CIK (`0001858681`) — two entirely
different numbers, confirmed directly from the real `insider_filings`
row for this exact event. Constructing a link from the accession prefix
would have pointed at the wrong entity's EDGAR page.

### Fix — `_resolve_source_link(ev, insider_filing)`

Preference order, every option a validated persisted fact, nothing
constructed from a guess:

1. `insider_filings.source_reference` (parsed directly from the Form 4/5
   XML's own issuer identity at ingestion time) — this table already had
   the correct URL for APO:
   `https://www.sec.gov/Archives/edgar/data/1858681/000168931526000002/wk-form4_1789417000.xml`
   (issuer CIK `1858681`, matching Apollo's real CIK, not the accession
   prefix).
2. `text_events.filing_index_url` (populated for 8-K/10-Q-style filings).
3. Neither present → explicit `"Source link unavailable (no validated
   issuer-CIK-based URL on record -- never guessed from the accession
   number's own prefix, which can identify a filing agent or the insider
   rather than the issuer)."` — never a fabricated line.

Live-verified above: `"details 1"` (AKAM, also Form 4, also no
`filing_index_url`) now shows a real, correct link resolved via
`insider_filings.source_reference`; `"details 2"` (AMZN, an 8-K) shows
its real `filing_index_url`.

## #5 — wording/provenance (was: mislabeled)

For a `route == "DIGEST"` row, the response now shows the **reconstructed
actual digest line** (via the same `_digest_row_summary` the real digest
renderer used) under the label `"The digest line you actually received
for this item:"`, and separately labels the fuller stored card
`"Stored supporting card (fuller detail than the compact digest line
above -- this fuller text was NOT itself sent to you ...)"`. The
previous, confirmed-wrong label `"Original notification text sent to
you"` is reserved for genuine single-card `IMMEDIATE` sends only (still
verified correct for that route — unaffected).

Facts vs. selection reasons are now visually separated:
`_SELECTION_REASON_CODES = {EVENT_TYPE_BASE, ON_WATCHLIST,
WATCHLIST_PINNED, MULTI_ITEM_8K}` route to a `"Why this was selected
(system routing reason, not a fact stated by the filing itself)"`
section; everything else (e.g. `EVENT_CLUSTER`, a real filing-fact code)
stays under `"Facts from the filing"`.

## A genuine bug FOUND by this segment's own live re-verification step

While re-running the fixed resolver against the real production message
958 (the live-verification step above — diagnostic only, still not a
live Telegram round trip), the reconstructed digest line for every row
with a non-empty `evidence_urls` column showed a stray trailing `"["`
instead of the real URL (11 of the real 14 rows for message 958;
confirmed directly against the raw `intelligence_delivery.evidence_urls`
column for all 14). Root cause: `pipeline.py::_digest_row_summary`
assumed `r.evidence_urls` was already a decoded Python list/tuple (true
for a real `DeliveryRow`, which `DeliveryOutbox._row()` builds via
`json.loads`), but the PRODUCTION reply-correlation path
(`ReadOnlyIntelligenceReader`, the exact wiring `run_talonx.py` uses)
hands back the raw, un-decoded JSON-string column — indexing `"[...]"[0]`
silently returns `"["`. This is a genuinely new gap introduced by this
same fix (the digest-line reconstruction itself is new in this task);
it did not exist before because the old code never reconstructed a
digest line at all. Fixed in `pipeline.py::_digest_row_summary` to
defensively `json.loads` a string `evidence_urls` before indexing,
covering both caller shapes. Re-verified live afterward (see the "after"
capture in `reply_details_live_verification_message_958.txt`): AMZN's
line now correctly shows its real evidence URL; AKAM's (genuinely empty
`evidence_urls`) correctly shows no link at all, not a stray character.
Covered by a new regression test,
`test_digest_line_reconstruction_via_the_real_readonly_production_wiring`,
which exercises the exact `ReadOnlyIntelligenceReader` /
`build_intelligence_details_resolver` production path against a local,
isolated digest.

## Limitations honestly disclosed

- This message (958) predates `digest_item_ordinal`, so its own order is
  labelled `order_verified=False` (reconstructed) in every reply,
  forever — this is permanent and correct, not a gap to "fix": no
  additional fact about its true send order exists to recover beyond
  what the reconstruction already proves. Every digest sent AFTER this
  fix's cutover will carry `order_verified=True`.
- The missing `text_events.filing_index_url` for Form 4/5 events remains
  an upstream ingestion gap (out of this task's scope) — the source-link
  fix works around it via `insider_filings.source_reference` where that
  table has the event, and states unavailability honestly where neither
  source exists.
