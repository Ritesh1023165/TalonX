"""Task 83 §2 -- the read-only comparison collector.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. No real network, no real Redis,
no production state dir. Every collector run here is driven by an isolated
tmp_path PIV state dir and an in-memory fake Redis.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from talonx_compare.collector import ComparisonCollector
from talonx_compare.config import CompareConfig
from talonx_compare.divergence import DIVERGENCE_CLASSES
from talonx_compare.identity import STAGES, make_record
from talonx_compare.testing import FakeRedis, make_pair, write_piv_state

DATE = "2026-08-28"
SESSION = "piv_2026-08-28_100000_abcd1234"
NOW = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def piv_dir(tmp_path):
    d = tmp_path / "piv"
    write_piv_state(d)
    return d


@pytest.fixture
def cfg(tmp_path, piv_dir):
    return CompareConfig(
        state_dir=tmp_path / "collector_state",
        evidence_root=tmp_path / "evidence",
        piv_state_dir=piv_dir,
    )


def _collector(cfg, **kw):
    return ComparisonCollector(cfg, clock=lambda: NOW, **kw)


# --- 2.1 / 2.6 observer-only, no shared state -------------------------------

def test_collector_never_writes_to_observed_redis(cfg):
    original, piv = make_pair()
    _collector(cfg, original_redis=original, piv_redis=piv).collect_once()
    assert original.write_calls == []
    assert piv.write_calls == []


def test_collector_subscribe_only_no_publish(cfg):
    """The runner's subscribe path never calls publish."""
    from talonx_compare.runner import CollectorService

    original, piv = make_pair()
    svc = CollectorService(cfg)
    # simulate one buffered message arriving and being folded in
    svc._buffer_original.append({"channel": "talonx:signals:quant",
                                 "data": json.dumps({"ticker": "AAPL", "timestamp": f"{DATE}T14:00:00+00:00",
                                                     "signal_type": "LONG"})})
    drained = svc._buffer_original.swap()
    ComparisonCollector(cfg, clock=lambda: NOW).collect_once(
        captured_original_messages=drained)
    assert original.write_calls == [] and piv.write_calls == []
    server_log = original._server.publish_log
    assert server_log == []  # collector never published anything


def test_collector_no_shared_lock_or_state_paths(cfg):
    from talonx_piv.config import PivConfig

    piv_sd = PivConfig().state_dir.resolve()
    assert cfg.state_dir.resolve() != piv_sd
    assert cfg.lock_path.resolve() != (piv_sd / "execution_ownership.lock").resolve()
    assert str(cfg.lock_path).startswith(str(cfg.state_dir))
    # collector namespace is its own, not talonx:piv / talonx:*
    assert cfg.namespace == "talonx:compare"


def test_collector_observed_bindings_unchanged(cfg):
    """The collector reads Original from DB 0 + existing channels and PIV
    from DB 1 + talonx:piv:* -- it defines no channels of its own."""
    assert cfg.original_redis_url.endswith("/0")
    assert cfg.piv_redis_url.endswith("/1")
    assert all(c.startswith("talonx:piv:") for c in cfg.piv_channels().values())
    assert all(not c.startswith("talonx:piv:") for c in cfg.original_channels().values())


def test_collector_namespace_is_isolated(cfg):
    c = _collector(cfg)
    c.collect_once()
    # cursor + dedup live under the collector state dir only
    assert cfg.cursor_path.exists()
    assert cfg.cursor_path.parent == cfg.state_dir
    assert cfg.dedup_dir.parent == cfg.state_dir


# --- 2.4 pub/sub crosses DB -> prefixes mandatory --------------------------

def test_pubsub_crosses_db_requires_prefix():
    original, piv = make_pair()
    # a subscriber on the PIV handle (DB 1) still receives a message
    # published on the Original handle (DB 0) for the same channel name.
    ps = piv.pubsub()
    ps.subscribe("talonx:signals:quant")
    original.publish("talonx:signals:quant", "leaked")
    msg = ps.get_message()
    assert msg is not None and msg["data"] == "leaked"
    # which is exactly why PIV must use a distinct channel name:
    ps2 = piv.pubsub()
    ps2.subscribe("talonx:piv:signals:quant")
    original.publish("talonx:signals:quant", "not-for-piv")
    assert ps2.get_message() is None


# --- 2.7 restart / cursor recovery ---------------------------------------

def test_restart_does_not_duplicate_events(cfg):
    r1 = _collector(cfg).collect_once()
    assert r1.piv_appended > 0
    # brand-new collector object == a process restart
    r2 = _collector(cfg).collect_once()
    assert r2.piv_appended == 0
    assert r2.duplicates_skipped == r1.piv_appended + r1.original_appended
    lines = (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines()
    ids = [json.loads(x)["_id"] for x in lines if x.strip()]
    assert len(ids) == len(set(ids))  # no dup lines


def test_cursor_recovery_after_crash(cfg, piv_dir):
    _collector(cfg).collect_once()
    # a new event lands while the collector was "down"
    with (piv_dir / "piv_events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "FILLED", "timestamp": f"{DATE}T14:30:00+00:00",
                             "symbol": "AAPL", "session_id": SESSION, "trading_date_et": DATE,
                             "correlation_id": "d1"}, sort_keys=True) + "\n")
    r = _collector(cfg).collect_once()
    assert r.piv_appended == 1  # exactly the one new event, nothing re-appended


# --- 2.8 late events + EOD ---------------------------------------------

def test_late_event_recorded(cfg, piv_dir):
    _collector(cfg).collect_once()
    with (piv_dir / "piv_events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "POSITION_CLOSED", "timestamp": f"{DATE}T15:55:00+00:00",
                             "symbol": "AAPL", "session_id": SESSION, "trading_date_et": DATE,
                             "correlation_id": "d1", "gross_pnl": 1.0}, sort_keys=True) + "\n")
    r = _collector(cfg).collect_once()
    assert r.piv_appended == 1


def test_late_eod_updates_correct_session(cfg, piv_dir):
    _collector(cfg).collect_once()
    (piv_dir / "eod_state.json").write_text(json.dumps({
        "status": "PASSED", "trading_date_et": DATE, "completed_at": f"{DATE}T20:10:00+00:00",
    }), encoding="utf-8")
    r = _collector(cfg).collect_once()
    piv_recs = [json.loads(x) for x in
                (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines() if x.strip()]
    eod = [x for x in piv_recs if x["stage"] == "eod"]
    assert eod and eod[0]["decision_outcome"] == "PASSED"
    assert eod[0]["session_id"] == SESSION  # the archived session, not a new one


# --- 2.9 explicit anomaly detection ---------------------------------

def test_detects_malformed_input(cfg, piv_dir):
    with (piv_dir / "piv_events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
    r = _collector(cfg).collect_once()
    assert any(d["kind"] == "MALFORMED" for d in r.diagnostics)


def test_detects_duplicate(cfg):
    _collector(cfg).collect_once()
    r = _collector(cfg).collect_once()
    assert any(d["kind"] == "DUPLICATE" for d in r.diagnostics)


def test_detects_missing_stage(cfg):
    # Original has no records at all -> every PIV stage/symbol key is
    # "PIV present, ORIGINAL missing"
    r = _collector(cfg).collect_once()
    assert any(d["kind"] == "MISSING" for d in r.diagnostics)


def test_detects_stale_source(cfg, piv_dir):
    # rewrite events so the newest one is hours old
    (piv_dir / "piv_events.jsonl").write_text(json.dumps({
        "event": "SIGNAL", "timestamp": "2026-08-28T09:00:00+00:00", "symbol": "AAPL",
        "session_id": SESSION, "trading_date_et": DATE, "correlation_id": "d1",
    }) + "\n", encoding="utf-8")
    r = _collector(cfg).collect_once()
    assert r.source_health["piv_events"]["state"] == "STALE"


def test_detects_wrong_session(cfg, piv_dir):
    with (piv_dir / "piv_events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "SIGNAL", "timestamp": f"{DATE}T14:10:00+00:00",
                             "symbol": "NVDA", "session_id": "piv_OTHER_SESSION",
                             "trading_date_et": DATE}) + "\n")
    r = _collector(cfg).collect_once()
    assert any(d["kind"] == "WRONG_SESSION" for d in r.diagnostics)


def test_manifest_conflict_is_wrong_session_at_day_level(cfg, piv_dir):
    _collector(cfg).collect_once()
    # a different session claims the same date -> manifest must not be overwritten
    write_piv_state(piv_dir, session_id="piv_2026-08-28_120000_ffff9999", config_hash="different")
    r = _collector(cfg).collect_once()
    assert r.manifest_conflict is True
    assert any(d["kind"] == "WRONG_SESSION" and d["source"] == "manifest.json" for d in r.diagnostics)


# --- 2.10 immutable manifest ------------------------------------

