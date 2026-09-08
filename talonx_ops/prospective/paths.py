"""Session paths + safe env resolution for the prospective operator."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Frozen operational locations (Task 113 / Task 114 locked governance).
V2_DB_PATH = REPO_ROOT / "v2_lane.db"
V2_STATUS_PATH = REPO_ROOT / "v2_service_status.json"
RESULTS_ROOT = REPO_ROOT / "results"


def session_dir(for_date: date | None = None) -> Path:
    d = for_date or datetime.now(timezone.utc).date()
    return RESULTS_ROOT / f"prospective_{d.isoformat()}"


def ensure_session_dir(for_date: date | None = None) -> Path:
    p = session_dir(for_date)
    (p / "checkpoints").mkdir(parents=True, exist_ok=True)
    return p


def resolve_env() -> dict[str, str]:
    """The 4 non-secret V2 vars the companion needs.  Resolution order:
    already-exported env  ->  repo .env (gitignored)  ->  frozen defaults.
    Secrets (APCA_*, TELEGRAM_*, ...) are NOT handled here -- they stay in
    .env and are inherited by child processes untouched."""
    wanted = {
        "TALONX_ACTIVE_STRATEGY_PROFILE": "INSIDER_BUY_CLUSTER_V2",
        "TALONX_V2_STARTING_CASH_USD": "300000",
        "TALONX_V2_DB_PATH": str(V2_DB_PATH),
        "TALONX_V2_STATUS_PATH": str(V2_STATUS_PATH),
    }
    dotenv: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            dotenv[k.strip()] = v.strip().strip('"').strip("'")
    out: dict[str, str] = {}
    for k, default in wanted.items():
        out[k] = os.environ.get(k) or dotenv.get(k) or default
    return out


def apply_env(env: dict[str, str]) -> None:
    for k, v in env.items():
        os.environ.setdefault(k, v)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def now_pair() -> dict[str, str]:
    n = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        lon = n.astimezone(ZoneInfo("Europe/London")).isoformat()
    except Exception:  # noqa: BLE001
        lon = n.isoformat()
    return {"utc": n.isoformat(), "europe_london": lon}
