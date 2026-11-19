"""
EDGAR filing-calendar classification for the V2@1 forward crawler (2026-10-13 acquisition correction).

Deterministic: the versioned calendar file (docs/research/protocols/edgar_calendar/EDGAR_CLOSURES_V1.json, built from
official SEC pages archived under docs/research/evidence/2026-10-13_edgar_closure_calendar/) is loaded ONCE per crawl;
no online lookup. Dates are classified as:
  WEEKEND               Saturday / Sunday -- no daily index expected (pre-existing behaviour)
  SEC_CLOSED            an officially documented EDGAR closure (scheduled or exceptional) -- no daily index expected
  EXPECTED_FILING_DAY   a weekday in a supported year that is not a documented closure -- the index is required
  UNKNOWN_COVERAGE      a weekday in a year the calendar does not cover -- callers must FAIL, never guess
Not derived from the stock-exchange calendar or a generic federal-holiday library.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CALENDAR_PATH = REPO / "docs" / "research" / "protocols" / "edgar_calendar" / "EDGAR_CLOSURES_V1.json"
WEEKEND, SEC_CLOSED, EXPECTED, UNKNOWN = "WEEKEND", "SEC_CLOSED", "EXPECTED_FILING_DAY", "UNKNOWN_COVERAGE"


class CalendarError(RuntimeError):
    pass


class EdgarCalendar:
    def __init__(self, path: Path | None = None):
        path = Path(path) if path is not None else CALENDAR_PATH      # resolved at call time
        raw = path.read_bytes()
        try:
            d = json.loads(raw.decode("utf-8"))
            self.calendar_id = str(d["calendar_id"])
            self.years = {int(y) for y in d["supported_years"]}
            closures = {}
            for kind in ("scheduled_closures", "exceptional_closures"):
                for c in d[kind]:
                    day = date.fromisoformat(c["date"])
                    if day.year not in self.years:
                        raise CalendarError(f"{kind} {day} outside supported_years")
                    closures[day] = {"name": c.get("name"), "kind": kind}
        except (KeyError, TypeError, ValueError) as exc:
            raise CalendarError(f"invalid EDGAR calendar {Path(path).name}: {type(exc).__name__}: {exc}") from None
        self.closures = closures
        self.path = Path(path)
        self.sha256 = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()

    def classify(self, day: date) -> str:
        if day.weekday() >= 5:
            return WEEKEND
        if day.year not in self.years:
            return UNKNOWN
        return SEC_CLOSED if day in self.closures else EXPECTED

    def provenance(self) -> dict:
        try:
            rel = str(self.path.relative_to(REPO)).replace("\\", "/")
        except ValueError:
            rel = self.path.name
        return {"calendar_id": self.calendar_id, "sha256": self.sha256, "supported_years": sorted(self.years),
                "path": rel}
