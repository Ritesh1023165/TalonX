"""
talonx_backtest.reproducibility
------------------------------------
Metadata every backtest result should carry so it can actually be
reproduced later: the exact code involved, the full effective
configuration, and when it ran. Never fabricates a value it can't
determine -- an unavailable git commit is recorded as the literal
string "UNKNOWN", not omitted or guessed.

This project defines no formal semantic version for either the
strategy or the backtester, so both "version" fields here are content
fingerprints (sha256, first 12 hex chars) rather than invented version
numbers:
  - strategy_version: fingerprint of talonx_quant's own strategy/
    indicator/config/session source files -- changes IF AND ONLY IF the
    frozen strategy's own code changes.
  - backtester_version: talonx_backtest.__version__ if this package
    ever adopts one; falls back to "UNKNOWN" rather than inventing one.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STRATEGY_FILES = (
    _REPO_ROOT / "talonx_quant" / "strategy.py",
    _REPO_ROOT / "talonx_quant" / "indicators.py",
    _REPO_ROOT / "talonx_quant" / "config.py",
    _REPO_ROOT / "talonx_quant" / "session.py",
)


def get_git_commit() -> str:
    """The current HEAD commit SHA, or the literal string "UNKNOWN" if
    git isn't available, this isn't a git checkout, or the command
    otherwise fails -- never guessed, never silently omitted."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    if result.returncode != 0:
        return "UNKNOWN"
    sha = result.stdout.strip()
    return sha if sha else "UNKNOWN"


def get_strategy_version() -> str:
    """sha256 (first 12 hex chars) of the frozen strategy's own source
    files. A missing file contributes a distinct, deterministic marker
    to the hash rather than silently being skipped, so a broken
    checkout doesn't masquerade as a valid fingerprint."""
    digest = hashlib.sha256()
    for path in _STRATEGY_FILES:
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"MISSING:" + str(path).encode())
    return digest.hexdigest()[:12]


def get_backtester_version() -> str:
    import talonx_backtest
    return getattr(talonx_backtest, "__version__", "UNKNOWN")


def _to_jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def config_hash(config) -> str:
    """sha256 (first 12 hex chars) of every field of a BacktestConfig
    (QuantConfig + ExecutionConfig + backtest-mechanics settings) that
    affects behavior. Two runs with the SAME config_hash used the exact
    same effective configuration -- not just "similar" settings."""
    payload = _to_jsonable(config)
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


@dataclass(frozen=True)
class ReproducibilityMetadata:
    git_commit: str
    backtester_version: str
    strategy_version: str
    config_hash: str
    run_timestamp: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def build_metadata(config) -> ReproducibilityMetadata:
    return ReproducibilityMetadata(
        git_commit=get_git_commit(),
        backtester_version=get_backtester_version(),
        strategy_version=get_strategy_version(),
        config_hash=config_hash(config),
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )
