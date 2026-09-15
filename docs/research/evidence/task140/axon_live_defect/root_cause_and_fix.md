# Task 140b — Live Generic-Alert Defect: Root Cause, Fix, Closure

**User-reported defect**: two real Telegram informational pushes for
AXON restated their own filing category as "evidence" and explained
nothing about what was actually disclosed.

## 1. Exact provenance (traced, not assumed)

Both messages correspond to real, persisted rows in the production
`~/.talonx/ingestion_ledger.db` (raw trace: `raw_axon_provenance.txt`):

| | DEBT_FINANCING card | REGULATION_FD card |
|---|---|---|
| `event_id` | `SEC:0001193125-26-391320:DEBT_FINANCING` | `SEC:0001193125-26-391320:REGULATION_FD` |
| `accession` | `0001193125-26-391320` | `0001193125-26-391320` |
| Band | `CRITICAL` (score 7) | `CRITICAL` (score 7) |
| Tier / route | `CONCISE` / `IMMEDIATE` | `CONCISE` / `IMMEDIATE` |
| `sent_at_utc` | `2026-09-15T11:26:51.655750+00:00` | `2026-09-15T11:26:52.917000+00:00` |
| `transport_message_id` | `973` | `974` |

**Both events share the SAME accession** — verified directly from the
`accession` column on their `text_events` rows (`0001193125-26-391320`),
not inferred from their identical timestamps. A third event from the
same accession, `MATERIAL_AGREEMENT` (band `HIGH`), also exists and is
still `PENDING`/`DIGEST` (never sent) — the filing is a single bundled
8-K carrying items 1.01, 2.03, 7.01, 9.01.

**Every contributing significance reason** (from `event_significance.
reasons_json`, reproduced verbatim in
`tests/test_task140b_critical_content_gate.py`):

- DEBT_FINANCING: `EVENT_TYPE_BASE` ("direct financial obligation 8-K
  (Item 2.03/2.04)"), `MULTI_ITEM_8K`, `EVENT_RARE_FOR_FILER`,
  `EVENT_CLUSTER`, `ON_WATCHLIST`.
- REGULATION_FD: `EVENT_TYPE_BASE` ("Regulation FD disclosure 8-K (Item
  7.01)"), `MULTI_ITEM_8K`, `EVENT_RARE_FOR_FILER`, `EVENT_CLUSTER`,
  `ON_WATCHLIST`.

**None of these codes is in `SUBSTANTIVE_REASON_CODES`** (the frozen set
identifying a specific, already-thresholded content fact —
`SECTION_CHANGE_DECILE`, `SECTION_CHANGE_TERCILE`, `WHOLE_DOCUMENT_
CHANGE`, `NEW_MATERIAL_PASSAGES`, `RISK_TERM_COUNT_ROSE`, `XBRL_
MAGNITUDE`, `LARGE_OPEN_MARKET_TRANSACTION`). All five are meta/
category/selection reasons: what filing type this is, how many item
types were bundled, how rarely this filer files this event type, how
many disclosure types clustered this week, and watchlist membership —
none of them says what the debt obligation's terms are, or what the
Reg FD disclosure actually said.

**Enrichment/disposition provenance**: `enrichment.py`'s
`_process_one` computed `decision = classify_disposition(band=sig.band,
reasons=sig.reasons, insider_activity=insider_activity)`, then
`disposition_reason=decision.evidence_text` — this wiring is correct and
unchanged (verified in this session's own prior work). `render_concise`
is a dumb renderer that shows `disposition_reason` verbatim as its
second line. **The renderer did not select the wrong reason** — it
faithfully rendered whatever `evidence_text` the policy handed it.

**Running code/configuration**: both cards were enqueued/sent at
`2026-09-15T11:21:40`–`11:26:52 UTC`, well after this session's own
`2c96c8f` substantive-content commit (`2026-09-15T04:17:16Z`) and after
the Intelligence process's `10:31 UTC` restart earlier this session —
this was not a deployment-timing gap. It was a genuine logic bug, live
in the shipped policy the whole time since `2c96c8f`.

## 2. Complete production path traced

`text_events` (source facts) → `evaluate_significance` (bands+reasons,
`event_significance`) → `notification_policy.classify_disposition`
(disposition+evidence_text) → `enrichment.py` (`enqueue_card` with
`route_override`/`tier`/`disposition_reason`) → `intelligence_delivery`
outbox row → `process_pending`'s send loop → `render_concise` (final
text) → Telegram transport. Every stage but ONE (`classify_disposition`)
behaves correctly and needed no change.

## 3. The actual bypass (identified precisely)

`notification_policy.classify_disposition`'s `CRITICAL` branch had a
**separate, looser fallback** not shared by `MEDIUM`/`HIGH`:

```python
if band_val == SignificanceBand.CRITICAL.value:
    _, ev = _substantive_evidence(reasons)
    if ev is None and reasons:
        with_desc = [r for r in reasons if (r.description or "").strip()]
        if with_desc:
            ev = max(with_desc, key=lambda r: r.points).description
    return DispositionDecision(DISPOSITION_IMMEDIATE, ..., evidence_text=ev)
```

The reasoning (per its own comment) was that CRITICAL's structural floor
(≥2 substantive scoring families, ≥5 points) already proves
substantiveness, so ANY non-empty description should be trustworthy
enough to show. This is false in practice: `EVENT_TYPE_BASE` — a bare
category/item-number label, **deliberately excluded** from
`SUBSTANTIVE_REASON_CODES` — always carries a non-empty description
(the significance engine always populates it) and, for a multi-reason
CRITICAL card, typically **ties for the highest point value** with a
genuinely substantive-sounding but still-meta reason (`EVENT_RARE_FOR_
FILER` here, both scored `2`). Python's `max()` returns the **first**
element on a tie, and `EVENT_TYPE_BASE` is always listed first (it's the
base score) — so it silently won almost every time a CRITICAL card
lacked a genuine `SUBSTANTIVE_REASON_CODES` hit. This matches exactly
one of this task's own named candidate causes: **"CRITICAL or another
band bypassing the content check."** The renderer, tier selection, old
pending-row escape, and runtime-version hypotheses were all checked and
ruled out (see §1/§2 above).

## 4. Fix

`talonx_ingest/intelligence/delivery/notification_policy.py` — removed
CRITICAL's special case entirely. It now runs through the **identical**
evidence gate as MEDIUM/HIGH: a real `SUBSTANTIVE_REASON_CODES` hit with
a genuine (non-empty) description, OR a ≥2-distinct-insider open-market
BUY cluster; otherwise `DIGEST` (never suppressed, never fabricated).
"Regardless of significance band" — no band gets a looser bar; a higher
band earns more *prominence*, never a lower content bar.

No new `has_content` boolean, no new extraction pipeline, no external AI
service, no fabricated facts. The fix reuses the exact same
already-evidenced reason/cluster shapes the MEDIUM/HIGH path already
required — it removes an exception, adds nothing new to validate.

`talonx_ingest/intelligence/delivery/renderer.py` (`_quality_lines`) —
corrected the freshness-warning wording (§5 below).

## 5. Freshness wording — what was actually measured, and the fix

`card.freshness` (`FreshnessStatus`) is a **separate signal** from the
event's own `accepted_at_utc`/age (already shown one line above in every
card, e.g. "Source: 2026-09-15 07:20 UTC (source age: 4.1h)") — it
comes from `talonx_ingest.intelligence.freshness`'s own EDGAR-poll
currency tracker (FRESH/STALE/DOWN based on how recently a poll last
succeeded; UNKNOWN when never computed for this source).

