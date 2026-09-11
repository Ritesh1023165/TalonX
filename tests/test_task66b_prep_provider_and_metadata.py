"""Task 66B-PREP Parts 1, 5, 6, 10: provider/execution-path explicitness,
runtime_metadata.json write/read, and the runtime manifest table."""
from __future__ import annotations

import json

from talonx_ops.provider_status import (
    LOCAL_SIMULATED_PAPER_LEDGER,
    POLYGON_WEBSOCKET,
    YFINANCE_POLLING,
    configured_market_data_provider,
    paper_execution_path_label,
)
from talonx_ops.runtime_manifest import FULL_APP_RUNTIME_COMPONENTS, runtime_graph_stages
from talonx_ops.runtime_metadata import read_runtime_metadata, write_runtime_metadata


class _FakeMarketData:
    def __init__(self, polygon_api_key):
        self.polygon_api_key = polygon_api_key


class _FakeSettings:
    def __init__(self, polygon_api_key):
        self.market_data = _FakeMarketData(polygon_api_key)


def test_configured_provider_reflects_polygon_key_presence(monkeypatch):
    # talonx_ingest.config.settings is a frozen dataclass -- replace this
    # module's own `settings` binding instead of mutating a frozen field.
    import talonx_ops.provider_status as provider_status
    monkeypatch.setattr(provider_status, "settings", _FakeSettings("fake-key"))
    assert configured_market_data_provider() == POLYGON_WEBSOCKET


def test_configured_provider_falls_back_to_yfinance_when_no_key(monkeypatch):
    import talonx_ops.provider_status as provider_status
    monkeypatch.setattr(provider_status, "settings", _FakeSettings(None))
    assert configured_market_data_provider() == YFINANCE_POLLING


def test_paper_execution_path_is_always_local_never_alpaca():
    label = paper_execution_path_label()
    assert label == LOCAL_SIMULATED_PAPER_LEDGER
    assert "alpaca" not in label.lower()


def test_write_and_read_runtime_metadata_roundtrip(tmp_path):
    path = tmp_path / "runtime_metadata.json"
    payload = write_runtime_metadata(
        run_mode="FULL_APP", market_data_provider_configured="YFINANCE_POLLING",
        paper_execution_path=LOCAL_SIMULATED_PAPER_LEDGER, quant_enabled=True, brain_enabled=True,
        core_enabled=True, dispatch_enabled=True, paper_trading_enabled=True, path=path,
    )
    assert path.is_file()
    read_back = read_runtime_metadata(path=path)
    assert read_back == payload
    assert read_back["run_mode"] == "FULL_APP"
    assert read_back["modules_enabled"]["brain"] is True


def test_read_runtime_metadata_missing_file_returns_none(tmp_path):
    assert read_runtime_metadata(path=tmp_path / "nope.json") is None


def test_read_runtime_metadata_corrupt_file_returns_none_not_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert read_runtime_metadata(path=path) is None


def test_runtime_metadata_never_contains_raw_secret_fields(tmp_path):
    payload = write_runtime_metadata(
        run_mode="FULL_APP", market_data_provider_configured="YFINANCE_POLLING",
        paper_execution_path=LOCAL_SIMULATED_PAPER_LEDGER, quant_enabled=False, brain_enabled=False,
        core_enabled=False, dispatch_enabled=False, paper_trading_enabled=False,
        path=tmp_path / "runtime_metadata.json",
    )
    serialized = json.dumps(payload).lower()
    for forbidden in ("api_key", "token", "secret", "password"):
        assert forbidden not in serialized


def test_runtime_components_have_unique_names():
    names = [c.name for c in FULL_APP_RUNTIME_COMPONENTS]
    assert len(names) == len(set(names))


def test_runtime_components_cover_all_six_modules():
    modules_mentioned = " ".join(c.module for c in FULL_APP_RUNTIME_COMPONENTS)
    for expected in ("talonx_ingest", "talonx_quant", "talonx_brain", "talonx_core", "talonx_dispatch", "talonx_paper"):
        assert expected in modules_mentioned


def test_runtime_graph_stages_non_empty_and_ordered_tuple():
    stages = runtime_graph_stages()
    assert isinstance(stages, tuple) and len(stages) >= 5
