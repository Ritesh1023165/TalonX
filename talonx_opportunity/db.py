"""SQLite helpers. One writer per store (the owning component); every other reader opens ``mode=ro``."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "results" / "opportunity"

# The research lane must never open these (V2 ledger/outbox, shared outbox) -- same list as talonx_premarket.
PROTECTED_DB_NAMES = {"v2_release_rc1.db", "v2_release_rc1_notifications.db", "v2_lane.db", "notifications.db"}


def root_dir(root: str | Path | None = None) -> Path:
    r = Path(root or os.environ.get("TALONX_OPP_ROOT") or DEFAULT_ROOT)
    r.mkdir(parents=True, exist_ok=True)
    return r


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime | None = None) -> str:
    return (t or utcnow()).astimezone(timezone.utc).isoformat()


def connect(path: Path, *, readonly: bool = False, schema: str | None = None) -> sqlite3.Connection:
    if Path(path).name in PROTECTED_DB_NAMES:
        raise PermissionError(f"refusing to open a protected TalonX database from the research lane: {path}")
    if readonly:
        if not Path(path).exists():
            raise FileNotFoundError(path)
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), timeout=30.0)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=10000")
    con.row_factory = sqlite3.Row
    if schema and not readonly:
        con.executescript(schema)
        con.commit()
    return con


def j(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def unj(s: str | None, default=None):
    if s in (None, ""):
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default
