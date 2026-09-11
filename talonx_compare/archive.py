"""Task 83 §3/§4 / Task 83-R1 §6 -- read-only accessor over the
date-partitioned evidence store, for the browser and Streamlit dashboards.

Every read is pure. A missing / unreadable / stale / corrupt directory is
reported as its explicit state; derived totals from a corrupt archive are
NEVER presented as trustworthy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import CompareConfig
from .evidence import EvidenceWriter
from .health import DEGRADED, HEALTHY, MISSING, NOT_RUN, UNREADABLE, SourceHealth


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
        writer = EvidenceWriter(self.config.evidence_root, trading_date)
        d = writer.dir
        if not d.exists() or not (d / "manifest.json").exists():
            return {
                "trading_date": trading_date,
                "health": SourceHealth(NOT_RUN, f"no evidence archive for {trading_date}").to_dict(),
                "trustworthy": False,
            }

        integ = writer.verify_archive()
        manifest, _ = _read_json(d / "manifest.json")
        runtime_status, _ = _read_json(d / "runtime_status.json")
        comparison, c_err = _read_json(d / "comparison.json")
        divergences, _ = _read_json(d / "divergences.json")
        telegram, _ = _read_json(d / "telegram.json")
        diagnostics, _ = _read_json(d / "diagnostics.json")

        if integ.state == "MISSING":
            health = SourceHealth(MISSING, "; ".join(integ.problems)).to_dict()
        elif integ.state == "UNREADABLE":
            health = SourceHealth(UNREADABLE, "; ".join(integ.problems)).to_dict()
        elif integ.state == "DEGRADED":
            health = SourceHealth(DEGRADED, "archive integrity DEGRADED: " + "; ".join(integ.problems)).to_dict()
        else:
            health = SourceHealth(HEALTHY, "archive present and integrity-verified").to_dict()

        trustworthy = integ.ok
        return {
            "trading_date": trading_date,
            "health": health,
            "trustworthy": trustworthy,
            "archive_integrity": integ.to_dict(),
            "manifest": manifest,
            "runtime_status": runtime_status,
            # derived views are only surfaced as trustworthy when integrity holds
            "comparison": comparison if trustworthy else None,
            "comparison_untrusted": None if trustworthy else comparison,
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
                "trustworthy": False,
                "available_dates": [],
            }
        payload = self.day(dates[-1])
        payload["available_dates"] = dates
        return payload
