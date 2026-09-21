"""
talonx_ingest.intelligence.delivery.reply_correlation
=======================================================
Task 138 Workstream 3, corrected Task 140 -- reply-for-details,
deterministic, no external LLM. Correlates an inbound Telegram reply
(chat identity, already enforced by the listener before this module is
ever reached, plus the Telegram message ID being replied to) against the
durable EXISTING ``intelligence_delivery`` table -- reuses its
``transport_message_id`` column (set by ``mark_sent``/
``mark_digest_sent``), no new schema beyond one additive column
(``digest_item_ordinal``, see ``outbox.py``).

A single-card send stores the bare numeric Telegram message id in
``transport_message_id``; a digest send stores ``"digest:<digest_id>:
<message_id>"`` across every row that was part of it -- so one Telegram
message can, and for a digest routinely does, map to MULTIPLE delivery
rows/events. Both are resolved by the SAME lookup.

Task 140 fix -- ordering: a real operator round trip (replying "details"
and "details 2" to a real historical digest) proved the index this
module returned did NOT match the digest's own displayed order, and
"details 2" resolved to a different event than the digest's own second
line. Root cause: this module ordered rows by ``enqueued_at_utc``
(database insertion order) while the digest renderer
(``pipeline.py::digest_display_order``) orders by
``(band_rank, symbol, event_id)`` -- two independently-derived, silently
disagreeing orders. Fixed by using the SAME shared sort function, and by
persisting each row's actual sent-order position
(``digest_item_ordinal``) at send time going forward so future replies
resolve against a stored fact, not a re-derived one.
"""
from __future__ import annotations

from dataclasses import dataclass

_DETAILS_TRIGGER_WORDS = {"details", "detail", "info"}
_MAX_REPLY_CHARS = 3500          # safely under Telegram's 4096 cap, room for the item-index footer
_INDEX_ITEMS_PER_PAGE = 20        # a numbered index line is short; this comfortably fits _MAX_REPLY_CHARS


def is_details_request(text: str | None) -> bool:
    if not text:
        return False
    t = text.strip().strip('."!').lower()
    if t in _DETAILS_TRIGGER_WORDS:
        return True
    # "details 2" / "details page 2" -- an indexed or paged follow-up.
    parts = t.split()
    return bool(parts) and parts[0] in _DETAILS_TRIGGER_WORDS


def _requested_index(text: str) -> int | None:
    parts = text.strip().split()
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def _requested_page(text: str) -> int | None:
    parts = text.strip().lower().split()
    if len(parts) == 3 and parts[1] == "page" and parts[2].isdigit():
        return int(parts[2])
    return None


def _digest_band_rank(band) -> int:
    from talonx_ingest.intelligence.delivery.pipeline import _DIGEST_BAND_RANK

    return _DIGEST_BAND_RANK.get(band, 4)


def _order_rows(rows: list) -> tuple[list, bool]:
    """Returns ``(ordered_rows, order_is_verified)``. If every row in
    this message carries a stored ``digest_item_ordinal`` (Task 140's
    new column -- set for every digest sent going forward), that IS the
    literal, durable, originally-sent order -- ``order_is_verified=
    True``. Otherwise (a single-card send, where order is moot; or a
    digest sent before this column existed), falls back to the SAME
    deterministic sort the real digest renderer uses
    (``pipeline.digest_display_order``) -- since band/symbol/event_id
    are all immutable on a row once persisted, this reconstruction is
    provably the same order the renderer would have produced, but is
    labelled ``order_is_verified=False`` because it is a reconstruction,
    not a stored fact, and this module never silently claims otherwise."""
    if len(rows) <= 1:
        return list(rows), True
    if all(getattr(r, "digest_item_ordinal", None) is not None for r in rows):
        return sorted(rows, key=lambda r: r.digest_item_ordinal), True
    from talonx_ingest.intelligence.delivery.pipeline import digest_display_order

    return digest_display_order(rows), False


def find_delivery_rows_for_message(outbox, telegram_message_id) -> list:
    """Every ``intelligence_delivery`` row this Telegram message id maps
    to -- a bare match (single-card send) or a ``...:<id>`` suffix match
    (digest send). Returned in DATABASE order (enqueue time); callers
    that need display order must call ``_order_rows`` themselves -- kept
    separate so this function's contract (which rows) stays independent
    of ordering policy."""
    mid = str(telegram_message_id)
    rows = outbox._conn.execute(
        "SELECT * FROM intelligence_delivery WHERE transport_message_id = ? "
        "OR transport_message_id LIKE ? ORDER BY enqueued_at_utc ASC",
        (mid, f"%:{mid}"),
    ).fetchall()
    return [outbox._row(r) for r in rows]