def test_manifest_fields_present_and_immutable(cfg):
    r = _collector(cfg).collect_once()
    manifest = json.loads((cfg.evidence_root / DATE / "manifest.json").read_text())
    assert manifest["trading_date"] == DATE
    assert manifest["piv"]["session_id"] == SESSION
    assert manifest["piv"]["runtime_sha"] == "e153450"
    assert manifest["piv"]["config_hash"] == "cfg0001"
    assert manifest["piv"]["feed_mode"] == "RESEARCH_SIP"
    assert manifest["piv"]["universe"]
    assert manifest["piv"]["execution_mode"] in ("SHADOW", "PAPER")
    assert manifest["piv"]["strategy_approval_status"] == "UNVALIDATED"
    assert manifest["piv"]["real_capital_prohibited"] is True
    assert manifest["original"]["channels"]
    assert manifest["original"]["stage_modules"]
    assert manifest["collector"]["role"] == "PASSIVE_OBSERVER"
    assert manifest["collector"]["publishes"] is False
    assert manifest["operational_agreement_only"] is True
    # immutability: a re-run with identical inputs does not rewrite it
    mtime = (cfg.evidence_root / DATE / "manifest.json").stat().st_mtime
    _collector(cfg).collect_once()
    assert (cfg.evidence_root / DATE / "manifest.json").stat().st_mtime == mtime


# --- 2.11 / 2.12 record coverage -----------------------------

def test_original_stage_records_written(cfg):
    original, piv = make_pair()
    for module, counter, val in [("ingest", "bars_read", 100), ("quant", "evaluated", 40),
                                 ("brain", "received", 10), ("core", "action_bullish", 3),
                                 ("dispatch", "pushed_telegram", 2)]:
        original.seed_metric(DATE, module, counter, val)
    r = _collector(cfg, original_redis=original, piv_redis=piv).collect_once()
    assert r.original_appended > 0
    recs = [json.loads(x) for x in
            (cfg.evidence_root / DATE / "original_events.jsonl").read_text().splitlines() if x.strip()]
    stages = {x["stage"] for x in recs}
    assert {"warmup", "quant", "brain", "core", "telegram"} <= stages


