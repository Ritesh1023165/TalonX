"""Task 100A -- authoritative read-model / legacy-ownership adapter tests.

Confirms the semantic status states (ACTIVE / ZERO_ACTIVITY / NO_ACTIVE_PRODUCER
/ SUPERSEDED / STALE / UNKNOWN) are assigned truthfully, that the adapter has no
write side effects, that legacy numeric fields are preserved, that Original /
Experimental / PIV paper state stays isolated and un-double-counted, and that a
missing optional store degrades to UNKNOWN rather than crashing.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from talonx_ops.authoritative_read_model import (
    AuthoritativeReadModel,
    AuthorityStatus,
    DomainAuthority,
)

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
TODAY = "2026-09-15"


# --------------------------------------------------------------------------- #
# fixtures: a synthetic ~/.talonx tree
# --------------------------------------------------------------------------- #
def _db(path, ddl_rows):
    con = sqlite3.connect(path)
    for ddl, rows in ddl_rows:
        con.execute(ddl)
        if rows:
            ph = ",".join("?" * len(rows[0]))
            tbl = ddl.split("(")[0].split()[-1]
            con.executemany(f"INSERT INTO {tbl} VALUES ({ph})", rows)
    con.commit()
    con.close()


@pytest.fixture
def home(tmp_path):
    h = tmp_path / ".talonx"
    (h / "experimental").mkdir(parents=True)
    (h / "intelligence").mkdir(parents=True)
    return h


@pytest.fixture
def live_metadata(home):
    p = home / "runtime_metadata.json"
    p.write_text(json.dumps({"pid": 4242424242,
                             "started_at": (NOW - timedelta(minutes=5)).isoformat()}))
    return p


@pytest.fixture
def model_factory(home, live_metadata):
    def make(*, check_processes=False, now=NOW, metadata=None):
        return AuthoritativeReadModel(
            home=home, now=now, check_processes=check_processes,
            runtime_metadata_path=metadata or live_metadata,
        )
    return make


# --------------------------------------------------------------------------- #
# 1-5: the five semantic states
# --------------------------------------------------------------------------- #
def test_1_legacy_active_producer_active(home, model_factory):
    _db(home / "quant.db", [
        ("CREATE TABLE suppression_counts(date TEXT, reason TEXT, count INT)",
         [(TODAY, "LOW_VOLATILITY", 16000), (TODAY, "LOW_CONFLUENCE", 3)]),
        ("CREATE TABLE bar_buffer(x INT)", []),
    ])
    m = model_factory(check_processes=False)
    d = m.quant_funnel()
    assert d.status == AuthorityStatus.ACTIVE
    assert d.values["suppressions_today"] == 16003
    assert d.values["by_reason_today"]["LOW_VOLATILITY"] == 16000


def test_2_no_producer_yields_no_active_producer(home, tmp_path):
    _db(home / "brain.db", [("CREATE TABLE report_counts(date TEXT, category TEXT, count INT)", [])])
    dead_meta = home / "rm.json"
    dead_meta.write_text(json.dumps({"pid": 999999999,
                                     "started_at": (NOW - timedelta(days=2)).isoformat()}))
    m = AuthoritativeReadModel(home=home, now=NOW, check_processes=True, runtime_metadata_path=dead_meta)
    d = m.brain_reports()
    assert d.status == AuthorityStatus.NO_ACTIVE_PRODUCER
    assert d.values["reports_today"] == 0


def test_3_superseded_source_yields_superseded(home, model_factory):
    d = model_factory().filings_legacy_channel()
    assert d.status == AuthorityStatus.SUPERSEDED
    assert d.superseded_source == "talonx:filings:events"
    assert "ingestion_ledger.db" in d.authoritative_source
    assert "KEEP the channel" in d.note  # channel not deleted


def test_4_zero_real_activity_yields_zero_activity_when_producer_live(home, model_factory):
    _db(home / "brain.db", [("CREATE TABLE report_counts(date TEXT, category TEXT, count INT)", [])])
    _db(home / "dispatch_audit.db", [
        ("CREATE TABLE alerts(id INT, received_at TEXT, telegram_sent INT, telegram_error TEXT, suppress_reason TEXT)", []),
        ("CREATE TABLE long_term_alerts(id INT)", []),
    ])
    m = model_factory(check_processes=False)  # metadata fixture => producer live
    d = m.brain_reports()
    assert d.status == AuthorityStatus.ZERO_ACTIVITY
    assert "Brain is running and correctly idle, NOT down" in d.note


def test_5_stale_source_yields_stale(home, model_factory):
    _db(home / "paper_trading.db", [
        ("CREATE TABLE latest_prices(ticker TEXT, price REAL, updated_at TEXT)",
         [("AAPL", 200.0, (NOW - timedelta(hours=3)).isoformat())]),
        ("CREATE TABLE positions(x INT)", []),
        ("CREATE TABLE trade_history(x INT)", []),
    ])
    m = model_factory(check_processes=False)  # producer "live"
    d = m.market()
    assert d.status == AuthorityStatus.STALE
    assert d.values["newest_tick_age_seconds"] >= 3 * 3600 - 5


# --------------------------------------------------------------------------- #
# 6-10: authority preference, no double counting, quant/brain nuance
# --------------------------------------------------------------------------- #
def test_6_authoritative_source_preferred_over_legacy_projection(home, model_factory):
    _db(home / "quant.db", [
        ("CREATE TABLE suppression_counts(date TEXT, reason TEXT, count INT)", [(TODAY, "X", 1)])])
    d = model_factory(check_processes=False).quant_funnel()
    assert d.authoritative_source.startswith("quant.db suppression_counts")
    assert "talonx:quant:rejected" in d.legacy_sources  # legacy noted, not used as authority
    assert d.superseded_source is None  # quant.db IS the authority -- nothing supersedes it


def test_7_official_alerts_not_double_counted_with_transient(home, model_factory):
    _db(home / "dispatch_audit.db", [
        ("CREATE TABLE alerts(id INT, received_at TEXT, telegram_sent INT, telegram_error TEXT, suppress_reason TEXT)",
         [(1, f"{TODAY}T14:00:00", 1, None, None), (2, f"{TODAY}T14:05:00", 0, None, None)]),
        ("CREATE TABLE long_term_alerts(id INT)", []),
    ])
    d = model_factory(check_processes=False).official_alerts()
    assert d.values["generated_today"] == 2  # rows in the durable table, NOT + a transient Redis count
    assert "one row in dispatch_audit.db.alerts == one logical alert" in d.values["dedup_basis"]


def test_8_quant_zero_signals_nonzero_suppressions_represented(home, model_factory):
    _db(home / "quant.db", [
        ("CREATE TABLE suppression_counts(date TEXT, reason TEXT, count INT)",
         [(TODAY, "LOW_VOLATILITY", 16137)]),
    ])
    _db(home / "dispatch_audit.db", [
        ("CREATE TABLE alerts(id INT, received_at TEXT, telegram_sent INT, telegram_error TEXT, suppress_reason TEXT)", []),
        ("CREATE TABLE long_term_alerts(id INT)", []),
    ])
    m = model_factory(check_processes=False)
    assert m.quant_funnel().status == AuthorityStatus.ACTIVE
    assert m.quant_funnel().values["suppressions_today"] == 16137
    qs = m.quant_signals()
    assert qs.status == AuthorityStatus.ZERO_ACTIVITY
    assert "does NOT mean 0 market processing" in qs.note


def test_9_brain_zero_due_to_no_quant_publication(home, model_factory):
    _db(home / "brain.db", [("CREATE TABLE report_counts(date TEXT, category TEXT, count INT)", [])])
    _db(home / "dispatch_audit.db", [
        ("CREATE TABLE alerts(id INT, received_at TEXT, telegram_sent INT, telegram_error TEXT, suppress_reason TEXT)", []),
        ("CREATE TABLE long_term_alerts(id INT)", []),
    ])
    d = model_factory(check_processes=False).brain_reports()
    assert d.status == AuthorityStatus.ZERO_ACTIVITY
    assert "0 because 0 Quant" in d.note.replace("reports today because 0 Quant", "0 because 0 Quant") \
        or "0 Quant signals were published" in d.note
    assert d.values["upstream_quant_signals_today"] == 0


def test_10_brain_unavailable_distinct_from_idle(home, tmp_path):
    # brain.db missing entirely -> UNKNOWN, not ZERO_ACTIVITY
    dead = home / "rm.json"
    dead.write_text(json.dumps({"pid": 999999999, "started_at": (NOW - timedelta(days=1)).isoformat()}))
    m = AuthoritativeReadModel(home=home, now=NOW, check_processes=True, runtime_metadata_path=dead)
    assert m.brain_reports().status == AuthorityStatus.UNKNOWN


# --------------------------------------------------------------------------- #
# 11-12: intelligence authority + legacy filings channel
# --------------------------------------------------------------------------- #
def test_11_intelligence_authority_is_task96_store_stale_without_service(home, model_factory):
    led = home / "ingestion_ledger.db"
    _db(led, [
        ("CREATE TABLE text_events(event_id TEXT, accepted_at_utc TEXT)",
         [("E1", "2026-08-01T00:00:00+00:00")]),
        ("CREATE TABLE event_significance(event_id TEXT)", [("E1",)]),
    ])
    m = AuthoritativeReadModel(home=home, now=NOW, check_processes=False,
                               runtime_metadata_path=(home / "runtime_metadata.json"))
    d = m.intelligence()
    assert d.status == AuthorityStatus.NO_ACTIVE_PRODUCER  # no fresh heartbeat
    assert d.values["text_events_rows"] == 1
    assert d.values["newest_event"] == "2026-08-01T00:00:00+00:00"
    assert "NOT as 'no SEC events happened'" in d.note


def test_12_legacy_filings_channel_preserved_not_deleted(model_factory):
    d = model_factory().filings_legacy_channel()
    assert "talonx:filings:events" in d.legacy_sources
    assert "do NOT re-publish" in d.note


# --------------------------------------------------------------------------- #
# 13-18: alert + paper isolation
# --------------------------------------------------------------------------- #
def test_13_original_alert_counts_isolated_from_experimental(home, model_factory):
    _db(home / "dispatch_audit.db", [
        ("CREATE TABLE alerts(id INT, received_at TEXT, telegram_sent INT, telegram_error TEXT, suppress_reason TEXT)",
         [(1, f"{TODAY}T10:00:00", 1, None, None)]),
        ("CREATE TABLE long_term_alerts(id INT)", []),
    ])
    _db(home / "experimental" / "exp_alerts.db", [
        ("CREATE TABLE directional_alerts(id INT, sent INT)", [(1, 0), (2, 0)]),
    ])
    m = model_factory(check_processes=False)
    off = m.official_alerts()
    exp = m.experimental_alerts()
    assert off.values["generated_today"] == 1
    assert off.values["external_eligible"] is True
    assert exp.values["total"] == 2
    assert exp.values["external_eligible"] is False and exp.values["internal_only"] is True


def test_14_experimental_alerts_internal_only(home, model_factory):
    _db(home / "experimental" / "exp_alerts.db", [
        ("CREATE TABLE directional_alerts(id INT, sent INT)", [(1, 1)]),  # even a 'sent' row
    ])
    d = model_factory(check_processes=False).experimental_alerts()
    assert d.values["internal_only"] is True
    assert "never-external" in d.values["boundary"] and "boundary forbids" in d.values["boundary"]


def test_15_durable_outbox_not_double_counted_with_transient(home, model_factory):
    _db(home / "dispatch_audit.db", [
        ("CREATE TABLE alerts(id INT, received_at TEXT, telegram_sent INT, telegram_error TEXT, suppress_reason TEXT)",
         [(1, f"{TODAY}T10:00:00", 1, None, None)]),
        ("CREATE TABLE long_term_alerts(id INT)", []),
        ("CREATE TABLE last_telegram_push(ticker TEXT, horizon TEXT, pushed_at TEXT, price REAL)",
         [("AAPL", "intraday", f"{TODAY}T10:00:01", 200.0)]),
    ])
    d = model_factory(check_processes=False).telegram_delivery()
    assert d.values["merged"] is False
    assert d.values["original"]["sent_all_time"] == 1  # counted once, from the durable table


def test_16_17_18_paper_engines_isolated(home, model_factory):
    _db(home / "paper_trading.db", [
        ("CREATE TABLE positions(x INT)", [(1,)]),
        ("CREATE TABLE trade_history(timestamp TEXT)", [(f"{TODAY}T10:00:00",)]),
        ("CREATE TABLE portfolio_state(id INT, current_cash REAL)", [(1, 98000.0)]),
    ])
    _db(home / "experimental" / "experimental_paper.db", [
        ("CREATE TABLE positions(x INT)", []),
        ("CREATE TABLE trade_history(timestamp TEXT)", []),
        ("CREATE TABLE portfolio_state(id INT, current_cash REAL)", [(1, 100000.0)]),
    ])
    m = model_factory(check_processes=False)
    op, ep, piv = m.original_paper(), m.experimental_paper(), m.piv()
    assert op.values["attribution"] == "ORIGINAL / local-only"
    assert op.values["open_positions"] == 1 and op.status == AuthorityStatus.ACTIVE
    assert ep.values["attribution"] == "EXPERIMENTAL / validation-only"
    assert ep.values["open_positions"] == 0
    assert "structurally cannot route real capital" in piv.values["isolation"]
    # three distinct sources, never mixed
    assert op.authoritative_source != ep.authoritative_source != piv.authoritative_source
    assert "no broker" in op.values["execution"].lower()


# --------------------------------------------------------------------------- #
# 19-25: robustness / no-side-effect / snapshot
# --------------------------------------------------------------------------- #
def test_19_missing_optional_store_does_not_crash(home, model_factory):
    m = model_factory(check_processes=False)  # empty home, no dbs at all
    snap = m.snapshot()
    assert len(snap["domains"]) == 14
    for d in snap["domains"]:
        assert d["status"] in {s.value for s in AuthorityStatus}


def test_20_stale_timestamps_handled(home, model_factory):
    _db(home / "quant.db", [
        ("CREATE TABLE suppression_counts(date TEXT, reason TEXT, count INT)",
         [("2020-01-01", "LOW_VOLATILITY", 5)]),  # old date, none today
    ])
    d = model_factory(check_processes=False).quant_funnel()
    assert d.status == AuthorityStatus.ZERO_ACTIVITY  # producer live, 0 today
    assert d.values["newest_date"] == "2020-01-01"
    assert d.values["suppressions_today"] == 0


def test_21_restart_safe_read_is_stateless(home, model_factory):
    _db(home / "quant.db", [
        ("CREATE TABLE suppression_counts(date TEXT, reason TEXT, count INT)", [(TODAY, "X", 1)])])
    a = model_factory(check_processes=False).quant_funnel().to_dict()
    b = model_factory(check_processes=False).quant_funnel().to_dict()
    assert a == b


def test_22_backward_compatible_legacy_numeric_fields_present(home, model_factory):
    _db(home / "quant.db", [
        ("CREATE TABLE suppression_counts(date TEXT, reason TEXT, count INT)", [(TODAY, "X", 9)])])
    d = model_factory(check_processes=False).quant_funnel()
    assert "suppressions_today" in d.values and "by_reason_today" in d.values  # numeric preserved
    assert "status" in d.to_dict()  # explicit status added alongside


def test_23_no_write_side_effects(home, model_factory):
    dbp = home / "quant.db"
    _db(dbp, [("CREATE TABLE suppression_counts(date TEXT, reason TEXT, count INT)", [(TODAY, "X", 1)])])
    before = dbp.stat().st_mtime_ns
    before_tables = _tables(dbp)
    for _ in range(3):
        model_factory(check_processes=False).snapshot()
    assert dbp.stat().st_mtime_ns == before  # file untouched
    assert _tables(dbp) == before_tables     # no table created/migrated


def _tables(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    t = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    con.close()
    return t


def test_24_dashboard_backend_reads_authority_block():
    import dashboard_web as dw
    blk = dw._authority_block()
    assert "domains" in blk and "status_counts" in blk and "producers" in blk
    json.dumps(blk)  # WS payload must serialize
    # cached
    assert dw._authority_block() is blk


def test_25_zero_is_not_silently_remapped_to_activity(home, model_factory):
    # producer live, genuinely nothing -> ZERO_ACTIVITY, and values still show 0, not a fake nonzero
    _db(home / "dispatch_audit.db", [
        ("CREATE TABLE alerts(id INT, received_at TEXT, telegram_sent INT, telegram_error TEXT, suppress_reason TEXT)", []),
        ("CREATE TABLE long_term_alerts(id INT)", []),
    ])
    d = model_factory(check_processes=False).official_alerts()
    assert d.status == AuthorityStatus.ZERO_ACTIVITY
    assert d.values["generated_today"] == 0  # the zero is preserved, just correctly labelled