@dataclass(frozen=True)
class DetailsContext:
    """Everything ``build_details_response`` needs for ONE delivery row,
    pulled fresh from the already-persisted, durable stores -- never
    recomputed/guessed. Any field that could not be resolved is left
    ``None`` and reported as a limitation, never silently omitted."""
    row: object                    # DeliveryRow
    event: object | None = None    # TextEvent
    significance: object | None = None   # InformationSignificance
    insider_filing: object | None = None  # raw insider_filings row (issuer_cik, source_reference)


def _strip_html(text: str) -> str:
    """Best-effort: the stored card text is HTML (parse_mode=HTML), this
    module replies with parse_mode=None (see the module docstring's own
    HTML/Markdown-escaping note) to avoid a malformed-markup send failure
    on uncontrolled, SEC-sourced text -- so tags are stripped for
    readability, and HTML entities are unescaped, rather than shown raw."""
    import html
    import re

    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _fmt_ts(dt) -> str:
    if dt is None:
        return "unknown"
    dt = dt if dt.tzinfo else dt.replace(tzinfo=__import__("datetime").timezone.utc)
    return dt.astimezone(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _resolve_source_link(ev, insider_filing) -> tuple[str | None, str]:
    """Task 140: NEVER infer an issuer's CIK from an accession number's
    own prefix -- proven, with real production data, to identify the
    FILER/owner (e.g. an individual insider's own EDGAR filer account),
    not the issuer, whenever an agent or the insider themselves submits
    the filing (a real example: accession prefix 0001689315 is the
    filing insider's own CIK; the issuer Apollo Global Management's real
    CIK is 0001858681 -- entirely different numbers).

    Preference order, every one already a VALIDATED, persisted fact, never
    constructed from a guess:
    1. ``insider_filing.source_reference`` (insider_filings table -- the
       real issuer_cik-based SEC Archives URL, stored at ingestion time
       directly from the parsed Form 4/5 XML's own issuer identity).
    2. ``ev.filing_index_url`` (text_events -- populated for filing types
       whose ingestion path resolves a real index URL, e.g. 8-K/10-Q).
    3. Neither -- returns (None, "Source link unavailable") rather than
       guessing."""
    if insider_filing is not None:
        ref = getattr(insider_filing, "source_reference", None)
        if ref:
            url = ref.split(":", 1)[1] if ref.startswith("SEC_EDGAR_ARCHIVES:") else ref
            if url:
                return url, "verified (insider filing issuer CIK)"
    url = getattr(ev, "filing_index_url", None) if ev is not None else None
    if url:
        return url, "verified (filing index)"
    return None, "Source link unavailable (no validated issuer-CIK-based URL on record -- " \
                 "never guessed from the accession number's own prefix, which can identify " \
                 "a filing agent or the insider rather than the issuer)."


# Selection-reason codes: WHY the system chose to surface/route this event
# -- never a fact stated BY the filing itself. Kept visually separate from
# genuine filing facts (Task 140).
_SELECTION_REASON_CODES = frozenset({
    "EVENT_TYPE_BASE", "ON_WATCHLIST", "WATCHLIST_PINNED", "MULTI_ITEM_8K",
})


def _one_item_detail(ctx: DetailsContext, *, item_no: int | None = None) -> list[str]:
    row, ev, sig = ctx.row, ctx.event, ctx.significance
    lines: list[str] = [f"{row.symbol} -- {row.route} disposition (delivery {row.delivery_id[:8]}...)"]

    if ev is not None:
        lines.append(f"Accession: {ev.accession}")
    elif ctx.insider_filing is not None:
        lines.append(f"Accession: {getattr(ctx.insider_filing, 'accession', 'unknown')}")
    else:
        lines.append("Source event record unavailable -- accession cannot be shown "
                     "(data limitation, not guessed).")

    link, link_note = _resolve_source_link(ev, ctx.insider_filing)
    if link:
        lines.append(f"Filing link: {link}")
    else:
        lines.append(link_note)

    src_accepted = getattr(ev, "accepted_at_utc", None) if ev is not None else None
    if src_accepted is None and ctx.insider_filing is not None:
        src_accepted = getattr(ctx.insider_filing, "accepted_at_utc", None)
    lines.append(f"Source accepted: {_fmt_ts(src_accepted)}")
    lines.append(f"Delivery enqueued: {_fmt_ts(row.enqueued_at_utc)}")
    lines.append(f"Delivery sent: {_fmt_ts(row.sent_at_utc)}")

    lines.append("")
    facts = []
    reasons = []
    if sig is not None and sig.reasons:
        for r in sig.reasons:
            entry = f"  - {r.description}  [{r.code}]"
            (reasons if r.code in _SELECTION_REASON_CODES else facts).append(entry)
    lines.append("Facts from the filing (computed by the significance/insider engines, "
                 "not interpretation):")
    lines.extend(facts if facts else ["  (no persisted filing-level facts found for this event)"])
    if reasons:
        lines.append("")
        lines.append("Why this was selected (system routing reason, not a fact stated by "
                     "the filing itself):")
        lines.extend(reasons)

    lines.append("")
    if row.route == "DIGEST":
        # Task 140: the OPERATOR'S ACTUAL MESSAGE for a digest item was
        # the compact aggregated line, never row.text (a full individual
        # card this row would have used if sent standalone) -- showing
        # row.text and calling it "the original text sent to you" was a
        # confirmed, real mislabeling. Reconstruct the ACTUAL digest line
        # via the SAME function the real digest renderer used.
        try:
            from talonx_ingest.intelligence.delivery.pipeline import _digest_row_summary

            actual_line = f"- {row.symbol}: {_digest_row_summary(row)}"
        except Exception:  # noqa: BLE001
            actual_line = "(could not be reconstructed)"
        lines.append(f"The digest line you actually received for this item:")
        lines.append(actual_line)
        lines.append("")
        lines.append("Stored supporting card (fuller detail than the compact digest line above "
                     "-- this fuller text was NOT itself sent to you; HTML markup stripped for "
                     "this plain-text reply, wording/facts unchanged from what is stored):")
        lines.append(_strip_html(row.text))
    else:
        lines.append("Original message text sent to you (HTML markup stripped for this "
                     "plain-text reply -- wording/facts unchanged):")
        lines.append(_strip_html(row.text))

    lines.append("")
    lines.append("Data limitations: aggregation windows/insider-activity detail beyond what the "
                 "original card showed are not separately re-derived here -- the facts above are "
                 "the SAME ones already used to decide this card's routing, evaluated as of the "
                 "original send, not re-computed against any later enrichment update.")
    return lines


def _index_lines(contexts: list[DetailsContext], *, order_verified: bool,
                 page: int | None = None) -> str:
    n = len(contexts)
    order_note = ("in the exact order you received them" if order_verified
                 else "reconstructed from the original renderer's own ordering rule -- this "
                      "message predates durable per-item order tracking, so this is a verified "
                      "deterministic reconstruction, not a stored record; see 'details N' below")
    header = [f"This message covered {n} event(s), numbered below {order_note}:"]

    total_pages = max(1, (n + _INDEX_ITEMS_PER_PAGE - 1) // _INDEX_ITEMS_PER_PAGE)
    pg = page or 1
    pg = min(max(pg, 1), total_pages)
    start = (pg - 1) * _INDEX_ITEMS_PER_PAGE
    end = min(n, start + _INDEX_ITEMS_PER_PAGE)

    lines = list(header)
    if total_pages > 1:
        lines.append(f"Page {pg} of {total_pages} (items {start + 1}-{end} of {n}):")
    for i in range(start, end):
        ctx = contexts[i]
        ev = ctx.event
        acc = (getattr(ev, "accession", None) if ev is not None else None) \
            or (getattr(ctx.insider_filing, "accession", None) if ctx.insider_filing is not None else None) \
            or "unknown accession"
        lines.append(f"  {i + 1}. {ctx.row.symbol} -- {acc}")
    lines.append("")
    lines.append(f'Reply "details N" (e.g. "details 1") for a specific item\'s full facts, '
                f"source link, and timestamps.")
    if total_pages > 1:
        nxt = pg + 1 if pg < total_pages else 1
        lines.append(f'Reply "details page {nxt}" for the next page (items are numbered '
                     f"consistently across pages and after a restart).")
    return "\n".join(lines)[:_MAX_REPLY_CHARS]


def build_details_response(
    contexts: list[DetailsContext], *, requested_index: int | None = None,
    requested_page: int | None = None, order_verified: bool = True,
) -> str:
    if not contexts:
        return ("This message isn't recognized as a TalonX informational card, or it predates "
                "durable reply correlation -- I can't truthfully identify which card this was, "
                "so I won't guess. (No reply for a card sent before this feature existed.)")

    if len(contexts) == 1 or requested_index is not None:
        idx = (requested_index - 1) if requested_index else 0
        if idx < 0 or idx >= len(contexts):
            return (f"This message referenced {len(contexts)} event(s) -- reply "
                    f"\"details {1}\" through \"details {len(contexts)}\" for a specific one, "
                    f'or "details" alone to see the index again.')
        text = "\n".join(_one_item_detail(contexts[idx], item_no=idx + 1))
        if len(contexts) > 1:
            order_tag = "" if order_verified else " (order reconstructed -- see 'details' index)"
            text = f"[Item {idx + 1} of {len(contexts)}{order_tag}]\n\n" + text
        return text[:_MAX_REPLY_CHARS]

    # multi-event message, no specific index requested -> a compact,
    # FULLY-navigable indexed summary; every constituent event/fact is
    # still individually addressable via "details N", nothing is
    # collapsed into an invented combined total, and nothing is hidden
    # behind an "...and N more" dead end.
    return _index_lines(contexts, order_verified=order_verified, page=requested_page)


def resolve_details_reply(
    text: str, reply_to_message_id, *, outbox, events_store, significance_store,
    insider_store=None,
) -> str | None:
    """The top-level, deterministic entry point. Returns ``None`` if
    ``text`` is not a details request at all (so the listener falls
    through to whatever else it would otherwise do) -- a truthful,
    explicit "unavailable" STRING (never ``None``) once it IS recognized
    as a details request but nothing correlates, so the operator gets an
    honest answer rather than silence."""
    if not is_details_request(text):
        return None
    if reply_to_message_id is None:
        return ('Reply "details" directly on a specific TalonX card (use Telegram\'s '
                "own Reply feature) so I know which one you mean.")

    rows = find_delivery_rows_for_message(outbox, reply_to_message_id)
    ordered_rows, order_verified = _order_rows(rows)
    contexts = []
    for row in ordered_rows:
        ev = None
        sig = None
        insider_filing = None
        try:
            ev = events_store.get_event(row.event_id)
        except Exception:  # noqa: BLE001
            ev = None
        try:
            sig = significance_store.get_for_event(row.event_id)
        except Exception:  # noqa: BLE001
            sig = None
        if insider_store is not None:
            try:
                insider_filing = insider_store.get_filing_for_event(row.event_id)
            except Exception:  # noqa: BLE001
                insider_filing = None
        contexts.append(DetailsContext(row=row, event=ev, significance=sig,
                                       insider_filing=insider_filing))

    return build_details_response(contexts, requested_index=_requested_index(text),
                                  requested_page=_requested_page(text),
                                  order_verified=order_verified)


# ---------------------------------------------------------------------
# Production wiring: a SINGLE read-only connection to the SAME
# ingestion_ledger.db Intelligence owns/writes -- mirrors the EXACT
# established pattern talonx_signals/reply.py already uses for
# Experimental's exp_alerts.db (file:...?mode=ro, no write path can ever
# exist from this side, a concurrent WAL writer is unaffected). No new
# process, no second poller -- Original's existing single
# TelegramReplyListener gains one more additive resolver.
# ---------------------------------------------------------------------
class _RORow:
    """Minimal attribute-access wrapper over a sqlite3.Row -- avoids
    depending on the full EventStore/SignificanceStore/DeliveryOutbox
    constructors (which run schema init/migrations) just to read."""

    def __init__(self, row):
        self._row = row

    def __getattr__(self, name):
        try:
            return self._row[name]
        except (IndexError, KeyError):
            return None


class _RODateRow(_RORow):
    """Same, but parses the standard ``..._at_utc`` ISO columns into
    ``datetime`` objects on access, matching what the real store classes
    already hand back."""

    _DATE_FIELDS = ("accepted_at_utc", "enqueued_at_utc", "sent_at_utc", "updated_at_utc")

    def __getattr__(self, name):
        v = super().__getattr__(name)
        if v and name in self._DATE_FIELDS:
            from datetime import datetime

            try:
                return datetime.fromisoformat(v)
            except ValueError:
                return v
        return v


class _ROReasonRow:
    def __init__(self, code, description):
        self.code = code
        self.description = description


class _ROSignificance:
    def __init__(self, reasons):
        self.reasons = reasons


class ReadOnlyIntelligenceReader:
    """Read-only access to ``ingestion_ledger.db`` for reply-correlation
    only -- ``file:...?mode=ro``, never opens for write."""

    def __init__(self, db_path):
        import sqlite3

        self.path = str(db_path)
        self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5.0)
        self._conn.row_factory = sqlite3.Row

    def find_delivery_rows_for_message(self, telegram_message_id) -> list:
        mid = str(telegram_message_id)
        rows = self._conn.execute(
            "SELECT * FROM intelligence_delivery WHERE transport_message_id = ? "
            "OR transport_message_id LIKE ? ORDER BY enqueued_at_utc ASC",
            (mid, f"%:{mid}"),
        ).fetchall()
        return [_RODateRow(r) for r in rows]

    def get_event(self, event_id: str):
        r = self._conn.execute(
            "SELECT * FROM text_events WHERE event_id=?", (event_id,)
        ).fetchone()
        return _RODateRow(r) if r is not None else None

    def get_significance(self, event_id: str):
        r = self._conn.execute(
            "SELECT reasons_json FROM event_significance WHERE event_id=? "
            "ORDER BY evaluated_at_utc DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if r is None:
            return None
        import json

        try:
            reasons = [_ROReasonRow(x.get("code"), x.get("description"))
                      for x in json.loads(r["reasons_json"] or "[]")]
        except Exception:  # noqa: BLE001
            reasons = []
        return _ROSignificance(reasons)

    def get_filing_for_event(self, event_id: str):
        """Task 140: the validated, issuer-CIK-based insider filing
        record for an INSIDER_TRANSACTION event, if one exists --
        ``insider_filings`` is populated directly from the parsed Form
        4/5 XML's own issuer identity, never inferred from the
        accession's own prefix (which can be a filing agent's or the
        insider's own CIK, a real, confirmed mismatch in production
        data)."""
        try:
            r = self._conn.execute(
                "SELECT accession, issuer_cik, accepted_at_utc, source_reference "
                "FROM insider_filings WHERE event_id=?", (event_id,),
            ).fetchone()
        except Exception:  # noqa: BLE001 -- table may not exist on an older schema
            return None
        return _RODateRow(r) if r is not None else None

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


_LOCK_FALLBACK = ("TalonX details lookup is temporarily busy -- please try replying "
                  '"details" again in a moment.')


def build_intelligence_details_resolver(db_path=None, *, on_error=None):
    """Mirrors talonx_signals.reply.build_experimental_dxre_resolver's own
    contract exactly: returns ``(reader_handle, resolver)``; on any
    construction failure returns ``(None, None)`` and the caller simply
    does not register this resolver. Keep the handle to ``.close()`` it
    in the same shutdown ``finally`` block as the Experimental one."""
    import sqlite3 as _sqlite3

    try:
        if db_path is None:
            from pathlib import Path as _Path

            db_path = _Path.home() / ".talonx" / "ingestion_ledger.db"
        reader = ReadOnlyIntelligenceReader(db_path)
    except Exception as exc:  # noqa: BLE001 -- never block run_talonx.py startup
        if on_error is not None:
            on_error(exc)
        return None, None

    def message_resolver(message) -> str | None:
        try:
            text = getattr(message, "text", None)
            reply_to = getattr(message, "reply_to_message", None)
            reply_to_id = getattr(reply_to, "message_id", None) if reply_to is not None else None
            if not is_details_request(text):
                return None
            if reply_to_id is None:
                return ('Reply "details" directly on a specific TalonX card (use '
                        "Telegram's own Reply feature) so I know which one you mean.")
            rows = reader.find_delivery_rows_for_message(reply_to_id)
            ordered_rows, order_verified = _order_rows(rows)
            contexts = [
                DetailsContext(row=row, event=reader.get_event(row.event_id),
                              significance=reader.get_significance(row.event_id),
                              insider_filing=reader.get_filing_for_event(row.event_id))
                for row in ordered_rows
            ]
            return build_details_response(contexts, requested_index=_requested_index(text),
                                          requested_page=_requested_page(text),
                                          order_verified=order_verified)
        except _sqlite3.OperationalError:
            return _LOCK_FALLBACK
        except Exception as exc:  # noqa: BLE001 -- a resolver bug must never kill the poller
            if on_error is not None:
                on_error(exc)
            return None

    return reader, message_resolver


def make_telegram_message_resolver(*, outbox, events_store, significance_store, insider_store=None):
    """Builds a ``message_resolvers``-shaped callable (``Message -> str |
    None``) for ``talonx_dispatch.telegram_listener.TelegramReplyListener``
    -- extracts text + reply_to_message.message_id from the real inbound
    ``python-telegram-bot`` Message object and delegates to
    ``resolve_details_reply``. Never raises on a malformed/unexpected
    message shape -- returns None (falls through) instead."""

    def _resolver(message) -> str | None:
        try:
            text = getattr(message, "text", None)
            reply_to = getattr(message, "reply_to_message", None)
            reply_to_id = getattr(reply_to, "message_id", None) if reply_to is not None else None
        except Exception:  # noqa: BLE001
            return None
        return resolve_details_reply(
            text, reply_to_id, outbox=outbox, events_store=events_store,
            significance_store=significance_store, insider_store=insider_store,
        )

    return _resolver
