"""Task 66B-PREP Parts 5/6/10: a small, best-effort, additive metadata file
describing the most recent run_talonx.py startup -- which market-data
provider was configured, which paper-execution path this run uses, which
of the six modules were enabled, commit SHA, and when it started.

Pure observability: written once at startup (see run_talonx.py's main()),
wrapped in try/except there so a write failure never blocks startup. Read
optionally by generate_eod_report.py (degrades to "unknown" if missing or
unreadable, same as every other optional store there) so an EOD report can
say which provider/execution path/commit it's actually reporting on,
without guessing or fabricating anything if this file isn't there --
e.g. an older run, or one where the write failed.

Same ~/.talonx home directory every other store in this project already
uses (see talonx_watchlist/config.py), not results/ -- this is local
runtime state, not a committed research artifact.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Any

RUNTIME_METADATA_PATH = Path(
    os.environ.get("TALONX_RUNTIME_METADATA_PATH", str(Path.home() / ".talonx" / "runtime_metadata.json"))
)


def _current_commit_sha() -> str | None:
    try:
        repo_root = Path(__file__).resolve().parent.parent
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, timeout=10,
        ).strip()
    except Exception:  # noqa: BLE001 -- best-effort metadata only
        return None


def write_runtime_metadata(
    *, run_mode: str, market_data_provider_configured: str, paper_execution_path: str,
    quant_enabled: bool, brain_enabled: bool, core_enabled: bool, dispatch_enabled: bool,
    paper_trading_enabled: bool, path: Path | None = None,
) -> dict[str, Any]:
    payload = {
        "run_mode": run_mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _current_commit_sha(),
        "pid": os.getpid(),
        "market_data_provider_configured": market_data_provider_configured,
        "paper_execution_path": paper_execution_path,
        "modules_enabled": {
            "quant": quant_enabled, "brain": brain_enabled, "core": core_enabled,
            "dispatch": dispatch_enabled, "paper_trading": paper_trading_enabled,
        },
    }
    target = path or RUNTIME_METADATA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def read_runtime_metadata(path: Path | None = None) -> dict[str, Any] | None:
    """Returns None if the file is missing or unreadable -- never raises.
    Callers (e.g. generate_eod_report.py) treat that exactly like every
    other optional store: report "unknown"/omit, don't fail."""
    target = path or RUNTIME_METADATA_PATH
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
