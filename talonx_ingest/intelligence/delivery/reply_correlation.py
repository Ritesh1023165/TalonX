"""
talonx_ingest.intelligence.delivery.reply_correlation
=======================================================
Task 138 Workstream 3 -- reply-for-details, deterministic, no external
LLM. Correlates an inbound Telegram reply (chat identity, already
enforced by the listener before this module is ever reached, plus the
Telegram message ID being replied to) against the durable EXISTING
``intelligence_delivery`` table -- reuses its ``transport_message_id``
column (set by ``mark_sent``/``mark_digest_sent``), no new schema.

A single-card send stores the bare numeric Telegram message id in
``transport_message_id``; a digest send stores ``"digest:<digest_id>:
<message_id>"`` across every row that was part of it -- so one Telegram
message can, and for a digest routinely does, map to MULTIPLE delivery
rows/events. Both are resolved by the SAME lookup.
"""
from __future__ import annotations

from dataclasses import dataclass

_DETAILS_TRIGGER_WORDS = {"details", "detail", "info"}
_MAX_REPLY_CHARS = 3500          # safely under Telegram's 4096 cap, room for the item-index footer
_MAX_ITEMS_PER_REPLY = 6


def is_details_request(text: str | None) -> bool:
    if not text:
        return False
    t = text.strip().strip('."!').lower()
    if t in _DETAILS_TRIGGER_WORDS:
        return True
    # "details 2" -- an indexed follow-up on a multi-event reply.
    parts = t.split()
    return bool(parts) and parts[0] in _DETAILS_TRIGGER_WORDS


def _requested_index(text: str) -> int | None:
    parts = text.strip().split()
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def find_delivery_rows_for_message(outbox, telegram_message_id) -> list:
    """Every ``intelligence_delivery`` row this Telegram message id maps
    to -- a bare match (single-card send) or a ``...:<id>`` suffix match
    (digest send). Oldest-enqueued first, for a stable index order."""
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


def _one_item_detail(ctx: DetailsContext) -> list[str]:
    row, ev, sig = ctx.row, ctx.event, ctx.significance
    lines: list[str] = [f"{row.symbol} -- {row.route} disposition (delivery {row.delivery_id[:8]}...)"]

    if ev is not None:
        lines.append(f"Accession: {ev.accession}")
        if getattr(ev, "filing_index_url", None):
            lines.append(f"Filing link: {ev.filing_index_url}")
        lines.append(f"Source accepted: {_fmt_ts(getattr(ev, 'accepted_at_utc', None))}")
    else:
        lines.append("Source event record unavailable -- accession/link cannot be shown "
                     "(data limitation, not guessed).")

    lines.append(f"Delivery enqueued: {_fmt_ts(row.enqueued_at_utc)}")
    lines.append(f"Delivery sent: {_fmt_ts(row.sent_at_utc)}")

    lines.append("")
    lines.append("Source facts (from the significance engine, not interpretation):")
    if sig is not None and sig.reasons:
        for r in sig.reasons:
            lines.append(f"  - {r.description}  [{r.code}]")
    else:
        lines.append("  (no persisted significance reasons found for this event)")

    lines.append("")
    lines.append("Original notification text sent to you (HTML markup stripped for this "
                 "plain-text reply -- wording/facts unchanged):")
    lines.append(_strip_html(row.text))

    lines.append("")
    lines.append("Data limitations: aggregation windows/insider-activity detail beyond what the "
                 "original card showed are not separately re-derived here -- the significance "
                 "reasons above are the SAME ones already used to decide this card's routing.")
    return lines


def build_details_response(contexts: list[DetailsContext], *, requested_index: int | None = None) -> str:
    if not contexts:
        return ("This message isn't recognized as a TalonX informational card, or it predates "
                "durable reply correlation -- I can't truthfully identify which card this was, "
                "so I won't guess. (No reply for a card sent before this feature existed.)")

    if len(contexts) == 1 or requested_index is not None:
        idx = (requested_index - 1) if requested_index else 0
        if idx < 0 or idx >= len(contexts):
            return (f"This message referenced {len(contexts)} event(s) -- reply "
                    f"\"details {1}\" through \"details {len(contexts)}\" for a specific one.")
        text = "\n".join(_one_item_detail(contexts[idx]))
        if len(contexts) > 1:
            text = f"[Item {idx + 1} of {len(contexts)}]\n\n" + text
        return text[:_MAX_REPLY_CHARS]

    # multi-event message, no specific index requested -> a compact
    # indexed summary; every constituent event/fact is still individually
    # addressable via "details N", nothing is collapsed into an invented
    # combined total.
    lines = [f"This message covered {len(contexts)} event(s):"]
    for i, ctx in enumerate(contexts[:_MAX_ITEMS_PER_REPLY], start=1):
        ev = ctx.event
        acc = getattr(ev, "accession", "unknown accession") if ev is not None else "unknown accession"
        lines.append(f"  {i}. {ctx.row.symbol} -- {acc}")
    if len(contexts) > _MAX_ITEMS_PER_REPLY:
        lines.append(f"  ... and {len(contexts) - _MAX_ITEMS_PER_REPLY} more")
    lines.append("")
    lines.append(f'Reply "details N" (e.g. "details 1") for a specific item\'s full facts, '
                f"source link, and timestamps.")
    return "\n".join(lines)[:_MAX_REPLY_CHARS]


def resolve_details_reply(
    text: str, reply_to_message_id, *, outbox, events_store, significance_store,
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
    contexts = []
    for row in rows:
        ev = None
        sig = None
        try:
            ev = events_store.get_event(row.event_id)
        except Exception:  # noqa: BLE001
            ev = None
        try:
            sig = significance_store.get_for_event(row.event_id)
        except Exception:  # noqa: BLE001
            sig = None
        contexts.append(DetailsContext(row=row, event=ev, significance=sig))

    return build_details_response(contexts, requested_index=_requested_index(text))


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
            contexts = [
                DetailsContext(row=row, event=reader.get_event(row.event_id),
                              significance=reader.get_significance(row.event_id))
                for row in rows
            ]
            return build_details_response(contexts, requested_index=_requested_index(text))
        except _sqlite3.OperationalError:
            return _LOCK_FALLBACK
        except Exception as exc:  # noqa: BLE001 -- a resolver bug must never kill the poller
            if on_error is not None:
                on_error(exc)
            return None

    return reader, message_resolver


def make_telegram_message_resolver(*, outbox, events_store, significance_store):
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
            significance_store=significance_store,
        )

    return _resolver