**Verified directly against production**: `SELECT DISTINCT
freshness_status, COUNT(*) FROM text_events` returns exactly one row —
`UNKNOWN, 56755` — **100% of persisted events**. This tracker is not
currently wired into card construction at all; the field silently
defaults to `UNKNOWN` for every single event, making the old wording
("Source freshness unknown at emit time") an always-present, zero-signal
warning that reads as if it doubts the event's own timing — which is
in fact exact and known.

**Fix**: reworded to precisely name what's unknown without touching the
genuine limitation or fabricating a substitute value:

> ⚠️ Ingestion feed-poll currency not tracked for this source (the
> filing date/age above is exact and unaffected)

Never inferred from enqueue time, a DB read, or a heartbeat — if this
tracker is ever wired up in the future, this line would report its real
FRESH/STALE/DOWN verdict, not a proxy.

## 6. Requirement-to-code/test mapping

| Requirement | Code | Test |
|---|---|---|
| CRITICAL content gate closed | `notification_policy.py::classify_disposition` | `test_axon_debt_financing_no_longer_qualifies_immediate`, `test_axon_regulation_fd_no_longer_qualifies_immediate` |
| Generalizes beyond the exact AXON shape | (same) | `test_critical_band_category_only_reasons_cannot_reach_immediate` |
| Nonempty-but-generic insufficient | (same) | `test_nonempty_generic_reason_description_is_insufficient_regardless_of_length` |
| PENDING generic rows cannot escape | `notification_policy.py::reclassify_pending_rows` (pre-existing, unchanged, inherits the fix) | `test_reclassify_pending_rows_downgrades_a_critical_category_only_pending_row` |
| SENT/AMBIGUOUS rows never touched | (same) | `test_reclassify_never_touches_sent_rows` |
| Positive fixture — one useful message, facts in the actual payload | `renderer.py::render_concise` (unchanged) | `test_critical_band_with_genuine_substantive_reason_still_sends_one_useful_message` |
| Missing evidence → honest non-send | `classify_disposition` | `test_critical_band_missing_evidence_is_an_honest_non_send_not_a_fabrication` |
| Same-accession, each independently qualifies → distinct evidence | `classify_disposition` (accession-agnostic by design) | `test_same_accession_events_that_each_independently_qualify_get_distinct_evidence` |
| Freshness wording corrected | `renderer.py::_quality_lines` | `test_freshness_wording_no_longer_implies_the_known_source_timestamp_is_in_doubt` |
| Digest OFF / V2 unaffected | (no code touched) | `test_classify_disposition_never_touches_digest_toggle_or_v2` |

