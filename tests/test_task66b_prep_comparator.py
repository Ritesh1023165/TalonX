"""Task 66B-PREP Part 7: read-only PIV-vs-full-app comparator.

Covers the honesty contract explicitly required by the task: never
fabricate parity, report missing coverage plainly, and never classify a
stage MATCH unless real evidence exists on BOTH sides."""
from __future__ import annotations

import json

from talonx_ops.comparator import (
    MATCH,
    MISSING_EVENT,
    NOT_APPLICABLE_TO_PIV,
    PIV_APPLICABLE_STAGES,
    STAGES,
    build_comparator_report,
    compare,
    load_piv_evidence,
)


def write_piv_events(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")


def test_missing_file_returns_empty_evidence_not_an_error(tmp_path):
    evidence = load_piv_evidence(tmp_path / "does_not_exist.jsonl")
    assert evidence == {}


def test_malformed_line_skipped_not_fatal(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('not json\n{"event": "SIGNAL", "source": "STRATEGY", "symbol": "AAPL", "timestamp": "t"}\n', encoding="utf-8")
    evidence = load_piv_evidence(path)
    assert "AAPL" in evidence and "quant_signal" in evidence["AAPL"]


def test_strategy_signal_maps_to_quant_signal_stage(tmp_path):
    path = tmp_path / "events.jsonl"
    write_piv_events(path, [{"event": "SIGNAL", "source": "STRATEGY", "symbol": "AAPL", "timestamp": "t"}])
    evidence = load_piv_evidence(path)
    assert evidence["AAPL"]["quant_signal"]["event"] == "SIGNAL"


def test_probe_signal_not_mapped_to_quant_signal_stage(tmp_path):
    """A PIV_LIFECYCLE_PROBE order is explicitly not alpha evidence and not
    a real strategy signal -- must never be counted as one."""
    path = tmp_path / "events.jsonl"
    write_piv_events(path, [{"event": "ORDER_INTENT", "source": "PIV_LIFECYCLE_PROBE", "symbol": "AAPL", "timestamp": "t"}])
    evidence = load_piv_evidence(path)
    assert "quant_signal" not in evidence.get("AAPL", {})
    assert evidence["AAPL"]["paper_decision"]["source"] == "PIV_LIFECYCLE_PROBE"


def test_event_with_no_symbol_is_skipped(tmp_path):
    path = tmp_path / "events.jsonl"
    write_piv_events(path, [{"event": "EOD_FLATTEN", "symbol": None, "timestamp": "t"}])
    evidence = load_piv_evidence(path)
    assert evidence == {}


def test_stage_out_of_piv_scope_classified_not_applicable():
    rows = compare({"AAPL": {"quant_signal": {"x": 1}}}, {})
    by_stage = {r.stage: r for r in rows}
    assert by_stage["brain_received"].classification == NOT_APPLICABLE_TO_PIV
    assert by_stage["core_result"].classification == NOT_APPLICABLE_TO_PIV
    assert by_stage["dispatch_received"].classification == NOT_APPLICABLE_TO_PIV


def test_piv_applicable_stage_with_no_full_app_evidence_is_missing_not_fabricated():
    rows = compare({"AAPL": {"quant_signal": {"x": 1}}}, {})
    by_stage = {r.stage: r for r in rows}
    assert by_stage["quant_signal"].classification == MISSING_EVENT
    assert by_stage["quant_signal"].full_app_evidence is None  # never invented


def test_evidence_on_both_sides_is_match():
    rows = compare(
        {"AAPL": {"quant_signal": {"x": 1}}},
        {"AAPL": {"quant_signal": {"y": 2}}},
    )
    by_stage = {r.stage: r for r in rows}
    assert by_stage["quant_signal"].classification == MATCH


def test_full_app_only_evidence_is_missing_event():
    rows = compare({}, {"AAPL": {"quant_signal": {"y": 2}}})
    by_stage = {r.stage: r for r in rows}
    assert by_stage["quant_signal"].classification == MISSING_EVENT


def test_every_stage_covered_for_every_symbol():
    rows = compare({"AAPL": {}}, {"MSFT": {}})
    symbols_stages = {(r.symbol, r.stage) for r in rows}
    assert symbols_stages == {("AAPL", s) for s in STAGES} | {("MSFT", s) for s in STAGES}


def test_piv_applicable_stages_are_a_subset_of_all_stages():
    assert PIV_APPLICABLE_STAGES <= set(STAGES)
    assert PIV_APPLICABLE_STAGES  # non-empty


def test_build_comparator_report_never_fabricates_full_app_evidence_when_none_exists(tmp_path, monkeypatch):
    piv_path = tmp_path / "events.jsonl"
    write_piv_events(piv_path, [{"event": "SIGNAL", "source": "STRATEGY", "symbol": "AAPL", "timestamp": "t"}])
    # Force the full-app side to report nothing, regardless of whatever
    # real local stores happen to contain in this dev environment --
    # isolates this test from environment state.
    import talonx_ops.comparator as comparator_module
    monkeypatch.setattr(comparator_module, "load_full_app_evidence_for_date", lambda date_str: {})

    report = build_comparator_report(piv_path, "2026-08-25")
    assert report["full_app_symbols_with_evidence"] == []
    assert report["piv_symbols_with_evidence"] == ["AAPL"]
    assert report["classification_counts"].get(MATCH, 0) == 0  # nothing to match against
    assert all(row["classification"] != MATCH for row in report["rows"])
