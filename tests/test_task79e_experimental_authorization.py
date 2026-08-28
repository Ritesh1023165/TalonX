"""Task 79E -- experimental_authorization.py strict-parsing and binding
tests. TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE throughout."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from talonx_piv.experimental_authorization import load_experimental_authorization

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)


def _base(**overrides) -> dict:
    payload = {
        "enabled": True,
        "experiment_id": "exp-001",
        "operator_acknowledged_unvalidated": True,
        "strategy_id": "MACD_BULLISH_CROSS",
        "strategy_version": "v1",
        "runtime_sha": "abc123",
        "config_hash": "cfg123",
        "allowed_symbols": ["AAPL"],
        "trading_date_et": "2026-08-28",
        "session_scope": "REGULAR",
        "activated_at": "2026-08-28T09:00:00+00:00",
        "expires_at": "2026-08-28T20:00:00+00:00",
        "paper": None,
    }
    payload.update(overrides)
    return payload


def _write(tmp_path, payload):
    path = tmp_path / "experimental_authorization.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _binding(**overrides):
    kwargs = dict(
        symbol="AAPL", trading_date_et="2026-08-28", strategy_id="MACD_BULLISH_CROSS",
        strategy_version="v1", runtime_sha="abc123", config_hash="cfg123", now=NOW,
    )
    kwargs.update(overrides)
    return kwargs


def test_missing_file_returns_none(tmp_path):
    assert load_experimental_authorization(tmp_path / "nope.json") is None


def test_disabled_returns_none(tmp_path):
    path = _write(tmp_path, _base(enabled=False))
    assert load_experimental_authorization(path) is None


def test_string_false_does_not_act_as_true(tmp_path):
    path = _write(tmp_path, _base(enabled="false"))
    assert load_experimental_authorization(path) is None


def test_string_true_does_not_act_as_true(tmp_path):
    path = _write(tmp_path, _base(enabled="true"))
    assert load_experimental_authorization(path) is None


def test_valid_minimal_loads_and_permits_entry(tmp_path):
    path = _write(tmp_path, _base())
    auth = load_experimental_authorization(path)
    assert auth is not None
    ok, reason = auth.permits_entry(**_binding())
    assert ok, reason


def test_missing_operator_acknowledgement_rejected(tmp_path):
    path = _write(tmp_path, _base(operator_acknowledged_unvalidated=False))
    assert load_experimental_authorization(path) is None


def test_wrong_symbol_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(symbol="MSFT"))
    assert not ok and reason == "SYMBOL_NOT_IN_ALLOWED_SET"


def test_wrong_date_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(trading_date_et="2026-08-29"))
    assert not ok and reason == "WRONG_TRADING_DATE"


def test_wrong_strategy_id_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(strategy_id="OTHER"))
    assert not ok and reason == "WRONG_STRATEGY_ID"


def test_wrong_strategy_version_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(strategy_version="v2"))
    assert not ok and reason == "WRONG_STRATEGY_VERSION"


def test_wrong_runtime_sha_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(runtime_sha="different"))
    assert not ok and reason == "WRONG_RUNTIME_SHA"


def test_wrong_config_hash_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(config_hash="different"))
    assert not ok and reason == "WRONG_CONFIG_HASH"


def test_expired_permission_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(now=datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)))
    assert not ok and reason == "PERMISSION_EXPIRED"


def test_not_yet_active_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(now=datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)))
    assert not ok and reason == "PERMISSION_NOT_YET_ACTIVE"


def test_naive_now_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base()))
    ok, reason = auth.permits_entry(**_binding(now=datetime(2026, 8, 28, 10, 0)))
    assert not ok and reason == "NOW_NOT_TIMEZONE_AWARE"


def test_naive_activated_at_rejected(tmp_path):
    path = _write(tmp_path, _base(activated_at="2026-08-28T09:00:00"))
    assert load_experimental_authorization(path) is None


def test_expires_before_activates_rejected(tmp_path):
    path = _write(tmp_path, _base(activated_at="2026-08-28T20:00:00+00:00", expires_at="2026-08-28T09:00:00+00:00"))
    assert load_experimental_authorization(path) is None


def test_missing_required_field_rejected(tmp_path):
    for field_name in ("experiment_id", "strategy_id", "strategy_version", "runtime_sha", "config_hash", "trading_date_et", "session_scope"):
        payload = _base()
        del payload[field_name]
        assert load_experimental_authorization(_write(tmp_path, payload)) is None, field_name


def test_empty_allowed_symbols_rejected(tmp_path):
    assert load_experimental_authorization(_write(tmp_path, _base(allowed_symbols=[]))) is None


def test_non_list_allowed_symbols_rejected(tmp_path):
    assert load_experimental_authorization(_write(tmp_path, _base(allowed_symbols="AAPL"))) is None


def test_malformed_json_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_experimental_authorization(path) is None


def test_non_dict_json_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[1,2,3]", encoding="utf-8")
    assert load_experimental_authorization(path) is None


# ---------------------------------------------------------------------------
# PAPER sub-permission
# ---------------------------------------------------------------------------

def _paper_base(**overrides):
    payload = {
        "enabled": True, "account_id_binding": "acct-1", "max_quantity_per_entry": 1.0,
        "max_reference_notional_budget": 500.0, "max_entry_count": 2, "max_concurrent_exposure": 1,
    }
    payload.update(overrides)
    return payload


def test_paper_none_blocks_paper_execution(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base(paper=None)))
    ok, reason = auth.permits_paper_execution(**_binding(), account_id="acct-1")
    assert not ok and reason == "EXPERIMENTAL_PAPER_EXECUTION_NOT_ENABLED"


def test_paper_disabled_blocks_paper_execution(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base(paper=_paper_base(enabled=False))))
    ok, reason = auth.permits_paper_execution(**_binding(), account_id="acct-1")
    assert not ok and reason == "EXPERIMENTAL_PAPER_EXECUTION_NOT_ENABLED"


def test_paper_enabled_valid_permits(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base(paper=_paper_base())))
    ok, reason = auth.permits_paper_execution(**_binding(), account_id="acct-1")
    assert ok, reason


def test_paper_wrong_account_rejected(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base(paper=_paper_base())))
    ok, reason = auth.permits_paper_execution(**_binding(), account_id="acct-WRONG")
    assert not ok and reason == "WRONG_PAPER_ACCOUNT"


def test_paper_negative_quantity_rejected(tmp_path):
    payload = _base(paper=_paper_base(max_quantity_per_entry=-1.0))
    assert load_experimental_authorization(_write(tmp_path, payload)) is None


def test_paper_zero_quantity_rejected(tmp_path):
    payload = _base(paper=_paper_base(max_quantity_per_entry=0.0))
    assert load_experimental_authorization(_write(tmp_path, payload)) is None


def test_paper_nan_notional_rejected(tmp_path):
    payload = _base(paper=_paper_base(max_reference_notional_budget=float("nan")))
    assert load_experimental_authorization(_write(tmp_path, payload)) is None


def test_paper_infinite_notional_rejected(tmp_path):
    payload = _base(paper=_paper_base(max_reference_notional_budget=float("inf")))
    assert load_experimental_authorization(_write(tmp_path, payload)) is None


def test_paper_bool_as_entry_count_rejected(tmp_path):
    """bool is an int subclass -- must not slip through as a valid count."""
    payload = _base(paper=_paper_base(max_entry_count=True))
    assert load_experimental_authorization(_write(tmp_path, payload)) is None


def test_paper_fractional_entry_count_rejected(tmp_path):
    payload = _base(paper=_paper_base(max_entry_count=1.5))
    assert load_experimental_authorization(_write(tmp_path, payload)) is None


def test_paper_missing_account_binding_rejected(tmp_path):
    payload_paper = _paper_base()
    del payload_paper["account_id_binding"]
    assert load_experimental_authorization(_write(tmp_path, _base(paper=payload_paper))) is None


def test_wrong_account_also_blocks_via_entry_binding_reason_when_entry_itself_invalid(tmp_path):
    auth = load_experimental_authorization(_write(tmp_path, _base(paper=_paper_base())))
    ok, reason = auth.permits_paper_execution(**_binding(symbol="MSFT"), account_id="acct-1")
    assert not ok and reason == "SYMBOL_NOT_IN_ALLOWED_SET"  # entry-level check runs first