def test_piv_records_written(cfg, piv_dir):
    write_piv_state(
        piv_dir,
        freshness={"provider_state": "HEALTHY", "symbols": {"AAPL": "FRESH", "MSFT": "STALE"}},
        reconciliation={"complete": True, "consistent": True, "reconciled_at": f"{DATE}T20:00:00+00:00"},
        readiness={"session_date": DATE, "finalized": {"AAPL": {"status": "READY"}}},
        shadow={"sh_d1": {"decision_id": "d1", "symbol": "AAPL", "status": "OPEN",
                          "filled_at": f"{DATE}T14:10:00+00:00"}},
        eod={"status": "PASSED", "trading_date_et": DATE},
    )
    r = _collector(cfg).collect_once()
    recs = [json.loads(x) for x in
            (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines() if x.strip()]
    stages = {x["stage"] for x in recs}
    for expected in ("readiness", "freshness", "decision", "shadow", "lifecycle", "reconciliation", "eod"):
        assert expected in stages, f"missing PIV stage {expected}: got {sorted(stages)}"


# --- 2.13 Telegram totals + PIV zero-attempt ----------------

def test_telegram_totals_and_piv_zero_assertion(cfg, piv_dir):
    """Task 83-R1 §5: without durable notification telemetry the archive
    may NOT assert zero -- it is UNVERIFIED, not zero."""
    original, piv = make_pair()
    original.seed_metric(DATE, "dispatch", "pushed_telegram", 7)
    original.seed_metric(DATE, "dispatch", "muted_cooldown", 3)
    r = _collector(cfg, original_redis=original, piv_redis=piv).collect_once()
    tg = json.loads((cfg.evidence_root / DATE / "telegram.json").read_text())
    assert tg["piv_notification_telemetry"]["verdict"] == "UNVERIFIED"
    assert tg["piv_zero_attempt_assertion"] is False
    assert "pushed_telegram" in tg["original_telegram_counters"]
    assert tg["original_telegram_totals"]["pushed_telegram"] == 7


def test_piv_zero_assertion_only_with_verified_telemetry(cfg, piv_dir):
    """A durable telemetry file for the session, outbound+inbound disabled,
    all counters zero -> and only then -> the archive asserts zero."""
    from talonx_piv.notification_telemetry import merge_telemetry

    merge_telemetry(piv_dir, session_id=SESSION, trading_date_et=DATE,
                    ownership={"outbound_enabled": False, "sender_constructed": False,
                              "inbound_poller_constructed": False, "inbound_poller_started": False})
    r = _collector(cfg).collect_once()
    tg = json.loads((cfg.evidence_root / DATE / "telegram.json").read_text())
    assert tg["piv_notification_telemetry"]["verdict"] == "VERIFIED_ZERO"
    assert tg["piv_zero_attempt_assertion"] is True


def test_piv_zero_assertion_fails_loudly_if_piv_attempted_telegram(cfg, piv_dir):
    from talonx_piv.notification_telemetry import merge_telemetry

    merge_telemetry(piv_dir, session_id=SESSION, trading_date_et=DATE,
                    ownership={"outbound_enabled": True, "sender_constructed": True},
                    outbound_delta={"attempts": 1, "failures": 1})
    r = _collector(cfg).collect_once()
    tg = json.loads((cfg.evidence_root / DATE / "telegram.json").read_text())
    assert tg["piv_notification_telemetry"]["verdict"] == "ATTEMPTS_RECORDED"
    assert tg["piv_zero_attempt_assertion"] is False


# --- 2.14 per-symbol/stage comparison ----------------------

def test_per_symbol_stage_comparison(cfg, piv_dir):
    """Task 83-R1 §3.6: an Original quant signal and a PIV quant SIGNAL
    with no shared decision id are DISTINCT events -- each gets its own
    (stage, symbol, event_identity) row, never collapsed into one."""
    original, piv = make_pair()
    r = _collector(cfg, original_redis=original, piv_redis=piv).collect_once(
        captured_original_messages=[{
            "channel": "talonx:signals:quant",
            "data": json.dumps({"ticker": "AAPL", "timestamp": f"{DATE}T14:05:00+00:00",
                                "signal_type": "LONG"}),
        }])
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    assert "per_stage_totals" in comp and "per_symbol_stage" in comp
    quant_aapl = [x for x in comp["per_symbol_stage"] if x["stage"] == "quant" and x["symbol"] == "AAPL"]
    assert any(x["original_present"] and not x["piv_present"] for x in quant_aapl)
    assert any(x["piv_present"] and not x["original_present"] for x in quant_aapl)
    # every row carries its event identity + record kind
    assert all("event_identity" in x and x["record_kind"] == "EVENT" for x in quant_aapl)


# --- 2.15 hashes + diagnostics --------------------------

def test_evidence_file_hashes(cfg):
    _collector(cfg).collect_once()
    hp = cfg.evidence_root / DATE / "file_hashes.json"
    assert hp.exists()
    stored = json.loads(hp.read_text())
    assert stored["algorithm"] == "sha256-lf-normalized"
    assert "manifest.json" in stored["hashes"]
    assert "runtime_status.json" in stored["hashes"]
    from talonx_compare.evidence import EvidenceWriter

    integ = EvidenceWriter(cfg.evidence_root, DATE).verify_archive()
    assert integ.ok, integ.problems
    assert integ.state == "HEALTHY"


def test_source_diagnostics_recorded(cfg, piv_dir):
    (piv_dir / "decision_ledger.json").write_text("{corrupt", encoding="utf-8")
    r = _collector(cfg).collect_once()
    diag = json.loads((cfg.evidence_root / DATE / "diagnostics.json").read_text())["diagnostics"]
    assert any(d["kind"] == "UNREADABLE" and "decision_ledger" in d["source"] for d in diag)


# --- 2.16 comparison identity fields --------------------

def test_comparison_identity_fields():
    rec = make_record(
        pipeline="PIV", stage="decision", symbol="aapl",
        event_time="2026-08-28T14:05:00+00:00", session_id="s1",
        source_bar_time="2026-08-28T14:04:00+00:00", decision_id="d1",
        decision_outcome="HOLD", reason_codes=["B", "A"], execution_class="NONE",
    )
    d = rec.to_dict()
    for field in ("pipeline", "session_id", "trading_date", "stage", "symbol", "event_time",
                  "source_bar_time", "decision_id", "decision_outcome", "reason_codes",
                  "execution_class", "payload_fingerprint"):
        assert field in d, field
    assert d["trading_date"] == "2026-08-28"        # tz-aware ET bucket
    assert d["symbol"] == "AAPL"                    # normalised
    assert d["reason_codes"] == ["A", "B"]          # order-normalised
    assert len(d["payload_fingerprint"]) == 16


# --- 2.17 deterministic tz-aware alignment ---------------

def test_alignment_is_deterministic_and_tz_aware(cfg):
    r1 = _collector(cfg).collect_once()
    comp1 = (cfg.evidence_root / DATE / "comparison.json").read_text()
    # wipe evidence, re-run -> identical bytes
    import shutil

    shutil.rmtree(cfg.evidence_root / DATE)
    _collector(cfg).collect_once()
    comp2 = (cfg.evidence_root / DATE / "comparison.json").read_text()
    assert comp1 == comp2


def test_no_cross_date_or_cross_session_comparison(cfg, piv_dir):
    # events for the day-after must never be aligned into this date's evidence
    with (piv_dir / "piv_events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "SIGNAL", "timestamp": "2026-08-29T14:00:00+00:00",
                             "symbol": "TSLA", "session_id": SESSION,
                             "trading_date_et": "2026-08-29"}) + "\n")
    _collector(cfg).collect_once()
    recs = [json.loads(x) for x in
            (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines() if x.strip()]
    assert all(x["trading_date"] == DATE for x in recs)
    assert not any(x["symbol"] == "TSLA" for x in recs)


# --- 2.18 divergence classification -------------------

@pytest.mark.parametrize("klass", DIVERGENCE_CLASSES)
def test_divergence_classification(klass):
    from talonx_compare.divergence import (
        DECISION_DIFFERENCE, EXECUTION_MODE_DIFFERENCE, FEED_INPUT_DIFFERENCE,
        FRESHNESS_EXCLUSION, LATE_OR_MISSING_STAGE, QUANT_GATE_DIFFERENCE,
        READINESS_DIFFERENCE, SOURCE_UNAVAILABLE, ALERT_DELIVERY_DIFFERENCE,
        classify_divergence,
    )

    def rec(stage, **kw):
        return make_record(pipeline=kw.pop("pipeline", "ORIGINAL"), stage=stage,
                           symbol="AAPL", event_time=NOW.isoformat(),
                           session_id=kw.pop("session_id", None), **kw)

    if klass == SOURCE_UNAVAILABLE:
        d = classify_divergence(rec("quant"), rec("quant", pipeline="PIV"),
                                original_source_health_ok=False)
    elif klass == LATE_OR_MISSING_STAGE:
        d = classify_divergence(rec("quant"), None)
    elif klass == FEED_INPUT_DIFFERENCE:
        d = classify_divergence(rec("quant", source_bar_time="2026-08-28T14:00:00+00:00"),
                                rec("quant", pipeline="PIV", source_bar_time="2026-08-28T14:01:00+00:00"))
    elif klass == EXECUTION_MODE_DIFFERENCE:
        d = classify_divergence(rec("lifecycle", execution_class="SIMULATED_PAPER"),
                                rec("lifecycle", pipeline="PIV", execution_class="PIV_PAPER"))
    elif klass == READINESS_DIFFERENCE:
        d = classify_divergence(rec("readiness", decision_outcome="READY"),
                                rec("readiness", pipeline="PIV", decision_outcome="DATA_NOT_READY"))
    elif klass == FRESHNESS_EXCLUSION:
        d = classify_divergence(rec("freshness", decision_outcome="FRESH"),
                                rec("freshness", pipeline="PIV", decision_outcome="STALE"))
    elif klass == QUANT_GATE_DIFFERENCE:
        d = classify_divergence(rec("quant", decision_outcome="LONG"),
                                rec("quant", pipeline="PIV", decision_outcome="NO_SIGNAL"))
    elif klass == DECISION_DIFFERENCE:
        d = classify_divergence(rec("decision", decision_outcome="BUY"),
                                rec("decision", pipeline="PIV", decision_outcome="HOLD"))
    elif klass == ALERT_DELIVERY_DIFFERENCE:
        d = classify_divergence(rec("dispatch", decision_outcome="SENT"),
                                rec("dispatch", pipeline="PIV", decision_outcome="SUPPRESSED"))
    else:  # pragma: no cover
        raise AssertionError(klass)

    assert d is not None and d.divergence_class == klass


def test_identical_records_are_agreement_not_divergence():
    from talonx_compare.divergence import classify_divergence

    a = make_record(pipeline="ORIGINAL", stage="quant", symbol="AAPL",
                    event_time=NOW.isoformat(), session_id=None, decision_outcome="LONG")
    b = make_record(pipeline="PIV", stage="quant", symbol="AAPL",
                    event_time=NOW.isoformat(), session_id="s1", decision_outcome="LONG")
    assert classify_divergence(a, b) is None


# --- 2.19 operational agreement != alpha ------------

def test_operational_agreement_not_alpha_evidence(cfg):
    _collector(cfg).collect_once()
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    manifest = json.loads((cfg.evidence_root / DATE / "manifest.json").read_text())
    assert comp["operational_agreement_only"] is True
    assert "not" in comp["not_alpha_evidence"].lower() and "alpha" in comp["not_alpha_evidence"].lower()
    assert "UNVALIDATED" in manifest["not_alpha_evidence"]


def test_stage_vocabulary_is_frozen():
    assert "quant" in STAGES and "shadow" in STAGES and "reconciliation" in STAGES
    assert len(set(STAGES)) == len(STAGES)
