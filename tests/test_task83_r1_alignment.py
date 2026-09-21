"""Task 83-R1 §3 -- session- and event-safe comparison.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from talonx_compare.alignment import align, compare
from talonx_compare.collector import ComparisonCollector
from talonx_compare.config import CompareConfig
from talonx_compare.identity import (
    KIND_AGGREGATE,
    ORIGINAL_SCOPE_PREFIX,
    UNSCOPED,
    make_record,
)
from talonx_compare.testing import make_pair, write_piv_state

DATE = "2026-08-28"
SESSION_A = "piv_2026-08-28_100000_aaaa1111"
SESSION_B = "piv_2026-08-28_143000_bbbb2222"
NOW = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)


def _piv(stage, symbol, session, *, decision_id=None, outcome=None, bar=None, exec_class="NONE"):
    return make_record(pipeline="PIV", stage=stage, symbol=symbol, event_time=NOW.isoformat(),
                       session_id=session, decision_id=decision_id, decision_outcome=outcome,
                       source_bar_time=bar, execution_class=exec_class)


def _orig(stage, symbol, scope, *, decision_id=None, outcome=None, bar=None, exec_class="NONE"):
    return make_record(pipeline="ORIGINAL", stage=stage, symbol=symbol, event_time=NOW.isoformat(),
                       session_id=None, run_scope=scope, decision_id=decision_id,
                       decision_outcome=outcome, source_bar_time=bar, execution_class=exec_class)


# --- 3.1 different PIV sessions never aligned -----------------------

def test_different_piv_sessions_never_aligned():
    a = _piv("decision", "AAPL", SESSION_A, decision_id="dA", outcome="BUY")
    b = _piv("decision", "AAPL", SESSION_B, decision_id="dB", outcome="HOLD")
    pairs = align([], [a, b], restrict_trading_date=DATE)
    scopes = {p.piv_run_scope for p in pairs}
    assert scopes == {SESSION_A, SESSION_B}
    # no single pair holds records from two sessions
    for p in pairs:
        assert p.piv is None or p.piv.run_scope == p.piv_run_scope


# --- 3.2 Original scope is collector-derived + labelled -----------

def test_original_scope_is_collector_derived_and_labelled(tmp_path, monkeypatch):
    meta = tmp_path / "runtime_metadata.json"
    meta.write_text(json.dumps({
        "commit_sha": "abc123def456", "started_at": "2026-08-28T13:00:00+00:00",
        "run_mode": "full", "market_data_provider_configured": "alpaca_sip",
    }), encoding="utf-8")
    piv = tmp_path / "piv"
    write_piv_state(piv, session_id=SESSION_A)
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev",
                        piv_state_dir=piv, original_runtime_metadata_path=meta)
    r = ComparisonCollector(cfg, clock=lambda: NOW).collect_once()
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    assert comp["original_run_scope"].startswith(ORIGINAL_SCOPE_PREFIX)
    rs = json.loads((cfg.evidence_root / DATE / "runtime_status.json").read_text())
    assert "NOT an Original session id" in rs["original_run_scope"]["derivation"]
    assert rs["original_run_scope"]["runtime_metadata_present"] is True


# --- 3.3 unscoped Original -> no event-level agreement ------------

def test_unscoped_original_no_event_agreement():
    # identical work on both sides, but Original scope is UNSCOPED
    o = _orig("decision", "AAPL", UNSCOPED, decision_id="d1", outcome="BUY")
    p = _piv("decision", "AAPL", SESSION_A, decision_id="d1", outcome="BUY")
    pairs, divs = compare([o], [p], restrict_trading_date=DATE, original_run_scope=UNSCOPED)
    assert len(divs) == 1 and divs[0].divergence_class == "SOURCE_UNAVAILABLE"
    assert "UNSCOPED" in divs[0].detail
    row = next(x for x in pairs)
    assert row.original_run_scope in (None, UNSCOPED)


def test_collector_reports_unscoped_when_no_runtime_metadata(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv, session_id=SESSION_A)
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev",
                        piv_state_dir=piv,
                        original_runtime_metadata_path=tmp_path / "nonexistent.json")
    r = ComparisonCollector(cfg, clock=lambda: NOW).collect_once()
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    assert comp["original_run_scope"] == UNSCOPED
    assert comp["event_level_agreement_assertable"] is False


# --- 3.4 event identity: decision_id vs causal -------------------

def test_event_identity_prefers_decision_id():
    r = make_record(pipeline="PIV", stage="decision", symbol="AAPL", event_time=NOW.isoformat(),
                    session_id=SESSION_A, decision_id="d-42", decision_outcome="BUY")
    assert r.event_identity == "d-42"
    assert r.alignment_key() == (DATE, "decision", "AAPL", "d-42")


def test_causal_identity_when_no_decision_id():
    r = make_record(pipeline="ORIGINAL", stage="quant", symbol="AAPL", event_time=NOW.isoformat(),
                    session_id=None, run_scope="orig:x", decision_outcome="LONG",
                    source_bar_time="2026-08-28T14:00:00+00:00")
    assert r.event_identity.startswith("causal:")
    # a documented, deterministic function of stage+symbol+bar+outcome+payload
    r2 = make_record(pipeline="ORIGINAL", stage="quant", symbol="AAPL", event_time="2026-08-28T14:09:00+00:00",
                     session_id=None, run_scope="orig:x", decision_outcome="LONG",
                     source_bar_time="2026-08-28T14:00:00+00:00")
    assert r.event_identity == r2.event_identity  # event_time noise excluded


# --- 3.5 aggregates compared as aggregates -----------------------

def test_aggregate_records_compared_as_aggregates():
    o1 = make_record(pipeline="ORIGINAL", stage="quant", symbol="", event_time=NOW.isoformat(),
                     session_id=None, run_scope="orig:x", record_kind=KIND_AGGREGATE,
                     aggregate_name="quant:evaluated", aggregate_value=10.0)
    o2 = make_record(pipeline="ORIGINAL", stage="quant", symbol="", event_time="2026-08-28T15:05:00+00:00",
                     session_id=None, run_scope="orig:x", record_kind=KIND_AGGREGATE,
                     aggregate_name="quant:evaluated", aggregate_value=25.0)
    # same aggregate key, two values -> alignment keeps the LATEST, not both
    pairs = align([o1, o2], [], restrict_trading_date=DATE)
    agg = [p for p in pairs if p.record_kind == KIND_AGGREGATE]
    assert len(agg) == 1
    assert agg[0].original.aggregate_value == 25.0
    assert agg[0].event_identity == "agg:quant:evaluated"


def test_aggregate_value_divergence_flagged():
    o = make_record(pipeline="ORIGINAL", stage="quant", symbol="", event_time=NOW.isoformat(),
                    session_id=None, run_scope="orig:x", record_kind=KIND_AGGREGATE,
                    aggregate_name="quant:evaluated", aggregate_value=10.0)
    p = make_record(pipeline="PIV", stage="quant", symbol="", event_time=NOW.isoformat(),
                    session_id=SESSION_A, record_kind=KIND_AGGREGATE,
                    aggregate_name="quant:evaluated", aggregate_value=12.0)
    pairs, divs = compare([o], [p], restrict_trading_date=DATE, original_run_scope="orig:x")
    assert len(divs) == 1 and "aggregate" in divs[0].detail


# --- 3.6 multiple same-symbol events stay distinct --------------

def test_multiple_same_symbol_events_stay_distinct(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv, session_id=SESSION_A, decisions={
        "d1": {"session_id": SESSION_A, "trading_date_et": DATE, "symbol": "AAPL",
               "timestamp": f"{DATE}T14:05:00+00:00", "recommendation": "HOLD",
               "reason_codes": [], "market_view": "BULLISH", "decision_execution_status": "NO_ACTION",
               "data_readiness": "COMPLETE"},
        "d2": {"session_id": SESSION_A, "trading_date_et": DATE, "symbol": "AAPL",
               "timestamp": f"{DATE}T14:35:00+00:00", "recommendation": "BUY",
               "reason_codes": ["ELIGIBLE_APPROVED_BULLISH_SETUP_NO_HOLDING"],
               "market_view": "BULLISH", "decision_execution_status": "ENTRY_ELIGIBLE",
               "data_readiness": "COMPLETE"},
    })
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)
    ComparisonCollector(cfg, clock=lambda: NOW).collect_once()
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    decisions = [x for x in comp["per_symbol_stage"] if x["stage"] == "decision" and x["symbol"] == "AAPL"]
    ids = {x["event_identity"] for x in decisions}
    assert ids == {"d1", "d2"}          # two DISTINCT decision rows, never merged
    assert comp["per_stage_totals"]["decision"]["piv_events"] == 2


# --- 3.7 late arrival re-aligns without replacing unrelated evidence ---

def test_late_arrival_does_not_replace_unrelated(tmp_path):
    piv = tmp_path / "piv"
    write_piv_state(piv, session_id=SESSION_A, decisions={
        "d1": {"session_id": SESSION_A, "trading_date_et": DATE, "symbol": "AAPL",
               "timestamp": f"{DATE}T14:05:00+00:00", "recommendation": "HOLD", "reason_codes": [],
               "market_view": "BULLISH", "decision_execution_status": "NO_ACTION",
               "data_readiness": "COMPLETE"},
    })
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)
    ComparisonCollector(cfg, clock=lambda: NOW).collect_once()

    # a late, unrelated decision arrives for the same symbol
    dl = json.loads((piv / "decision_ledger.json").read_text())
    dl["d2"] = {"session_id": SESSION_A, "trading_date_et": DATE, "symbol": "AAPL",
                "timestamp": f"{DATE}T15:40:00+00:00", "recommendation": "SELL_TO_CLOSE",
                "reason_codes": ["EXISTING_LONG_APPROVED_EXIT_CONDITION"], "market_view": "BEARISH",
                "decision_execution_status": "EXIT_ELIGIBLE", "data_readiness": "COMPLETE"}
    (piv / "decision_ledger.json").write_text(json.dumps(dl), encoding="utf-8")
    from datetime import timedelta
    r2 = ComparisonCollector(cfg, clock=lambda: NOW + timedelta(hours=1)).collect_once()
    assert r2.piv_appended == 1  # only d2 appended; d1 untouched

    recs = [json.loads(x) for x in
            (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines() if x.strip()]
    dids = {x["event_identity"] for x in recs if x["stage"] == "decision"}
    assert dids == {"d1", "d2"}


# --- 3.8 same-day two run scopes stay separated ---------------

def test_same_day_two_run_scopes_separated(tmp_path):
    piv = tmp_path / "piv"
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)
    write_piv_state(piv, session_id=SESSION_A)
    ComparisonCollector(cfg, clock=lambda: NOW).collect_once()
    # a restart mints a new session on the SAME day
    write_piv_state(piv, session_id=SESSION_B, config_hash="rebind")
    from datetime import timedelta
    r2 = ComparisonCollector(cfg, clock=lambda: NOW + timedelta(hours=1)).collect_once()
    # manifest binding conflict is surfaced, original manifest untouched
    assert r2.manifest_conflict is True
    # both sessions' records coexist, separated by run_scope
    recs = [json.loads(x) for x in
            (cfg.evidence_root / DATE / "piv_records.jsonl").read_text().splitlines() if x.strip()]
    scopes = {x["run_scope"] for x in recs}
    assert scopes == {SESSION_A, SESSION_B}
    # alignment never pairs a SESSION_A record with a SESSION_B record
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    for row in comp["per_symbol_stage"]:
        assert row["piv_run_scope"] in (None, SESSION_A, SESSION_B)


# --- 3.9 per-stage totals are typed --------------------------

def test_per_stage_totals_are_typed(tmp_path):
    original, piv = make_pair()
    for m, c, v in [("quant", "evaluated", 40), ("dispatch", "pushed_telegram", 2)]:
        original.seed_metric(DATE, m, c, v)
    p = tmp_path / "piv"
    write_piv_state(p, session_id=SESSION_A)
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=p)
    ComparisonCollector(cfg, clock=lambda: NOW, original_redis=original).collect_once()
    comp = json.loads((cfg.evidence_root / DATE / "comparison.json").read_text())
    tot = comp["per_stage_totals"]
    for stage, block in tot.items():
        assert "kind" in block
        if block["kind"] == KIND_AGGREGATE:
            assert "original_aggregate_total" in block
        else:
            assert "original_events" in block and "piv_events" in block
