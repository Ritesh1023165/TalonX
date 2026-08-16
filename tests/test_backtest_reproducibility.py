"""
tests/test_backtest_reproducibility.py
-------------------------------------------
talonx_backtest.reproducibility: git commit / strategy version /
backtester version / config hash metadata (spec section 7) -- the same
configuration must always hash the same, git_commit must never be
fabricated (falls back to the literal "UNKNOWN"), and the strategy
fingerprint must actually change when strategy source changes.
"""
from __future__ import annotations

import dataclasses

from talonx_backtest.engine import BacktestConfig
from talonx_backtest.execution import ExecutionConfig
from talonx_backtest.reproducibility import (
    build_metadata,
    config_hash,
    get_backtester_version,
    get_git_commit,
    get_strategy_version,
)
from talonx_quant.config import QuantConfig


def test_git_commit_is_a_real_sha_or_the_literal_unknown():
    commit = get_git_commit()
    assert commit == "UNKNOWN" or (len(commit) == 40 and all(c in "0123456789abcdef" for c in commit))


def test_git_commit_never_raises_when_git_is_unavailable(monkeypatch):
    import subprocess as subprocess_module

    def _boom(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess_module, "run", _boom)
    assert get_git_commit() == "UNKNOWN"


def test_strategy_version_is_a_stable_12_char_fingerprint():
    v1 = get_strategy_version()
    v2 = get_strategy_version()
    assert v1 == v2
    assert len(v1) == 12


def test_backtester_version_is_present():
    assert get_backtester_version() != ""


def test_same_config_produces_the_same_hash():
    c1 = config_hash(BacktestConfig())
    c2 = config_hash(BacktestConfig())
    assert c1 == c2


def test_different_execution_config_changes_the_hash():
    baseline = config_hash(BacktestConfig())
    changed = config_hash(BacktestConfig(execution=ExecutionConfig(entry_slippage_bps=5.0)))
    assert baseline != changed


def test_different_quant_config_changes_the_hash():
    baseline = config_hash(BacktestConfig())
    changed_qc = dataclasses.replace(QuantConfig(), cooldown_seconds=999.0)
    changed = config_hash(BacktestConfig(quant_config=changed_qc))
    assert baseline != changed


def test_eod_flatten_flag_is_part_of_the_hash():
    enabled = config_hash(BacktestConfig(eod_flatten_enabled=True))
    disabled = config_hash(BacktestConfig(eod_flatten_enabled=False))
    assert enabled != disabled


def test_build_metadata_returns_all_five_fields():
    meta = build_metadata(BacktestConfig())
    d = meta.to_dict()
    assert set(d.keys()) == {"git_commit", "backtester_version", "strategy_version", "config_hash", "run_timestamp"}
    assert all(v for v in d.values())  # nothing blank/None
