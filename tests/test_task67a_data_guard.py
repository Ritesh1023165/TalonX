"""
tests/test_task67a_data_guard.py
-----------------------------------
Proves research/task67a_lib/data_guard.py actually enforces the
DEVELOPMENT / VALIDATION / REPLICATION split: VALIDATION and REPLICATION
access must fail (even when "allowed" at the contract level, they must
never be reachable through the Stage-1-scoped guard), and DEVELOPMENT
access must succeed and return real, loadable data.

Uses a small SYNTHETIC contract + CSV built in tmp_path (not the repo's
real contract/data) so this test is fast, deterministic, and does not
depend on whether the real Task 67A downloads have completed.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from research.task67a_lib.data_guard import (
    BlockedDataRoleAccessError,
    DataRole,
    DataSplitGuard,
    UnmaterializedRoleError,
)


@pytest.fixture
def synthetic_contract(tmp_path):
    """Builds a tmp_path-local contract + one materialized DEVELOPMENT
    symbol CSV, and two UN-materialized VALIDATION/REPLICATION roles
    (matching the real contract's shape: reserved by date range only,
    no data on disk)."""
    dev_dir = tmp_path / "dev_data"
    dev_dir.mkdir()
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2026-06-01 09:30:00", periods=5, freq="1min", tz="UTC"),
        "open": [100.0, 100.5, 101.0, 100.8, 101.2],
        "high": [100.6, 101.1, 101.4, 101.0, 101.5],
        "low": [99.9, 100.3, 100.7, 100.5, 101.0],
        "close": [100.5, 101.0, 100.8, 101.2, 101.3],
        "volume": [1000, 1100, 900, 1200, 1050],
    })
    bars.to_csv(dev_dir / "AAA.csv", index=False)

    contract = {
        "roles": {
            "DEVELOPMENT": {
                "materialized": True,
                "data_dir": str(dev_dir),
                "symbols": ["AAA"],
                "date_range": {"start": "2026-06-01", "end": "2026-06-01"},
            },
            "VALIDATION": {
                "materialized": False,
                "data_dir": "unused/validation",
                "symbols": ["AAA"],
                "date_range": {"start": "2026-02-01", "end": "2026-02-01"},
            },
            "REPLICATION": {
                "materialized": False,
                "data_dir": "unused/replication",
                "symbols": ["AAA"],
                "date_range": {"start": "2025-11-01", "end": "2025-11-01"},
            },
        }
    }
    contract_path = tmp_path / "data_split_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return contract_path


def test_development_access_succeeds(synthetic_contract):
    guard = DataSplitGuard(allowed_roles=(DataRole.DEVELOPMENT,), contract_path=synthetic_contract)
    df = guard.load_ohlcv(DataRole.DEVELOPMENT)
    assert len(df) == 5
    assert set(df["symbol"]) == {"AAA"}


def test_validation_access_blocked_even_though_role_exists_in_contract(synthetic_contract):
    guard = DataSplitGuard(allowed_roles=(DataRole.DEVELOPMENT,), contract_path=synthetic_contract)
    with pytest.raises(BlockedDataRoleAccessError):
        guard.load_ohlcv(DataRole.VALIDATION)
    with pytest.raises(BlockedDataRoleAccessError):
        guard.resolve_data_dir(DataRole.VALIDATION)


def test_replication_access_blocked(synthetic_contract):
    guard = DataSplitGuard(allowed_roles=(DataRole.DEVELOPMENT,), contract_path=synthetic_contract)
    with pytest.raises(BlockedDataRoleAccessError):
        guard.load_ohlcv(DataRole.REPLICATION)


def test_block_happens_before_unmaterialized_check(synthetic_contract):
    """VALIDATION/REPLICATION in the fixture are also unmaterialized --
    this test asserts the SPECIFIC exception raised is the access-control
    one (BlockedDataRoleAccessError), not UnmaterializedRoleError, proving
    the guard checks role permission FIRST, before touching disk state at
    all. This matters: a caller must be able to tell "you're not allowed"
    apart from "not downloaded yet" even when both are simultaneously true."""
    guard = DataSplitGuard(allowed_roles=(DataRole.DEVELOPMENT,), contract_path=synthetic_contract)
    with pytest.raises(BlockedDataRoleAccessError) as exc_info:
        guard.resolve_data_dir(DataRole.VALIDATION)
    assert not isinstance(exc_info.value, UnmaterializedRoleError)


def test_unmaterialized_role_raises_distinct_error_when_allowed(synthetic_contract):
    """If a guard IS constructed to allow VALIDATION (e.g. by a later,
    separate validation-phase task -- never Stage 1 discovery), asking
    for its data before it has been downloaded must raise
    UnmaterializedRoleError, not silently succeed or raise the
    permission error."""
    guard = DataSplitGuard(allowed_roles=(DataRole.VALIDATION,), contract_path=synthetic_contract)
    with pytest.raises(UnmaterializedRoleError):
        guard.resolve_data_dir(DataRole.VALIDATION)


def test_unregistered_symbol_request_raises(synthetic_contract):
    guard = DataSplitGuard(allowed_roles=(DataRole.DEVELOPMENT,), contract_path=synthetic_contract)
    with pytest.raises(ValueError):
        guard.load_ohlcv(DataRole.DEVELOPMENT, symbols=["ZZZ_NOT_REGISTERED"])


def test_missing_contract_file_raises_filenotfound(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        DataSplitGuard(allowed_roles=(DataRole.DEVELOPMENT,), contract_path=missing)


def test_default_stage1_guard_only_allows_development():
    """Construction-level check independent of any contract file: the
    Stage-1-scoped default (allowed_roles=(DataRole.DEVELOPMENT,), the
    class default) must never include VALIDATION or REPLICATION."""
    assert DataSplitGuard.__init__.__defaults__[0] == (DataRole.DEVELOPMENT,)


# ---------------------------------------------------------------------
# Integration tests against the REAL Task 67A contract/data (not a
# synthetic fixture) -- these are skipped gracefully if the real
# contract/data haven't been materialized yet in this checkout, so this
# file remains runnable at any point in Task 67A's own progress.
# ---------------------------------------------------------------------

from research.task67a_lib.data_guard import DEFAULT_CONTRACT_PATH, get_stage1_guard  # noqa: E402

_real_contract_missing = not DEFAULT_CONTRACT_PATH.exists()


@pytest.mark.skipif(_real_contract_missing, reason="real data_split_contract.json not present yet")
def test_real_stage1_guard_blocks_validation_and_replication():
    guard = get_stage1_guard()
    with pytest.raises(BlockedDataRoleAccessError):
        guard.resolve_data_dir(DataRole.VALIDATION)
    with pytest.raises(BlockedDataRoleAccessError):
        guard.resolve_data_dir(DataRole.REPLICATION)


@pytest.mark.skipif(_real_contract_missing, reason="real data_split_contract.json not present yet")
def test_real_stage1_guard_development_access_succeeds_and_loads_real_data():
    guard = get_stage1_guard()
    df = guard.load_ohlcv(DataRole.DEVELOPMENT)
    assert len(df) > 0
    # Real DEVELOPMENT role covers the full 35-symbol PIV universe.
    assert len(set(df["symbol"])) == 35


@pytest.mark.skipif(_real_contract_missing, reason="real data_split_contract.json not present yet")
def test_real_validation_and_replication_are_unmaterialized():
    """Even a guard explicitly constructed to allow VALIDATION/REPLICATION
    (simulating a future validation-phase task, never Stage 1) must still
    fail today, because no data has actually been downloaded for either
    role yet -- see data_split_contract.md for why."""
    validation_guard = DataSplitGuard(allowed_roles=(DataRole.VALIDATION,))
    with pytest.raises(UnmaterializedRoleError):
        validation_guard.resolve_data_dir(DataRole.VALIDATION)
    replication_guard = DataSplitGuard(allowed_roles=(DataRole.REPLICATION,))
    with pytest.raises(UnmaterializedRoleError):
        replication_guard.resolve_data_dir(DataRole.REPLICATION)
