"""Task 83 §3/§4 -- read-only accessor over the date-partitioned evidence
store, for the browser and Streamlit dashboards.

Everything here is a pure read. A missing / unreadable / stale directory
is reported as its explicit health state, never as an empty-but-plausible
success.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .config import CompareConfig
from .evidence import EvidenceWriter
from .health import MISSING, NOT_RUN, UNREADABLE, HEALTHY, DEGRADED, SourceHealth


def _read_json(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


class CompareArchive:
    def __init__(self, config: CompareConfig | None = None) -> None:
        self.config = config or CompareConfig()

    def available_dates(self) -> list[str]:
        root = self.config.evidence_root
        if not root.exists():
            return []
        return sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and (p / "manifest.json").exists()
        )

    def day(self, trading_date: str) -> dict[str, Any]:
        """Everything the dashboards need for one date, plus an explicit
        archive-integrity verdict."""
        writer = EvidenceWriter(self.config.evidence_root, trading_date)
        d = writer.dir
        if not d.exists():
            return {
                "trading_date": trading_date,
                "health": SourceHealth(NOT_RUN, f"no evidence directory for {trading_date}").to_dict(),
            }
        manifest, m_err = _read_json(d / "manifest.json")
        comparison, c_err = _read_json(d / "comparison.json")
        divergences, dv_err = _read_json(d / "divergences.json")
        telegram, t_err = _read_json(d / "telegram.json")
        diagnostics, dg_err = _read_json(d / "diagnostics.json")
        hashes_ok, hash_problems = writer.verify_file_hashes()

        errs = [e for e in (m_err, c_err, dv_err, t_err, dg_err) if e and e != "missing"]
        if m_err == "missing":
            health = SourceHealth(MISSING, "manifest.json missing").to_dict()
        elif errs:
            health = SourceHealth(UNREADABLE, "; ".join(errs)).to_dict()
        elif not hashes_ok:
            health = SourceHealth(DEGRADED, "file hash mismatch: " + "; ".join(hash_problems)).to_dict()
        else:
            health = SourceHealth(HEALTHY, "archive present and hash-verified").to_dict()

        return {
            "trading_date": trading_date,
            "health": health,
            "archive_integrity": {
                "file_hashes_ok": hashes_ok,
                "problems": hash_problems,
            },
            "manifest": manifest,
            "comparison": comparison,
            "divergences": (divergences or {}).get("divergences", []) if divergences else [],
            "telegram": telegram,
            "diagnostics": (diagnostics or {}).get("diagnostics", []) if diagnostics else [],
        }

    def latest(self) -> dict[str, Any]:
        dates = self.available_dates()
        if not dates:
            return {
                "trading_date": None,
                "health": SourceHealth(NOT_RUN, "no comparison evidence has been collected yet").to_dict(),
                "available_dates": [],
            }
        payload = self.day(dates[-1])
        payload["available_dates"] = dates
        return payload
