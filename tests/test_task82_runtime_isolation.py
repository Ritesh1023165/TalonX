"""Task 82 deterministic Original/PIV isolation contract."""

from __future__ import annotations

import json
from pathlib import Path

from talonx_core import process_guard
from talonx_piv import cli
from talonx_piv.config import PivConfig
from talonx_piv.isolation import build_piv_quant_config, piv_quant_db_path, validate_piv_isolation
from talonx_piv.preflight import config_hash


def _rows(*rows: dict) -> str:
    return "\n".join(json.dumps(row) for row in rows)


def _output(value: str):
    def run(*args, **kwargs):
        return value
    return run


def test_default_piv_bindings_are_separate_and_telegram_is_off(tmp_path, monkeypatch):
    monkeypatch.delenv("TALONX_PIV_REDIS_URL", raising=False)
    monkeypatch.delenv("TALONX_PIV_REDIS_NAMESPACE", raising=False)
    monkeypatch.delenv("TALONX_PIV_TELEGRAM_ENABLED", raising=False)
    cfg = PivConfig(state_dir=tmp_path)

    passed, detail = validate_piv_isolation(cfg)

    assert passed, detail
    assert cfg.redis_url.endswith("/1")
    assert cfg.telegram_enabled is False
    assert all(channel.startswith("talonx:piv:") for channel in (
        cfg.market_stream_channel, cfg.signals_channel, cfg.rejected_candidates_channel,
        cfg.news_events_channel, cfg.paper_trades_channel,
    ))
    assert piv_quant_db_path(cfg) == (tmp_path / "piv_quant.db").resolve()


def test_reused_quant_scanner_receives_only_piv_bindings(tmp_path):
    cfg = PivConfig(state_dir=tmp_path)
    quant = build_piv_quant_config(cfg)

    assert quant.redis_url == cfg.redis_url
    assert quant.market_stream_channel == cfg.market_stream_channel
    assert quant.signals_channel == cfg.signals_channel
    assert quant.rejected_candidates_channel == cfg.rejected_candidates_channel
    assert quant.news_events_channel == cfg.news_events_channel
    assert quant.paper_trades_channel == cfg.paper_trades_channel
    assert Path(quant.db_path) == piv_quant_db_path(cfg)


def test_session_config_hash_changes_when_runtime_binding_changes(tmp_path):
    first = PivConfig(state_dir=tmp_path / "one")
    second = PivConfig(state_dir=tmp_path / "two")
    third = PivConfig(state_dir=tmp_path / "one", redis_url="redis://localhost:6379/2")
    assert config_hash(first) != config_hash(second)
    assert config_hash(first) != config_hash(third)


def test_same_redis_database_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_REDIS_URL", "redis://localhost:6379/0")
    cfg = PivConfig(state_dir=tmp_path, redis_url="redis://localhost:6379/0")
    passed, detail = validate_piv_isolation(cfg)
    assert passed is False
    assert "same Redis endpoint/database" in detail


def test_pubsub_overlap_fails_even_with_separate_redis_database(tmp_path):
    cfg = PivConfig(
        state_dir=tmp_path, redis_url="redis://localhost:6379/1",
        signals_channel="talonx:signals:quant",
    )
    passed, detail = validate_piv_isolation(cfg)
    assert passed is False
    assert "Pub/Sub" in detail


def test_quant_database_overlap_and_piv_telegram_each_fail_closed(tmp_path, monkeypatch):
    original_db = tmp_path / "original_quant.db"
    monkeypatch.setenv("TALONX_QUANT_DB_PATH", str(original_db))
    cfg = PivConfig(state_dir=tmp_path, quant_db_path=original_db, telegram_enabled=True)
    passed, detail = validate_piv_isolation(cfg)
    assert passed is False
    assert "Quant persistence" in detail
    assert "Telegram must remain disabled" in detail


def test_original_allows_only_marked_isolated_piv_peer():
    isolated = _rows({"pid": 20, "role": "PIV", "isolated": True})
    assert process_guard.no_competing_talonx_process(
        exclude_pid=10, current_role=process_guard.ORIGINAL_ROLE, check_output=_output(isolated),
    )[0] is True

    unmarked = _rows({"pid": 20, "role": "PIV", "isolated": False})
    assert process_guard.no_competing_talonx_process(
        exclude_pid=10, current_role=process_guard.ORIGINAL_ROLE, check_output=_output(unmarked),
    )[0] is False


def test_piv_allows_original_only_after_its_bindings_are_verified():
    original = _rows({"pid": 20, "role": "ORIGINAL", "isolated": False})
    assert process_guard.no_competing_talonx_process(
        exclude_pid=10, current_role=process_guard.PIV_ROLE, piv_isolation_verified=True,
        check_output=_output(original),
    )[0] is True
    assert process_guard.no_competing_talonx_process(
        exclude_pid=10, current_role=process_guard.PIV_ROLE, piv_isolation_verified=False,
        check_output=_output(original),
    )[0] is False


def test_same_role_duplicate_and_unclassified_output_fail_closed():
    duplicate = _rows({"pid": 20, "role": "PIV", "isolated": True})
    assert process_guard.no_competing_talonx_process(
        exclude_pid=10, current_role=process_guard.PIV_ROLE,
        piv_isolation_verified=True, check_output=_output(duplicate),
    )[0] is False
    assert process_guard.no_competing_talonx_process(
        exclude_pid=10, current_role=process_guard.PIV_ROLE,
        piv_isolation_verified=True, check_output=_output("20\n"),
    )[0] is False


def test_piv_event_bus_and_outbox_have_no_telegram_adapter_by_default(tmp_path):
    cfg = PivConfig(state_dir=tmp_path)
    bus, _, _, _ = cli.runtime(cfg)
    assert bus.telegram_send is None


def test_runtime_start_requires_explicit_isolation_marker(capsys):
    assert cli.main(["start", "--approved-sha", "abc", "--no-live-loop"]) == 2
    assert "--isolated-parallel is required" in capsys.readouterr().err
