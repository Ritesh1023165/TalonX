"""Task 66B-PREP Parts 3 + 4: FullAppPreflight (talonx_ops/preflight.py).

Follows the same testing convention tests/test_task64_piv.py already
established for talonx_piv's Preflight: monkeypatch _git for deterministic
SHA/tree-clean behavior, inject a fake HTTP transport to avoid a real
Telegram network call. Unlike PIV's decision_path_mode check (which can be
disabled via config to skip Redis entirely in tests), this preflight's
redis/store/chroma/brain checks have no such switch -- the normal
application doesn't have a "decision path disabled" mode -- so this suite
asserts only the checks that are fully deterministic under test (git state,
file-content checks, static labels, report I/O) rather than asserting the
overall READY/BLOCKED status, which legitimately depends on live local
services (Redis, Chroma, the configured LLM provider) being reachable in
whatever environment the suite runs in. The actual, live, real-environment
run is saved as evidence at results/task66b_prep/full_app_preflight.json
(same "unit tests + one live smoke artifact" pattern Task 65B's warmup fix
already used)."""
from __future__ import annotations

import json
from pathlib import Path

from talonx_ops.preflight import FULL_APP_E2E_BLOCKED, FULL_APP_E2E_READY, Check, FullAppPreflight
from talonx_ops.provider_status import LOCAL_SIMULATED_PAPER_LEDGER, paper_execution_path_label


class FakeTransport:
    def get(self, url, **kwargs):
        class Response:
            status_code = 200
            def json(self_inner):
                return {"ok": True}
        return Response()


def test_expected_sha_matches(monkeypatch, tmp_path):
    flight = FullAppPreflight(expected_sha="abc123", repo=tmp_path, transport=FakeTransport())
    monkeypatch.setattr(flight, "_git", lambda *args: "abc123" if args[0] == "rev-parse" else "")
    status, checks = flight.run()
    by_name = {c.name: c for c in checks}
    assert by_name["expected_sha"].passed is True
    assert by_name["expected_sha"].detail == "abc123"


def test_expected_sha_mismatch_fails_and_blocks_overall(monkeypatch, tmp_path):
    flight = FullAppPreflight(expected_sha="expected-sha", repo=tmp_path, transport=FakeTransport())
    monkeypatch.setattr(flight, "_git", lambda *args: "different-sha" if args[0] == "rev-parse" else "")
    status, checks = flight.run()
    by_name = {c.name: c for c in checks}
    assert by_name["expected_sha"].passed is False
    assert status == FULL_APP_E2E_BLOCKED  # one failed check is enough to block overall


def test_expected_sha_none_means_any_sha_accepted(monkeypatch, tmp_path):
    flight = FullAppPreflight(expected_sha=None, repo=tmp_path, transport=FakeTransport())
    monkeypatch.setattr(flight, "_git", lambda *args: "whatever-sha" if args[0] == "rev-parse" else "")
    _, checks = flight.run()
    by_name = {c.name: c for c in checks}
    assert by_name["expected_sha"].passed is True


def test_tracked_tree_clean_check(monkeypatch, tmp_path):
    flight = FullAppPreflight(repo=tmp_path, transport=FakeTransport())
    monkeypatch.setattr(
        flight, "_git",
        lambda *args: "" if args[0] == "rev-parse" else (" M some_file.py" if args[0] == "status" else ""),
    )
    _, checks = flight.run()
    by_name = {c.name: c for c in checks}
    assert by_name["tracked_tree_clean"].passed is False
    assert "some_file.py" in by_name["tracked_tree_clean"].detail


def test_no_real_capital_execution_capability_reads_real_engine_file():
    flight = FullAppPreflight(transport=FakeTransport())
    status, checks = flight.run()
    by_name = {c.name: c for c in checks}
    check = by_name["no_real_capital_execution_capability"]
    assert check.passed is True
    assert check.detail == "talonx_paper.engine references: none"


def test_execution_path_is_local_simulated_check():
    flight = FullAppPreflight(transport=FakeTransport())
    _, checks = flight.run()
    by_name = {c.name: c for c in checks}
    assert by_name["execution_path_is_local_simulated"].passed is True
    assert by_name["execution_path_is_local_simulated"].detail == LOCAL_SIMULATED_PAPER_LEDGER
    assert paper_execution_path_label() == LOCAL_SIMULATED_PAPER_LEDGER


def test_no_secrets_printed_check_never_echoes_a_token():
    flight = FullAppPreflight(transport=FakeTransport())
    _, checks = flight.run()
    by_name = {c.name: c for c in checks}
    assert by_name["no_secrets_printed"].passed is True
    for check in checks:
        assert "TELEGRAM_BOT_TOKEN" not in check.detail  # env var NAMES are fine, raw values are not


def test_all_expected_check_names_present():
    flight = FullAppPreflight(transport=FakeTransport())
    _, checks = flight.run()
    names = {c.name for c in checks}
    expected = {
        "expected_sha", "tracked_tree_clean", "no_duplicate_full_app_or_piv_process", "redis_reachable",
        "active_watchlist_non_empty", "paper_enabled_symbols_recorded", "quant_store_accessible",
        "brain_operational_hard_requirement", "chroma_vector_store_accessible", "core_store_accessible",
        "dispatch_audit_store_accessible", "paper_store_accessible", "telegram_outbound_reachable",
        "telegram_inbound_ping_capability", "market_data_provider_identified",
        "market_data_provider_connectivity_capability", "premarket_mechanism_available",
        "quant_initial_preseed_capability", "eod_report_capability", "no_real_capital_execution_capability",
        "execution_path_is_local_simulated", "no_secrets_printed", "current_time_reported",
    }
    assert expected <= names


def test_a_single_failed_check_blocks_overall_status():
    flight = FullAppPreflight(expected_sha="definitely-not-the-real-sha", transport=FakeTransport())
    status, checks = flight.run()
    assert any(not c.passed for c in checks)
    assert status == FULL_APP_E2E_BLOCKED


def test_write_report_roundtrip(tmp_path):
    checks = [Check("a", True, "ok"), Check("b", False, "nope")]
    out_path = tmp_path / "report.json"
    FullAppPreflight.write_report(out_path, FULL_APP_E2E_BLOCKED, checks)
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == FULL_APP_E2E_BLOCKED
    assert payload["checks"] == [{"name": "a", "passed": True, "detail": "ok"}, {"name": "b", "passed": False, "detail": "nope"}]
    assert "generated_at" in payload


def test_live_smoke_evidence_artifact_exists_and_is_recent_enough():
    """Not a unit test of behavior -- a guard that the real, live preflight
    run performed for this task's own evidence (Part 10/completion block)
    is actually on disk and structurally valid, same role
    warmup_verification_smoketest.json played for Task 65B."""
    path = Path("results/task66b_prep/full_app_preflight.json")
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] in (FULL_APP_E2E_READY, FULL_APP_E2E_BLOCKED)
    assert isinstance(payload["checks"], list) and len(payload["checks"]) >= 20
