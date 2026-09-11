"""Task 118A Priority 3(a)/(b) -- the Intelligence digest message (sent
with parse_mode=None) must never embed literal HTML markup pulled from an
individual card's own parse_mode="HTML" text, and must not describe a
batch it is actively sending as "held" (that wording is reserved for rows
genuinely still PENDING elsewhere in the outbox).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox, STATE_SENT
from talonx_ingest.intelligence.delivery.pipeline import (
    SenderResult, enqueue_card, process_digest, _digest_row_summary,
)
from _delivery_helpers import make_card

UTC = timezone.utc
NOW = datetime(2026, 9, 11, 13, 0, 0, tzinfo=UTC)
INTERVAL = 6 * 3600.0


class _Sender:
    def __init__(self):
        self.sent = []
        self.configured = True

    async def send(self, row):
        self.sent.append(row.text)
        return SenderResult(ok=True, message_id=999)


def _enq(ob, sym, acc, *, at):
    c, _ = make_card(symbol=sym, event_type=EventType.INSIDER_TRANSACTION,
                     accession=acc, on_watchlist=False, now=at)
    r = enqueue_card(c, outbox=ob, now=at).row
    assert r.route == "DIGEST"
    return r


def test_digest_message_text_never_contains_html_tags(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    _enq(ob, "AFL", "0001225208-26-007727", at=NOW - timedelta(minutes=10))
    _enq(ob, "ORCL", "0001193125-26-387905", at=NOW - timedelta(minutes=5))
    snd = _Sender()
    asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL, now=NOW))
    assert len(snd.sent) == 1
    text = snd.sent[0]
    assert "<b>" not in text and "</b>" not in text and "<" not in text and ">" not in text


def test_digest_wording_says_delivered_not_held(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    _enq(ob, "AFL", "0001225208-26-007727", at=NOW - timedelta(minutes=10))
    snd = _Sender()
    asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL, now=NOW))
    text = snd.sent[0]
    assert "held event" not in text
    assert "1 event(s) in this digest" in text


def test_digest_line_uses_real_event_facts_not_invented_ones(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    row = _enq(ob, "AFL", "0001225208-26-007727", at=NOW - timedelta(minutes=10))
    summary = _digest_row_summary(row)
    assert "Insider" in summary or "insider" in summary.lower()  # real event-type label
    assert "enqueued " in summary
    # no significance/recommendation language invented:
    for banned in ("recommend", "significant because", "likely to", "expect"):
        assert banned not in summary.lower()


def test_digest_still_marks_every_claimed_row_sent(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    ids = [_enq(ob, s, f"0001225208-26-00772{i}", at=NOW - timedelta(minutes=10 - i)).delivery_id
           for i, s in enumerate(["AFL", "JPM", "ADP"])]
    snd = _Sender()
    r = asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL, now=NOW))
    assert r.delivered == 3
    for did in ids:
        assert ob.get(did).state == STATE_SENT
