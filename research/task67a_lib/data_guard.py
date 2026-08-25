"""
research/task67a_lib/data_guard.py
------------------------------------
Code-level guard enforcing Task 67A's DEVELOPMENT / VALIDATION /
REPLICATION data-split contract (see
results/task67a_phenomenon_discovery/data_split_contract.json and
.md). This is the ONLY sanctioned way Stage 1 (the 6-family phenomenon
discovery screen) should resolve a historical-data directory: importing
pandas.read_csv or talonx_backtest.data.load_ohlcv_directory directly on
a hardcoded results/... or data/... path bypasses this guard entirely, so
Stage 1 scripts should route every data load through a `DataSplitGuard`
instance instead.

Why this exists: the discovery plan (results/task65_piv/
next_alpha_discovery_plan.md) requires "No family may be iterated against
validation or replication data" -- a *procedural* rule that is trivial to
violate by accident (a copy-pasted path, a symbol list that happens to
include a validation-window CSV). This module turns that procedural rule
into something that raises `BlockedDataRoleAccessError` instead of
silently returning wrong-role data.

Design:
  - The split contract (results/task67a_phenomenon_discovery/
    data_split_contract.json) is the single source of truth for which
    date ranges/symbols/data directories belong to which role, and
    whether that role's data has actually been materialized to disk yet.
  - A `DataSplitGuard` is constructed with an explicit `allowed_roles`
    set -- Stage 1 code should construct it with
    `allowed_roles=(DataRole.DEVELOPMENT,)` (the module-level
    `STAGE1_DISCOVERY_GUARD` convenience instance already does this) so
    that ANY attempt to resolve/load VALIDATION or REPLICATION data
    raises immediately, before any file I/O happens.
  - This is defense-in-depth, not the only line of defense: it does not
    stop a script from opening a raw CSV outside this module entirely.
    Every Stage 1 script is still expected to route all historical-data
    loading through a `DataSplitGuard`.
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT_PATH = ROOT / "results/task67a_phenomenon_discovery/data_split_contract.json"


class DataRole(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    REPLICATION = "REPLICATION"


class BlockedDataRoleAccessError(PermissionError):
    """Raised when code asks a DataSplitGuard for a role it was not
    constructed to allow (e.g. Stage 1 discovery code asking for
    VALIDATION or REPLICATION data). This is a PermissionError subclass
    (not a plain Exception) so a caller doing broad
    `except Exception` handling for I/O problems does not accidentally
    swallow a data-discipline violation silently -- catch this
    specifically if you ever legitimately need to, which should be rare."""


class UnmaterializedRoleError(FileNotFoundError):
    """Raised when a role is allowed but its data has not actually been
    downloaded to disk yet (contract["roles"][role]["materialized"] is
    False) -- distinct from BlockedDataRoleAccessError so a caller can
    tell "you're not allowed to see this" apart from "this doesn't exist
    on disk yet"."""