## 7. Same-accession consolidation — inspected, not built

No existing mechanism merges same-accession multi-item events into one
notification (confirmed: no `consolidat*`/"same accession" logic
anywhere in `talonx_ingest/intelligence/`, other than one unrelated
docstring mention). Each 8-K item type independently becomes its own
`TextEvent`/`event_significance`/card — this AXON filing alone produced
three (`MATERIAL_AGREEMENT`, `DEBT_FINANCING`, `REGULATION_FD`).

Building new cross-event consolidation is a genuinely separate feature
(new correlation/timing/delay semantics, exactly the kind of "another
feature task" this directive says not to introduce) — not attempted.
The directive's own fallback applies instead: **"If consolidation
cannot safely occur, each separately sent notification must still have
a distinct substantive explanation."** This is now guaranteed
structurally by the same fix: `evidence_text` is always drawn from that
specific event's own reasons, so two same-accession events that each
independently qualify necessarily get distinct text (proven:
`test_same_accession_events_that_each_independently_qualify_get_distinct_evidence`).
`classify_disposition` never reads accession/event_id at all, so it
structurally cannot delay one event waiting on another or combine two
filings by symbol/time.

## 8. Pending backlog — enforcement evidence

Direct query confirmed **zero PENDING CRITICAL-band rows** exist in
production at cutover time (the two real AXON CRITICAL cards were
already `SENT`, correctly left untouched). The bounded, idempotent
`reclassify_pending_rows` pass was still run against the live ledger
(same call the earlier Task 140 cutover established) —
`reclassify_pending_live_run.txt`: 49 currently-due PENDING IMMEDIATE
rows scanned, 0 downgraded, 0 errors. All 49 are `HIGH`/`MEDIUM` band
with genuine `LARGE_OPEN_MARKET_TRANSACTION` dollar-amount evidence
(sampled directly, `pending_sample.txt`) — unaffected by this
CRITICAL-only fix, confirming no incorrect mass-downgrade occurred.

## 9. Isolated vs. natural-live acceptance (kept separate)

**Isolated verification** (`isolated_verification_post_fix.txt`): a
direct `classify_disposition` call, using the same `.venv` the live
Intelligence process runs from, reproducing the real AXON
`DEBT_FINANCING`/`REGULATION_FD` reasons — both now resolve to `DIGEST`
with `evidence_text=None`. This is **not** a live Telegram round trip
and **not** a manufactured/replayed AXON send; the real, already-SENT
AXON rows were never touched or resent, per the directive's explicit
prohibition.

**Natural-live acceptance remains separately pending** — no new
qualifying or non-qualifying CRITICAL-band event has naturally occurred
in production since cutover to observe the corrected policy act on a
genuinely fresh event end-to-end. This will be confirmed the next time
one naturally arrives; not fabricated here.

## Limitations

- `LARGE_OPEN_MARKET_TRANSACTION`'s own description is a bare dollar
  figure ("an open-market insider transaction of about $X was
  reported"). This was inspected against the task's own caution ("do
  not treat a dollar amount alone as proof of investment importance")
  and deliberately **retained** as valid evidence: a concrete dollar
  transaction figure IS a specific, per-event fact distinguishable from
  "this filing type exists" (unlike `EVENT_TYPE_BASE`'s bare category
  label) — the caution is read as guidance against *interpreting*
  magnitude as importance, not as grounds to reject a genuine number.
  No live defect was found attributable to this code; not modified.
- No genuine content-extraction gap was found or closed for Item
  2.03/2.04 (debt terms/amount) or Item 7.01 (what was disclosed)
  specifically — the significance engine currently computes no
  dedicated reason code for either (no XBRL comparison applies to a
  freshly-announced debt instrument with no prior period; Reg FD
  narrative-text extraction does not exist). Building either is a new
  extraction project, explicitly out of this bounded correction's scope
  ("Do not add an external AI service, paid source or open-ended
  extraction project"). Both AXON events correctly fall through to
  DIGEST as a result — an honest non-send, not a workaround.
