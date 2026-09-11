"""Task 118A Priority 3(c) -- dashboard_read.py's intelligence().card_delivery
must distinguish CARD ROWS sent from actual Telegram MESSAGES sent: a
DIGEST batch marks several card rows SENT under one shared attempt_id but
is exactly one Telegram message.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
from talonx_ingest.intelligence.delivery.pipeline import (
    SenderResult, enqueue_card, process_digest, process_pending,
)
from talonx_ops.dashboard_read import DashboardReadModel
from _delivery_helpers import make_card

UTC = timezone.utc
NOW = datetime(2026, 9, 11, 13, 0, 0, tzinfo=UTC)


class _Sender:
    def __init__(self):
        self.configured = True

    async def send(self, row):
        return SenderResult(ok=True, message_id=1)


def _enq_digest(ob, sym, acc, *, at):
    c, _ = make_card(symbol=sym, event_type=EventType.INSIDER_TRANSACTION,
                     accession=acc, on_watchlist=False, now=at)
    return enqueue_card(c, outbox=ob, now=at).row


def _enq_immediate(ob, sym, acc, *, at):
    # default event_type (EARNINGS_RESULTS) + on_watchlist=True -> HIGH/CRITICAL
    # band -> IMMEDIATE route (same construction test_task117_intel_delivery_
    # age_cutoff.py uses for its own IMMEDIATE-route fixtures).
    c, _ = make_card(symbol=sym, accession=acc, on_watchlist=True, now=at)
    row = enqueue_card(c, outbox=ob, now=at).row
    assert row.route == "IMMEDIATE"
    return row


def test_one_digest_of_three_cards_counts_as_one_message(tmp_path):
    home = tmp_path / ".talonx"
    home.mkdir()
    ledger = home / "ingestion_ledger.db"
    ob = DeliveryOutbox(ledger)
    for i, sym in enumerate(["AFL", "ORCL", "JPM"]):
        _enq_digest(ob, sym, f"0001225208-26-00772{i}", at=NOW - timedelta(minutes=10 - i))
    asyncio.run(process_digest(ob, _Sender(), mode="enabled",
                               interval_seconds=6 * 3600.0, now=NOW))
    ob._conn.close() if hasattr(ob, "_conn") else None

    model = DashboardReadModel(home=home, exp_home=home / "experimental",
                               intel_ledger=ledger, now=NOW, check_processes=False)
    cd = model.intelligence()["card_delivery"]
    assert cd["sent_today"] == 3           # 3 card rows
    assert cd["messages_sent_today"] == 1  # exactly 1 Telegram message


def test_immediate_and_digest_sends_count_messages_correctly(tmp_path):
    home = tmp_path / ".talonx"
    home.mkdir()
    ledger = home / "ingestion_ledger.db"
    ob = DeliveryOutbox(ledger)
    _enq_immediate(ob, "TSLA", "0001318605-26-000099", at=NOW - timedelta(minutes=30))
    for i, sym in enumerate(["AFL", "ORCL"]):
        _enq_digest(ob, sym, f"0001225208-26-00773{i}", at=NOW - timedelta(minutes=10 - i))
    # route="IMMEDIATE" matches the real runner (intelligence/service/runner.py
    # deliver_cycle) -- DIGEST-route rows are drained only by process_digest.
    asyncio.run(process_pending(ob, _Sender(), mode="enabled", route="IMMEDIATE", now=NOW))
    asyncio.run(process_digest(ob, _Sender(), mode="enabled",
                               interval_seconds=6 * 3600.0, now=NOW))

    model = DashboardReadModel(home=home, exp_home=home / "experimental",
                               intel_ledger=ledger, now=NOW, check_processes=False)
    cd = model.intelligence()["card_delivery"]
    assert cd["sent_today"] == 3           # 1 immediate + 2 digest-aggregated rows
    assert cd["messages_sent_today"] == 2  # 1 immediate message + 1 digest message
