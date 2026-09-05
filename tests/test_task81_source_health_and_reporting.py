"""Task 81 §4 -- source-health diagnostics and automatic session reporting.

- C1: missing / corrupt / wrong-session / stale inputs produce EXPLICIT
  source-health diagnostics, never a plausible-looking zero-activity report.
- C2: verified-zero vs absent-optional-ledger vs unreadable-required-source
  are three distinct, named states.
- C3: exposed through the existing PIV projection (build_integrated_projection),
  no new comparison UI.
- C4: automatic session shutdown emits the correctly-scoped session report
  for PASSED / FAILED / INCONCLUSIVE EOD outcomes.
- C5: report generation is pure read -- it never re-triggers broker
  cancel/close; an EOD idempotent retry cancels/closes exactly once.
- C6: the original session/runtime identity is preserved and report-
  generation status is reported separately from broker/EOD status.
- C7: an accepted close request does NOT mark positions confirmed closed.

Clocks are frozen; state dirs are per-test tmp_path; brokers are fakes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from talonx_piv.eod_lifecycle import (
    STATUS_FAILED, STATUS_INCONCLUSIVE, STATUS_PASSED, run_eod_lifecycle,
)
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.observability import build_integrated_projection
from talonx_piv.reporting import build_session_report, finalize_session_report

SESSION_ID = "piv_2026-08-28_120000_deadbeef"
DATE_ET = "2026-08-28"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class SpyBroker:
    """Fake broker that records every cancel/close/submit call."""

    def __init__(self, open_orders=None, positions=None, converge_after=None):
        self._open_orders = list(open_orders or [])
        self._positions = list(positions or [])
        self.cancel_calls = 0
        self.close_calls = 0
        self.submit_calls = 0
        self.identity = object()
        self._reconcile_reads = 0
        self._converge_after = converge_after

    def _require_verified(self):
        pass

    def cancel_all_orders(self):
        self.cancel_calls += 1
        self._open_orders = []
        return []

    def close_all_positions(self):
        self.close_calls += 1
        # "accepted" -- but broker state is NOT necessarily flat afterwards.
        return list(self._positions)

    def submit_order(self, payload):
        self.submit_calls += 1
        return {"id": "should-never-happen"}

    def open_orders(self):
        return list(self._open_orders)

    def positions(self):
        self._reconcile_reads += 1
        if self._converge_after is not None and self._reconcile_reads > self._converge_after:
            self._positions = []
        return list(self._positions)


def _cfg(tmp_path, **over):
    v = dict(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
             broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path)
    v.update(over)
    return PivConfig(**v)


def _life(tmp_path, broker, *, open_symbols=()):
    cfg = _cfg(tmp_path)
    bus = EventBus(tmp_path / "piv_events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "lifecycle_state.json", broker, bus)
    life.start_session(True, True)
    for sym in open_symbols:
        life.state.positions[f"pos_{sym}"] = {"symbol": sym, "status": "OPEN", "quantity": 1, "remaining_quantity": 1}
    life._save()
    return cfg, bus, life


COMMON = dict(live_session_id=SESSION_ID, trading_date_et=DATE_ET, runtime_sha="sha1", config_hash="cfg1")


def _write_events(tmp_path, rows):
    (tmp_path / "piv_events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# C1 -- absent / stale events source must be an explicit diagnostic
# ---------------------------------------------------------------------------

def test_absent_events_source_is_review_required_not_parity_ok(tmp_path):
    report = build_session_report(
        tmp_path / "does_not_exist.jsonl", {}, "IEX_PAPER_PIV",
        trading_date_et=DATE_ET, session_id=SESSION_ID,
    )
    assert report["events_source_health"] == "EVENTS_SOURCE_ABSENT"
    assert report["classification"] == "REVIEW_REQUIRED"      # never PARITY_OK on a missing source


def test_events_for_other_dates_only_is_stale_scope_not_verified_zero(tmp_path):
    _write_events(tmp_path, [
        {"event": "PAPER_SESSION_STARTED", "trading_date_et": "2026-08-27"},
        {"event": "SESSION_COMPLETED", "trading_date_et": "2026-08-27"},
    ])
    report = build_session_report(
        tmp_path / "piv_events.jsonl", {}, "IEX_PAPER_PIV",
        trading_date_et=DATE_ET, session_id=SESSION_ID,
    )
    assert report["events_source_health"] == "EVENTS_SCOPE_EMPTY_FILE_HAS_OTHER_DATES"
    assert report["classification"] == "REVIEW_REQUIRED"


def test_unreadable_events_source_is_flagged(tmp_path):
    (tmp_path / "piv_events.jsonl").write_text("{not json}\n{also bad\n", encoding="utf-8")
    report = build_session_report(tmp_path / "piv_events.jsonl", {}, "IEX_PAPER_PIV", trading_date_et=DATE_ET)
    assert report["events_source_health"] == "EVENTS_SOURCE_UNREADABLE"
    assert report["classification"] == "REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# C2 -- three-way distinction in the integrated projection
# ---------------------------------------------------------------------------

def _seed_min_projection_inputs(tmp_path, *, with_events=True):
    (tmp_path / "session_identity.json").write_text(
        json.dumps({"session_id": SESSION_ID, "trading_date_et": DATE_ET, "runtime_sha": "s", "config_hash": "c"}),
        encoding="utf-8",
    )
    (tmp_path / "lifecycle_state.json").write_text(
        json.dumps({"session_enabled": False, "kill_switch": False, "positions": {}, "orders": {}, "intents": {}}),
        encoding="utf-8",
    )
    if with_events:
        _write_events(tmp_path, [
            {"event": "PAPER_SESSION_STARTED", "trading_date_et": DATE_ET},
            {"event": "SESSION_COMPLETED", "trading_date_et": DATE_ET},
        ])


def test_absent_optional_ledger_is_named_absent_optional(tmp_path):
    _seed_min_projection_inputs(tmp_path)
    proj = build_integrated_projection(tmp_path, session_id=SESSION_ID, trading_date_et=DATE_ET)
    assert proj["source_health"]["decision_ledger"]["status"] == "ABSENT_OPTIONAL"
    assert proj["source_health"]["shadow_ledger"]["status"] == "ABSENT_OPTIONAL"
    assert proj["source_health_ok"] is True                    # absent-optional does not fail health


def test_unreadable_required_source_fails_health(tmp_path):
    _seed_min_projection_inputs(tmp_path)
    (tmp_path / "decision_ledger.json").write_text("{ corrupt", encoding="utf-8")
    proj = build_integrated_projection(tmp_path, session_id=SESSION_ID, trading_date_et=DATE_ET)
    assert proj["source_health"]["decision_ledger"]["status"] == "UNREADABLE"
    assert proj["source_health_ok"] is False
    assert any("decision_ledger" in d and "UNREADABLE" in d for d in proj["source_health_diagnostics"])


def test_verified_zero_vs_zero_uncorroborated(tmp_path):
    # present + parses + empty + a corroborated session run -> VERIFIED_ZERO
    _seed_min_projection_inputs(tmp_path, with_events=True)
    (tmp_path / "decision_ledger.json").write_text("{}", encoding="utf-8")
    proj = build_integrated_projection(tmp_path, session_id=SESSION_ID, trading_date_et=DATE_ET)
    assert proj["source_health"]["decision_ledger"]["status"] == "VERIFIED_ZERO"
    assert proj["source_health_ok"] is True

    # same empty ledger but NO events corroboration -> ZERO_UNCORROBORATED
    (tmp_path / "piv_events.jsonl").unlink()
    proj2 = build_integrated_projection(tmp_path, session_id=SESSION_ID, trading_date_et=DATE_ET)
    assert proj2["source_health"]["decision_ledger"]["status"] == "ZERO_UNCORROBORATED"
    assert proj2["source_health"]["piv_events"]["status"] == "ABSENT_REQUIRED"
    assert proj2["source_health_ok"] is False


def test_wrong_session_records_are_flagged(tmp_path):
    _seed_min_projection_inputs(tmp_path)
    (tmp_path / "decision_ledger.json").write_text(
        json.dumps({"d1": {"session_id": "some_other_session", "recommendation": "WATCH"}}), encoding="utf-8",
    )
    proj = build_integrated_projection(tmp_path, session_id=SESSION_ID, trading_date_et=DATE_ET)
    assert proj["source_health"]["decision_ledger"]["status"] == "WRONG_SESSION"
    assert proj["source_health_ok"] is False


# ---------------------------------------------------------------------------
# C4 / C6 -- automatic shutdown report finaliser, every EOD outcome
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("eod_status", [STATUS_PASSED, STATUS_FAILED, STATUS_INCONCLUSIVE])
def test_finalize_session_report_emits_scoped_report_for_every_outcome(tmp_path, eod_status):
    _seed_min_projection_inputs(tmp_path)
    outcome = {
        "status": eod_status, "session_id": SESSION_ID, "trading_date_et": DATE_ET,
        "reconciliation_run_id": "run-1",
        "reconciliation": {"matched": eod_status == STATUS_PASSED, "broker_open_orders": 0, "broker_positions": 0},
        "exit_code": 0 if eod_status == STATUS_PASSED else 2,
    }
    report = finalize_session_report(
        tmp_path, tmp_path / "piv_events.jsonl", config_feed_mode="IEX_PAPER_PIV",
        live_session_id=SESSION_ID, trading_date_et=DATE_ET, eod_outcome=outcome,
    )
    written = json.loads((tmp_path / "latest_session_report.json").read_text())
    assert written["scoped_to"] == {"session_id": SESSION_ID, "trading_date_et": DATE_ET}
    assert written["eod_status"] == eod_status
    assert written["session_id"] == SESSION_ID
    assert "report_generation_status" in written
    assert report == written


def test_report_generation_status_is_separate_from_eod_status(tmp_path):
    _seed_min_projection_inputs(tmp_path)
    (tmp_path / "quant_funnel_report.json").write_text("{ corrupt funnel", encoding="utf-8")
    outcome = {
        "status": STATUS_PASSED, "session_id": SESSION_ID, "trading_date_et": DATE_ET,
        "reconciliation_run_id": "run-1",
        "reconciliation": {"matched": True, "broker_open_orders": 0, "broker_positions": 0},
    }
    report = finalize_session_report(
        tmp_path, tmp_path / "piv_events.jsonl", config_feed_mode="IEX_PAPER_PIV",
        live_session_id=SESSION_ID, trading_date_et=DATE_ET, eod_outcome=outcome,
    )
    assert report["eod_status"] == STATUS_PASSED                  # the session itself was fine
    assert report["report_generation_status"] == "DEGRADED"       # but the report had a bad input
    assert any("quant_funnel" in d for d in report["report_generation_diagnostics"])


# ---------------------------------------------------------------------------
# C5 -- report generation never re-triggers broker cancel/close;
#       an EOD idempotent retry cancels/closes exactly once
# ---------------------------------------------------------------------------

def test_finalize_session_report_makes_no_broker_calls(tmp_path):
    _seed_min_projection_inputs(tmp_path)
    broker = SpyBroker(positions=[{"symbol": "AAPL", "qty": "1", "side": "long"}])
    outcome = {"status": STATUS_PASSED, "session_id": SESSION_ID, "trading_date_et": DATE_ET,
               "reconciliation_run_id": "r", "reconciliation": {"matched": True, "broker_open_orders": 0, "broker_positions": 0}}
    finalize_session_report(tmp_path, tmp_path / "piv_events.jsonl", config_feed_mode="IEX_PAPER_PIV",
                            live_session_id=SESSION_ID, trading_date_et=DATE_ET, eod_outcome=outcome)
    finalize_session_report(tmp_path, tmp_path / "piv_events.jsonl", config_feed_mode="IEX_PAPER_PIV",
                            live_session_id=SESSION_ID, trading_date_et=DATE_ET, eod_outcome=outcome)
    assert broker.cancel_calls == 0 and broker.close_calls == 0 and broker.submit_calls == 0


def test_eod_idempotent_retry_does_not_repeat_cancel_or_close(tmp_path):
    broker = SpyBroker(positions=[{"symbol": "AAPL", "qty": "1", "side": "long"}], converge_after=1)
    cfg, bus, life = _life(tmp_path, broker, open_symbols=["AAPL"])
    first = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED", **COMMON)
    assert first["status"] == STATUS_FAILED           # broker still shows the position on the 1st reconcile
    second = run_eod_lifecycle(cfg, bus, life, trigger_reason="MANUAL_CLI_INVOCATION", **COMMON)
    assert second["status"] == STATUS_PASSED          # converged on the retry
    assert broker.cancel_calls == 1 and broker.close_calls == 1   # NOT repeated on the retry


# ---------------------------------------------------------------------------
# C7 -- an accepted close request is not "confirmed closed"
# ---------------------------------------------------------------------------

def test_accepted_close_with_broker_still_holding_is_not_confirmed_closed(tmp_path):
    broker = SpyBroker(positions=[{"symbol": "AAPL", "qty": "1", "side": "long"}])  # never converges
    cfg, bus, life = _life(tmp_path, broker, open_symbols=["AAPL"])
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED", **COMMON)
    assert result["status"] == STATUS_FAILED
    assert life.state.positions["pos_AAPL"]["status"] == "OPEN"   # NOT flipped to CLOSED
    assert "SESSION_COMPLETED" not in [json.loads(l)["event"] for l in bus.path.read_text().splitlines() if l.strip()]


def test_broker_confirmed_flat_marks_positions_closed(tmp_path):
    broker = SpyBroker(positions=[{"symbol": "AAPL", "qty": "1", "side": "long"}], converge_after=0)
    cfg, bus, life = _life(tmp_path, broker, open_symbols=["AAPL"])
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED", **COMMON)
    assert result["status"] == STATUS_PASSED
    assert life.state.positions["pos_AAPL"]["status"] == "CLOSED"
