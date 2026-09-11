# Task 118A Priority 3 — operator-visible correctness (2026-09-11)

Bounded fixes, reusing existing routing/states; no new sender/poller, no
dashboard redesign.

## (a)+(b) Intelligence digest: literal `<b>` markup + "held events" wording

**Confirmed root cause**: `talonx_ingest/intelligence/delivery/pipeline.py::_digest_text_from_rows`
(the function actually used by the live `process_digest` path) built each
digest line's summary from `r.text.splitlines()[0]` — the **first line of
the individual card's own rendered text**. That text is rendered for
`parse_mode="HTML"` single-card sends
(`renderer.py::_identity_lines`: `f"{icon} {bold(label)}"`, i.e. literally
`"⚪ <b>MEDIUM</b>"`), but the DIGEST message that embeds it is sent with
`parse_mode=None` (plain text) — so the embedded `<b>...</b>` fragment
rendered literally in the delivered Telegram message. Separately, the
digest's own header line read `"N held event(s)"` even though, by the
time this function runs, those N rows are being sent **right now** (the
caller only reaches it once the digest is due) — "held" is the wording
`held_reason="digest_not_due"` rows use elsewhere, not rows actively being
delivered.

**Fix**: `_digest_text_from_rows` no longer touches `r.text` at all. A new
`_digest_row_summary(r)` builds a plain-text-only line from the row's own
structured facts — event type (derived from the row's own `event_id`
suffix, mapped through the existing `EVENT_TYPE_LABEL`), the row's own
enqueue time (labelled "enqueued", not claimed as the SEC acceptance
time), and a source link from `evidence_urls` if present — no
significance explanation, recommendation, or invented fact. Header changed
to `"N event(s) in this digest"`.

**Tests**: `tests/test_task118a_digest_rendering.py` — 4 new tests,
including a direct assertion no `<` or `>` character appears anywhere in a
real, engine-produced digest message text.

## (c) Cards delivered vs. actual Telegram message count

**Confirmed root cause**: the dashboard's `card_delivery.sent_today`
(`talonx_ops/dashboard_read.py`) counts **card rows** with `state='SENT'`.
A DIGEST batch marks every aggregated card row SENT under one shared
`attempt_id` (the digest id) but is exactly **one** Telegram API call —
e.g. this morning's real activation sent 6 cards as message_id 720, one
message, but `sent_today` alone reads "6".

**Fix**: added `messages_sent_today` alongside the existing field
(unchanged, for compatibility) — `COUNT(DISTINCT ...)` over `delivery_id`
for IMMEDIATE-route rows (each is its own message) and over
`COALESCE(attempt_id, delivery_id)` for DIGEST-route rows (shared per
batch). The `note` field was extended to explain the distinction in place.

**Tests**: `tests/test_task118a_dashboard_message_count.py` — 2 new tests
against the real `DeliveryOutbox`/`process_pending`/`process_digest`
pipeline (not a stub), proving 3 aggregated cards → `sent_today=3`,
`messages_sent_today=1`, and a mixed immediate+digest batch counts
correctly (3 rows, 2 messages).

## (d) Experimental exit readiness / pending reasons

Addressed as part of Priority 1: the display log
(`exp_alerts.db.experimental_trades`) now correctly reflects `exit_reason`
("stop_loss"/"target_exit"), `closed_at`, and `net_pnl` once an exit
actually occurs (previously it would have stayed permanently blank even
after a real exit, since the exit path was never wired at all). No
separate change was needed once Priority 1's `update_trade` call was
added — this IS the fix for "pending reasons" display: a still-open
position's row now genuinely reflects "still open" because the underlying
mechanism now actually can close it, rather than the row simply never
being touched by any exit code path at all.

## (e) Missing prices / unavailable outcomes displayed as zero

**Not reproduced.** Checked `talonx_ops/dashboard_read.py` specifically
for a place that computes or displays Experimental unrealized P&L or a
current/mark price — no such computation exists anywhere in the dashboard
today (the Task 118 Part 4 unrealized-P&L figures were computed manually
against the `directional_alerts` feed, entirely outside any dashboard
code path). Since the field does not exist, there is no live instance of
it being coerced to zero to point at. This is reported as **not found**
rather than assumed fixed or invented — if a specific screen/field shows
this, it was not located in this bounded review.

## (f) Current-session EOD state presented as already reconciled before close

**Confirmed root cause, in TWO places**: both
`talonx_ops/authoritative_read_model.py::eod_reconciliation()`
(`today_reconciled: today is not None`) and
`talonx_ops/supervisor.py::_status_snapshot()`
(`eod_reconciled_today: bool(latest and latest.session_date == today)`)
declared "today reconciled" true merely because **a record exists for
today's date** — regardless of that record's own `status` field. Live,
this was directly observed: at 2026-09-11 11:03 UTC (pre-open — the
regular session had not even started), the dashboard's `paper_eod` section
showed `"today_reconciled": true` for a record whose own nested `status`
was `"PARTIAL"` (written by an earlier shutdown/restart snapshot, not a
real close).

**Fix**: `today_reconciled` in both places now means what it says — true
only when the record's own status is `RECONCILED` or
`RECONCILED_WITH_MISMATCH`. The original meaning ("a record exists for
today at all") is preserved under a new, honestly-named field,
`today_has_a_record` (`authoritative_read_model.py` only — `supervisor.py`
had no equivalent second field to preserve).

**Tests**: `tests/test_task100b_runtime_integration.py::test_41*` updated
to assert the corrected semantics against real `run_and_persist(...)`
output (both a `PARTIAL`-status scenario and, separately, a genuinely
`RECONCILED` one); a new `test_41b_...` added. Existing
`test_task102_operational_finalization.py` field-presence assertions for
`eod_reconciled_today` verified unaffected (they check the key exists,
not its value).

## Verification: real SPA rendering

The isolated/offline tests above exercise the exact functions the SPA's
`/api/section/intelligence` and `/api/section/paper_eod` endpoints call —
not a separate fixture renderer. **Live SPA verification after
deployment** (screenshots, real `:8787` reads) is captured in the main
activation report's post-restart acceptance section, distinguished there
from this pre-deployment, isolated-data verification. If live rendering
could not be captured for any reason, that limitation is stated there
explicitly, not implied as passed.
