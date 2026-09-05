"""
tests/test_delivery_pipeline.py
-------------------------------
Task 96F -- enqueue + durable drain: dedup, updates, retry/restart,
rate-limit, dry-run, priority order, execution independence, claim-safety
fail-closed.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import pkgutil

import pytest

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.delivery.claim_safety import PredictiveLanguageError
from talonx_ingest.intelligence.delivery.identity import delivery_id
from talonx_ingest.intelligence.delivery.observability import DeliveryMetrics
from talonx_ingest.intelligence.delivery.outbox import (
    STATE_FAILED,
    STATE_PENDING,
    STATE_SENT,
    DeliveryOutbox,
)
from talonx_ingest.intelligence.delivery.pipeline import (
    NullSender,
    RecordingSender,
    enqueue_card,
    process_pending,
)
from _delivery_helpers import make_card, mk_comparison, mk_event


def _drain(ob, sender, **kw):
    return asyncio.run(process_pending(ob, sender, **kw))


def test_enqueue_then_drain_delivers_once(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m = DeliveryMetrics()
    card, wc = make_card(on_watchlist=True)
    r = enqueue_card(card, outbox=ob, metrics=m)
    assert r.disposition == "NEW"
    snd = RecordingSender()
    res = _drain(ob, snd, metrics=m)
    assert res.delivered == 1 and len(snd.sent) == 1
    assert ob.get(r.row.delivery_id).state == STATE_SENT
    # re-enqueue same card -> suppressed, nothing new to drain
    enqueue_card(card, outbox=ob, metrics=m)
    assert _drain(ob, snd, metrics=m).attempted == 0
    assert m.dedup_suppressed >= 1
    ob.close()


def test_repeated_ingestion_never_double_sends(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    card, wc = make_card()
    for _ in range(5):
        enqueue_card(card, outbox=ob)
    snd = RecordingSender()
    _drain(ob, snd)
    for _ in range(5):
        enqueue_card(card, outbox=ob)
    _drain(ob, snd)
    assert len(snd.sent) == 1
    ob.close()


def test_retry_on_transient_then_succeeds(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m = DeliveryMetrics()
    card, _ = make_card()
    did = delivery_id(card.alert_id)
    enqueue_card(card, outbox=ob, metrics=m)
    snd = RecordingSender(fail_times=2, retry_after_seconds=0)
    r1 = _drain(ob, snd, metrics=m)
    assert r1.retried == 1 and r1.delivered == 0
    assert ob.get(did).state == STATE_PENDING and ob.get(did).attempts == 1
    _drain(ob, snd, metrics=m)      # attempt 2 -> fail
    r3 = _drain(ob, snd, metrics=m)  # attempt 3 -> success
    assert r3.delivered == 1
    assert ob.get(did).state == STATE_SENT
    assert m.retries == 2 and m.delivered == 1
    ob.close()


def test_rate_limit_uses_retry_after(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    card, _ = make_card()
    did = delivery_id(card.alert_id)
    enqueue_card(card, outbox=ob)
    snd = RecordingSender(fail_times=1, fail_error="RetryAfter 30", retry_after_seconds=30)
    _drain(ob, snd)
    row = ob.get(did)
    assert row.state == STATE_PENDING and row.next_retry_at_utc is not None
    # not yet due -> drain skips it
    assert _drain(ob, snd).attempted == 0
    ob.close()


def test_permanent_failure_goes_terminal(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m = DeliveryMetrics()
    card, _ = make_card()
    did = delivery_id(card.alert_id)
    enqueue_card(card, outbox=ob, metrics=m)
    snd = RecordingSender(fail_times=99, fail_error="InvalidToken (non-retryable)", permanent=True)
    res = _drain(ob, snd, metrics=m)
    assert res.failed == 1
    assert ob.get(did).state == STATE_FAILED
    assert m.failures == 1
    ob.close()


def test_restart_between_enqueue_and_send_loses_nothing(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    card, _ = make_card()
    did = delivery_id(card.alert_id)
    enqueue_card(card, outbox=ob)
    ob.close()  # "crash" before the drain

    ob2 = DeliveryOutbox(ledger_path)
    snd = RecordingSender()
    assert _drain(ob2, snd).delivered == 1
    assert ob2.get(did).state == STATE_SENT
    ob2.close()


def test_dry_run_does_not_send_externally(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    card, _ = make_card()
    did = delivery_id(card.alert_id)
    enqueue_card(card, outbox=ob)
    real = RecordingSender()
    res = _drain(ob, real, dry_run=True)
    assert res.delivered == 1                 # lifecycle exercised
    assert real.sent == []                    # ...but the real sender was untouched
    assert ob.get(did).state == STATE_SENT
    ob.close()


def test_not_configured_leaves_rows_pending(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    card, _ = make_card()
    did = delivery_id(card.alert_id)
    enqueue_card(card, outbox=ob)
    snd = RecordingSender(configured=False)
    res = _drain(ob, snd)
    assert res.skipped_not_configured and res.attempted == 0
    assert ob.get(did).state == STATE_PENDING   # nothing consumed, nothing lost
    ob.close()


def test_update_requires_opt_in(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m = DeliveryMetrics()
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    card0, _ = make_card(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=())
    enqueue_card(card0, outbox=ob, metrics=m)
    _drain(ob, RecordingSender(), metrics=m)

    # a later comparison arrives -> materially changed render
    wc = None
    from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed
    wc = build_what_changed(mk_comparison(event=ev, rf_diff=0.7, revenue_rel_delta=0.5))
    card1, _ = make_card(
        event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(),
        comparison=mk_comparison(event=ev, rf_diff=0.7, revenue_rel_delta=0.5),
    )

    r_noupd = enqueue_card(card1, outbox=ob, what_changed=wc, metrics=m, allow_update=False)
    assert r_noupd.disposition == "SUPPRESSED"

    r_upd = enqueue_card(card1, outbox=ob, what_changed=wc, metrics=m, allow_update=True)
    assert r_upd.disposition == "UPDATE"
    res = _drain(ob, RecordingSender(), metrics=m)
    assert res.delivered == 1 and m.updates_sent == 1
    ob.close()


def test_time_passing_alone_is_not_an_update(ledger_path):
    from datetime import timedelta
    from _delivery_helpers import NOW

    ob = DeliveryOutbox(ledger_path)
    card, _ = make_card(age_hours=1, now=NOW)
    enqueue_card(card, outbox=ob, now=NOW)
    _drain(ob, RecordingSender(), now=NOW)
    # same card, evaluated later (recency reason may differ) -> still suppressed
    card_later, _ = make_card(age_hours=1, now=NOW + timedelta(hours=10))
    r = enqueue_card(card_later, outbox=ob, allow_update=True, now=NOW + timedelta(hours=10))
    assert r.disposition in ("SUPPRESSED",)
    ob.close()


def test_bad_language_fails_closed_before_persist(ledger_path, monkeypatch):
    ob = DeliveryOutbox(ledger_path)
    m = DeliveryMetrics()
    card, _ = make_card()
    import talonx_ingest.intelligence.delivery.pipeline as P

    real = P.render_card(card)
    tainted = real.model_copy(update={"text": real.text + "\nStrong buy signal — bullish outlook."})
    monkeypatch.setattr(P, "render_card", lambda *a, **k: tainted)

    with pytest.raises(PredictiveLanguageError):
        enqueue_card(card, outbox=ob, metrics=m)
    assert ob.query() == []                  # nothing persisted
    assert m.claim_safety_rejections == 1
    ob.close()


# ---------------------------------------------------------------------------
# execution independence (Phase 20) -- static import audit
# ---------------------------------------------------------------------------
_FORBIDDEN_ROOTS = (
    "talonx_quant",
    "talonx_core.decision",
    "talonx_paper",
    "talonx_piv",
    "redis",
    "talonx_dispatch.consumer",
    "talonx_dispatch.app",
    "talonx_dispatch.formatter",
    "talonx_dispatch.schemas",
    "talonx_dispatch.telegram_listener",
)


def _imports(path):
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module)
    return mods


def test_delivery_package_has_no_execution_or_quant_import():
    import talonx_ingest.intelligence.delivery as pkg

    walked = 0
    for mod in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        m = importlib.import_module(mod.name)
        for imp in _imports(m.__file__):
            for bad in _FORBIDDEN_ROOTS:
                assert not imp.startswith(bad), f"{mod.name} imports {imp!r}"
        walked += 1
    assert walked >= 8


def test_only_pipeline_may_touch_telegram_transport():
    import talonx_ingest.intelligence.delivery as pkg

    for mod in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        m = importlib.import_module(mod.name)
        imps = _imports(m.__file__)
        touches_transport = any(
            i.startswith(("talonx_dispatch.telegram_client", "talonx_dispatch.config"))
            for i in imps
        )
        if touches_transport:
            assert mod.name.endswith(".pipeline"), mod.name
