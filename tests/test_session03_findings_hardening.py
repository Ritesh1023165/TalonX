"""
Session 03 findings (2026-09-23) -- A1 effective Intelligence delivery state, A2 Intelligence card
acceptance time, A3 health cause codes, A4 /ping lane attribution, A5 delivery queue breakdown,
A6 bounded SHUTDOWN drain, and the closed post-freeze allowlist.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_ingest.intelligence.sec_time import (BASIS_AMBIGUOUS, BASIS_ET_LABELLED_Z, BASIS_TRUE_UTC,
                                                  format_acceptance, resolve_acceptance)

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------ A2 timestamps
def test_adc_card_example_resolves_to_11_00_20_utc_not_07_00():
    # stored value SEC served fresh (ET wall clock labelled Z); TalonX read it 11:01:43Z
    r = resolve_acceptance(datetime(2026, 9, 23, 7, 0, 20, tzinfo=UTC),
                           observed_at=datetime(2026, 9, 23, 11, 1, 43, tzinfo=UTC), filing_date=date(2026, 9, 23))
    assert r.basis == BASIS_ET_LABELLED_Z and r.utc == datetime(2026, 9, 23, 11, 0, 20, tzinfo=UTC)
    txt = format_acceptance(r)
    assert txt == "SEC accepted 2026-09-23 07:00:20 ET (2026-09-23 11:00:20 UTC)"
    assert "07:00:20 UTC" not in txt and "07:00 UTC" not in txt


def test_true_utc_rendering_is_kept_when_ingested_late():
    # ADC 0001348490-26-000006: accepted 07:00:24 ET on 09-17, ingested days later (SEC had re-rendered)
    r = resolve_acceptance(datetime(2026, 9, 17, 11, 0, 24, tzinfo=UTC),
                           observed_at=datetime(2026, 9, 21, 18, 42, 40, tzinfo=UTC), filing_date=date(2026, 9, 17))
    assert r.basis == BASIS_TRUE_UTC and r.utc == datetime(2026, 9, 17, 11, 0, 24, tzinfo=UTC)
    assert format_acceptance(r) == "SEC accepted 2026-09-17 07:00:24 ET (2026-09-17 11:00:24 UTC)"


def test_est_wall_clock_labelled_z_is_converted_with_the_winter_offset():
    # 2026-12-02 (EST, UTC-5): accepted 08:15:00 ET, read 2 min later
    r = resolve_acceptance(datetime(2026, 12, 2, 8, 15, tzinfo=UTC),
                           observed_at=datetime(2026, 12, 2, 13, 17, tzinfo=UTC), filing_date=date(2026, 12, 2))
    assert r.basis == BASIS_ET_LABELLED_Z and r.utc == datetime(2026, 12, 2, 13, 15, tzinfo=UTC)


@pytest.mark.parametrize("raw,observed,expected_utc", [
    # spring forward 2026-03-08 (02:00 -> 03:00 ET): a 07:00 ET filing on the transition day is UTC-4
    (datetime(2026, 3, 9, 7, 0, tzinfo=UTC), datetime(2026, 3, 9, 11, 2, tzinfo=UTC), datetime(2026, 3, 9, 11, 0, tzinfo=UTC)),
    # the Friday before (still EST, UTC-5)
    (datetime(2026, 3, 6, 7, 0, tzinfo=UTC), datetime(2026, 3, 6, 12, 2, tzinfo=UTC), datetime(2026, 3, 6, 12, 0, tzinfo=UTC)),
    # fall back 2026-11-01: Monday 11-02 is EST
    (datetime(2026, 11, 2, 7, 0, tzinfo=UTC), datetime(2026, 11, 2, 12, 2, tzinfo=UTC), datetime(2026, 11, 2, 12, 0, tzinfo=UTC)),
])
def test_dst_transitions(raw, observed, expected_utc):
    r = resolve_acceptance(raw, observed_at=observed, filing_date=raw.date())
    assert r.basis == BASIS_ET_LABELLED_Z and r.utc == expected_utc


def test_evening_filing_true_utc_crosses_midnight_but_filing_date_is_the_et_day():
    # accepted 20:30 ET on 09-22 = 00:30Z on 09-23; read the next morning (true UTC rendering)
    r = resolve_acceptance(datetime(2026, 9, 23, 0, 30, tzinfo=UTC),
                           observed_at=datetime(2026, 9, 23, 13, 0, tzinfo=UTC), filing_date=date(2026, 9, 22))
    assert r.basis == BASIS_TRUE_UTC and r.new_york.date() == date(2026, 9, 22)


def test_ambiguous_timing_never_guesses_and_shows_only_the_filing_date():
    # read ~2h after acceptance: SEC could have served either rendering -> no claim
    r = resolve_acceptance(datetime(2026, 9, 23, 9, 0, tzinfo=UTC),
                           observed_at=datetime(2026, 9, 23, 15, 0, tzinfo=UTC), filing_date=date(2026, 9, 23))
    assert r.basis == BASIS_AMBIGUOUS and r.utc is None
    assert format_acceptance(r) == "SEC filing date 2026-09-23 (acceptance time unverified)"
    assert "UTC" not in format_acceptance(r)


def _card(raw, observed, fd):
    from talonx_ingest.intelligence.domain import AlertCard, EventType, SignificanceBand
    return AlertCard(alert_id="a", event_id="e", symbol="ADC", company_name="Agree Realty", title="ADC insider",
                     event_type=EventType.INSIDER_TRANSACTION, significance=SignificanceBand.HIGH,
                     significance_reasons=("3 distinct insiders bought",), timestamp_utc=raw,
                     filing_date=fd, source_observed_at_utc=observed)


def test_concise_card_renders_the_resolved_time_and_receipt_age():
    from talonx_ingest.intelligence.delivery.renderer import render_concise as render_concise_card
    card = _card(datetime(2026, 9, 23, 7, 0, 20, tzinfo=UTC), datetime(2026, 9, 23, 11, 1, 43, tzinfo=UTC),
                 date(2026, 9, 23))
    msg = render_concise_card(card, now=datetime(2026, 9, 23, 11, 3, 11, tzinfo=UTC),
                              disposition_reason="3 distinct insiders bought in the open market within 30 days")
    assert "SEC accepted 2026-09-23 07:00:20 ET (2026-09-23 11:00:20 UTC)" in msg.text
    assert "07:00 UTC" not in msg.text and "source age: 3m" in msg.text


def test_expanded_card_accepted_line_uses_the_resolved_time():
    from talonx_ingest.intelligence.delivery import renderer as R
    card = _card(datetime(2026, 9, 23, 7, 0, 20, tzinfo=UTC), datetime(2026, 9, 23, 11, 1, 43, tzinfo=UTC),
                 date(2026, 9, 23))
    lines = R._event_lines(card, expanded=False)
    assert any("11:00:20 UTC" in ln for ln in lines) and not any("07:00 UTC" in ln for ln in lines)


def test_card_built_from_an_event_carries_filing_date_and_receipt_separately():
    from talonx_ingest.intelligence.domain import EventType, SourceType, TextEvent
    from talonx_ingest.intelligence.pipeline import build_alert_card
    ev = TextEvent(event_id="SEC:x:INSIDER_TRANSACTION", symbol="ADC", company_name="Agree",
                   source_type=SourceType.SEC_EDGAR_SUBMISSIONS, source_record_id="x",
                   event_type=EventType.INSIDER_TRANSACTION, form_type="4", accession="x",
                   accepted_at_utc=datetime(2026, 9, 23, 7, 0, 20, tzinfo=UTC), filing_date=date(2026, 9, 23),
                   ingested_at_utc=datetime(2026, 9, 23, 11, 1, 43, tzinfo=UTC))
    c = build_alert_card(ev)
    assert c.timestamp_utc == datetime(2026, 9, 23, 7, 0, 20, tzinfo=UTC)          # raw provenance preserved
    assert c.filing_date == date(2026, 9, 23) and c.source_observed_at_utc == datetime(2026, 9, 23, 11, 1, 43, tzinfo=UTC)


def test_v2_admission_does_not_use_the_intelligence_resolver():
    for f in ("talonx_v2/form4_source.py", "talonx_v2/service.py", "talonx_v2/cluster_engine.py"):
        assert "sec_time" not in (REPO / f).read_text(encoding="utf-8")


# -------------------------------------------------------------------------- A1 effective delivery
@pytest.mark.parametrize("env,deliver,transport,expected", [
    ({}, True, "telegram", ("OFF", True, "ON")),                                     # the Session 03 case
    ({"TALONX_INTEL_DELIVER_CARDS": "0"}, True, "telegram", ("OFF", True, "OFF")),   # explicit OFF wins
    ({"TALONX_INTEL_DELIVER_CARDS": "1"}, True, "telegram", ("DRY_RUN", True, "ON")),
    ({"TALONX_INTEL_DELIVER_CARDS": "1", "TALONX_INTEL_DRY_RUN_DELIVERY": "1"}, True, "telegram",
     ("DRY_RUN", False, "DRY_RUN")),
    ({}, True, "dryrun", ("OFF", False, "OFF")),
    ({}, False, "telegram", ("OFF", False, "OFF")),
])
def test_intelligence_delivery_state_configured_vs_runtime_vs_effective(env, deliver, transport, expected):
    from talonx_v2.release_gate import intelligence_delivery_state
    s = intelligence_delivery_state(env, deliver=deliver, transport=transport)
    assert (s["configured"], s["runtime_requested"], s["effective"]) == expected


def test_launcher_and_gate_share_one_implementation():
    src = (REPO / "talonx_ops/prospective/proc.py").read_text(encoding="utf-8")
    assert "intelligence_delivery_env_overrides" in src
    assert '"TALONX_INTEL_DELIVER_CARDS": "1"' not in src                          # no second copy of the rule
    from talonx_v2.release_gate import intelligence_delivery_env_overrides
    assert intelligence_delivery_env_overrides({}, deliver=True, transport="telegram") == {
        "TALONX_INTEL_DELIVER_CARDS": "1", "TALONX_INTEL_DRY_RUN_DELIVERY": "0"}


def test_delivery_state_never_reads_secrets():
    from talonx_v2.release_gate import intelligence_delivery_state
    s = intelligence_delivery_state({"TELEGRAM_BOT_TOKEN": "SECRET-123"}, deliver=True, transport="telegram")
    assert "SECRET" not in repr(s)


# ---------------------------------------------------------------------------- A3 health causes
def test_health_causes_separate_recovery_pass_from_live_path():
    from talonx_ops.notify.producers import intelligence_health_causes, intelligence_health_condition
    rec = intelligence_health_causes(symbols_failed=0, poll_errors=0, recovery={"timed_out": 1, "failed": 0},
                                     delivery_ok=True, freshness="FRESH")
    assert rec == ["RECOVERY_PASS_TIMED_OUT"] and intelligence_health_condition(rec) == "RECOVERY_PASS_DEGRADED"
    live = intelligence_health_causes(symbols_failed=2, poll_errors=2, recovery={"timed_out": 1}, delivery_ok=True,
                                      freshness="STALE")
    assert intelligence_health_condition(live) == "PROCESSING_OR_INPUT_DEGRADED"
    assert set(live) == {"POLL_SYMBOL_FAILURES", "POLL_ERRORS", "RECOVERY_PASS_TIMED_OUT", "SOURCE_STALE"}
    assert intelligence_health_causes(symbols_failed=0, poll_errors=0, recovery={}, delivery_ok=True,
                                      freshness="FRESH") == []


def test_degraded_incident_is_still_raised_and_carries_its_causes(tmp_path, monkeypatch):
    from talonx_ops.notify.outbox import NotifyStore
    from talonx_ops.notify.producers import record_intelligence_health
    monkeypatch.setenv("TALONX_NOTIFY_OPERATIONS_ENABLED", "1")
    monkeypatch.setenv("TALONX_NOTIFY_DB_PATH", str(tmp_path / "n.db"))
    now = datetime(2026, 9, 23, 12, 55, tzinfo=UTC)
    assert record_intelligence_health(degraded=True, now=now, causes=["RECOVERY_PASS_TIMED_OUT"]) is True
    rows = NotifyStore(str(tmp_path / "n.db")).outbox_due(now_iso=now.isoformat(), destination="OPERATIONS")
    assert len(rows) == 1 and "RECOVERY_PASS_DEGRADED" in rows[0]["payload_text"]
    assert "RECOVERY_PASS_TIMED_OUT" in rows[0]["payload_text"]


def test_runner_passes_the_same_predicate_with_causes():
    src = (REPO / "talonx_ingest/intelligence/service/runner.py").read_text(encoding="utf-8")
    assert "intelligence_health_causes(" in src and "record_intelligence_health(degraded=bool(causes)" in src


# ---------------------------------------------------------------------------- A5 queue breakdown
def test_delivery_queue_breakdown_separates_live_queue_from_historical_expiry():
    from talonx_ops.intel_queue import delivery_queue_breakdown, format_breakdown
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE intelligence_delivery (state TEXT, route TEXT, enqueued_at_utc TEXT, updated_at_utc TEXT,"
                " sent_at_utc TEXT)")
    now = datetime(2026, 9, 23, 20, 0, tzinfo=UTC)
    iso = lambda h: (now - timedelta(hours=h)).isoformat()  # noqa: E731
    rows = ([("PENDING", "DIGEST", iso(2), iso(2), None)] * 3 + [("PENDING", "IMMEDIATE", iso(0.1), iso(0.1), None)]
            + [("EXPIRED", "DIGEST", iso(3), iso(3), None)] * 5 + [("EXPIRED", "DIGEST", iso(100), iso(100), None)] * 7
            + [("SENT", "IMMEDIATE", iso(9), iso(9), iso(9)), ("SENT", "IMMEDIATE", iso(0.5), iso(0.5), iso(0.5))]
            + [("FAILED", "IMMEDIATE", iso(1), iso(1), None), ("HELD", "IMMEDIATE", iso(1), iso(1), None)])
    con.executemany("INSERT INTO intelligence_delivery VALUES (?,?,?,?,?)", rows)
    b = delivery_queue_breakdown(con, now=now)
    assert b["LIVE_PENDING"] == 4 and b["LIVE_PENDING_BY_ROUTE"] == {"DIGEST": 3, "IMMEDIATE": 1}
    assert b["LIVE_PENDING_OLDEST_MIN"] == pytest.approx(120.0)
    assert (b["LIVE_FAILED_24H"], b["HELD"], b["EXPIRED_24H"], b["EXPIRED_ALL_TIME"]) == (1, 1, 5, 12)
    assert (b["SENT_1H"], b["SENT_24H"]) == (1, 2)
    text = "\n".join(format_breakdown(b))
    assert "LIVE_PENDING: 4" in text and "stale backlog cards expire by design" in text


# ---------------------------------------------------------------------------- A4 /ping attribution
def test_ping_labels_the_shared_quant_counter_and_brain_scope():
    src = (REPO / "talonx_dispatch/telegram_listener.py").read_text(encoding="utf-8")
    # SUPERSEDED 2026-09-24 (S14 legacy cleanup): the Experimental lane that shared this counter is RETIRED from
    # active startup, so the label now attributes the counter to the CONTROL lane explicitly.
    assert "Quant published (CONTROL; Experimental retired)" in src
    assert "Brain received (Original talonx:signals:quant only)" in src
    assert '"published_no_subscriber"' in src


# ---------------------------------------------------------------------------- A6 SHUTDOWN drain
def test_shutdown_notice_drain_is_bounded_and_never_hangs_close():
    from talonx_ops.prospective.__main__ import drain_operations_bounded
    release = threading.Event()

    def slow_drain(store, *, destination):
        release.wait(5)
        return {}

    t0 = time.monotonic()
    out = drain_operations_bounded(object(), timeout_s=0.3, drain=slow_drain)
    assert out["status"] == "TIMEOUT" and time.monotonic() - t0 < 2.0
    release.set()


def test_shutdown_notice_drain_sends_operations_only(tmp_path):
    from talonx_ops.prospective.__main__ import drain_operations_bounded
    seen = []
    out = drain_operations_bounded(object(), drain=lambda store, *, destination: seen.append(destination) or {"sent": 1})
    assert out["status"] == "DRAINED" and seen == ["OPERATIONS"]
    err = drain_operations_bounded(object(), drain=lambda store, *, destination: 1 / 0)
    assert err["status"] == "ERROR" and err["error"] == "ZeroDivisionError"


def test_close_enqueues_shutdown_before_the_bounded_drain():
    src = (REPO / "talonx_ops/prospective/__main__.py").read_text(encoding="utf-8")
    i_enq = src.index('event_type="SHUTDOWN"')
    i_drain = src.index("drain_operations_bounded(_ops_store)")
    assert i_enq < i_drain


# ------------------------------------------------------------------------------ freeze allowlist
def test_session03_allowlist_is_closed_and_strategy_free():
    from talonx_ops.prospective.preflight import FREEZE_SESSION03_HARDENING_FILES as files
    fp_mod = __import__("research.scripts.task112_v2_release_fingerprint", fromlist=["_STRATEGY_FILES"])
    fp_files = {str(p.relative_to(Path(fp_mod.__file__).resolve().parents[2])).replace("\\", "/")
                for p in fp_mod._STRATEGY_FILES}
    assert not fp_files & set(files)
    assert not [f for f in files if f.startswith("talonx_v2/")]
    assert not [f for f in files if any(x in f for x in ("pricing", "provider_contract", "store.py", "paper",
                                                           "cluster_engine", "form4_source", "insider/"))]


def test_frozen_release_check_accepts_this_branch_shape(tmp_path):
    from talonx_ops.prospective import preflight as pf
    ok_files = list(pf.FREEZE_SESSION03_HARDENING_FILES) + ["talonx_premarket/engine.py", "docs/x.md", "tests/t.py"]
    bad = ok_files + ["talonx_v2/cluster_engine.py"]
    allowed = lambda f: (f.startswith(pf.FREEZE_ALLOWED_PREFIXES) or f in pf.FREEZE_ALLOWED_FILES  # noqa: E731
                         or f in pf.FREEZE_OPS_HARDENING_FILES or f in pf.FREEZE_RELEASE_FIDELITY_FIX_FILES
                         or f in pf.FREEZE_SESSION03_HARDENING_FILES or f.startswith(pf.FREEZE_RESEARCH_LANE_PREFIXES))
    assert all(allowed(f) for f in ok_files) and not all(allowed(f) for f in bad)