class DataSplitGuard:
    """Loads and enforces one data_split_contract.json. See module
    docstring for the intended usage pattern."""

    def __init__(
        self,
        allowed_roles: tuple[DataRole, ...] = (DataRole.DEVELOPMENT,),
        contract_path: str | Path = DEFAULT_CONTRACT_PATH,
    ) -> None:
        self.contract_path = Path(contract_path)
        if not self.contract_path.exists():
            raise FileNotFoundError(
                f"Data split contract not found at {self.contract_path}. "
                "This must exist BEFORE any Stage 1 phenomenon-discovery code runs -- "
                "see results/task67a_phenomenon_discovery/data_split_contract.md."
            )
        self.contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        self.allowed_roles = frozenset(DataRole(r) for r in allowed_roles)

    def _role_str(self, role: DataRole | str) -> str:
        return DataRole(role).value

    def assert_allowed(self, role: DataRole | str) -> None:
        """Raises BlockedDataRoleAccessError if `role` is not in this
        guard's allowed_roles. Call this FIRST, before any file path is
        even constructed, in any function that resolves data for a given
        role."""
        role_value = self._role_str(role)
        if DataRole(role_value) not in self.allowed_roles:
            raise BlockedDataRoleAccessError(
                f"Role {role_value!r} is not accessible via this guard "
                f"(allowed_roles={sorted(r.value for r in self.allowed_roles)}). "
                "Stage 1 discovery code must only ever request DEVELOPMENT data -- "
                "see results/task67a_phenomenon_discovery/data_split_contract.md."
            )

    def role_info(self, role: DataRole | str) -> dict:
        """Returns the contract's raw metadata dict for `role`, WITHOUT
        checking allowed_roles -- use only for inspection/reporting, not
        as a way to read data for a blocked role. `resolve_data_dir` and
        `load_ohlcv` are the access-controlled paths; this is not."""
        role_value = self._role_str(role)
        try:
            return self.contract["roles"][role_value]
        except KeyError as exc:
            raise KeyError(f"Role {role_value!r} not present in {self.contract_path}") from exc

    def resolve_data_dir(self, role: DataRole | str) -> Path:
        """Access-controlled: raises BlockedDataRoleAccessError if `role`
        is not allowed, else UnmaterializedRoleError if the contract
        marks this role's data as not yet downloaded, else returns the
        Path to the role's data directory (guaranteed to exist on disk)."""
        self.assert_allowed(role)
        info = self.role_info(role)
        if not info.get("materialized", False):
            raise UnmaterializedRoleError(
                f"Role {self._role_str(role)!r} is reserved (dates: "
                f"{info.get('date_range')}) but its data has not been materialized "
                "to disk yet -- this is expected for VALIDATION/REPLICATION during "
                "Stage 0/Stage 1; it must be downloaded in a dedicated later task, "
                "AFTER a family is selected from discovery, per the data discipline "
                "in results/task65_piv/next_alpha_discovery_plan.md."
            )
        data_dir = ROOT / info["data_dir"]
        if not data_dir.is_dir():
            raise UnmaterializedRoleError(
                f"Contract claims role {self._role_str(role)!r} is materialized at "
                f"{data_dir}, but that directory does not exist. Contract is stale "
                "or data was deleted -- do not silently proceed."
            )
        return data_dir

    def load_ohlcv(self, role: DataRole | str, symbols: list[str] | None = None):
        """Access-controlled convenience wrapper around
        talonx_backtest.data.load_ohlcv_directory: raises
        BlockedDataRoleAccessError / UnmaterializedRoleError exactly as
        resolve_data_dir does (it calls resolve_data_dir first, before
        any pandas I/O), otherwise returns the loaded, normalized,
        multi-symbol OHLCV DataFrame for that role. `symbols`, if given,
        is further intersected with the role's registered symbol list --
        requesting a symbol NOT in the role's registered universe raises
        ValueError rather than silently returning nothing for it."""
        data_dir = self.resolve_data_dir(role)  # raises before any I/O if not allowed
        info = self.role_info(role)
        registered_symbols = set(info.get("symbols", []))
        if symbols is not None:
            unregistered = sorted(set(symbols) - registered_symbols)
            if unregistered:
                raise ValueError(
                    f"Symbol(s) {unregistered} are not registered for role "
                    f"{self._role_str(role)!r} in the data split contract."
                )
        # Lazy import: keeps this module importable without talonx_backtest
        # present (e.g. from a lightweight tooling context), and avoids a
        # circular-import risk since talonx_backtest itself does not (and
        # must not) import anything from research/.
        from talonx_backtest.data import load_ohlcv_directory

        return load_ohlcv_directory(data_dir, symbols=symbols)


#: Convenience instance for Stage 1 discovery code: only DEVELOPMENT is
#: allowed. Importing and using THIS instance (rather than constructing a
#: bespoke DataSplitGuard with a wider allowed_roles) is the intended,
#: reviewable pattern for every Stage 1 family script.
STAGE1_DISCOVERY_GUARD = None  # populated lazily by get_stage1_guard() below


def get_stage1_guard(contract_path: str | Path = DEFAULT_CONTRACT_PATH) -> DataSplitGuard:
    """Returns (constructing on first call) the module-level Stage 1
    discovery guard, which only allows DataRole.DEVELOPMENT. Lazy rather
    than a module-level singleton built at import time, so importing this
    module never fails just because the contract file doesn't exist yet
    (e.g. during this module's own test collection) -- the FileNotFoundError
    only fires when a caller actually asks for the guard."""
    global STAGE1_DISCOVERY_GUARD
    if STAGE1_DISCOVERY_GUARD is None or Path(contract_path) != STAGE1_DISCOVERY_GUARD.contract_path:
        STAGE1_DISCOVERY_GUARD = DataSplitGuard(
            allowed_roles=(DataRole.DEVELOPMENT,), contract_path=contract_path
        )
    return STAGE1_DISCOVERY_GUARD
