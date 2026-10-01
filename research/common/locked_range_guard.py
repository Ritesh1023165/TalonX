"""Generalized per-program holdout guard (ported from research/task75b_preflight/holdout.py @ 14e770e).

A LockedRangeGuard is configured PER PROGRAM: its own locked date ranges, its own durable state file
(results/<program_dir>/guard_state.json) and its own append-only audit log. It is enforced at BOTH layers:
  DOWNLOAD  check_range(start, end)       before any request is built
  LOAD      check_range / check_frame(df) before any loaded data is used
A program can only read/write ITS OWN state file: the constructor refuses any state path outside the program's own
results directory, and refuses a state file whose recorded program differs (so EVENT_RESPONSE_MAP_V1 can never load,
write or transition Task75's guard state). Locked ranges are immutable once the program is registered.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE_ROOTS = (Path("C:/workspace/TalonX").resolve(),)
OPEN_END = date(9999, 12, 31)


class HoldoutViolation(RuntimeError):
    pass


def _d(x) -> date:
    return x if isinstance(x, date) and not isinstance(x, datetime) else date.fromisoformat(str(x)[:10])


def intersects(start, end, window: tuple[date, date]) -> bool:
    s, e = _d(start), _d(end)
    if e < s:
        s, e = e, s
    return s <= window[1] and e >= window[0]


def assert_research_path(p: Path) -> None:
    rp = Path(p).resolve()
    for live in LIVE_ROOTS:
        if rp == live or live in rp.parents:
            raise HoldoutViolation(f"refusing to write under the live application worktree: {rp}")


@dataclass(frozen=True)
class ProgramSpec:
    program: str
    results_dir: str                       # relative to the worktree root, e.g. results/event_response_map_v1
    locked: tuple[tuple[str, date, date], ...]


class LockedRangeGuard:
    def __init__(self, spec: ProgramSpec, *, root: Path = ROOT):
        self.spec = spec
        self.dir = (root / spec.results_dir).resolve()
        self.path = self.dir / "guard_state.json"
        assert_research_path(self.path)
        if self.path.exists():
            doc = json.loads(self.path.read_text())
            if doc.get("program") != spec.program:
                raise HoldoutViolation(f"state file belongs to {doc.get('program')!r}, not {spec.program!r}")
            if doc.get("locked") != self._locked_repr():
                raise HoldoutViolation("locked ranges differ from the registered program spec (immutable)")

    def _locked_repr(self) -> list:
        return [[name, str(a), str(b)] for name, a, b in self.spec.locked]

    def check_range(self, start, end, *, layer: str) -> None:
        for name, a, b in self.spec.locked:
            if intersects(start, end, (a, b)):
                raise HoldoutViolation(f"{self.spec.program} {layer}: {start}..{end} intersects LOCKED {name} {a}..{b}")

    def check_frame(self, df, *, layer: str = "LOAD", ts_col: str = "timestamp") -> None:
        if df is None or len(df) == 0:
            return
        import pandas as pd
        t = pd.to_datetime(df[ts_col], utc=True)
        self.check_range(t.min().date(), t.max().date(), layer=layer)
        # also refuse any interior row inside a locked range (a frame may straddle a locked gap)
        days = pd.Series(t.dt.date.unique())
        for name, a, b in self.spec.locked:
            if ((days >= a) & (days <= b)).any():
                raise HoldoutViolation(f"{self.spec.program} {layer}: frame contains rows inside LOCKED {name}")

    def record(self, event: dict) -> None:
        assert_research_path(self.path)
        doc = json.loads(self.path.read_text()) if self.path.exists() else {
            "program": self.spec.program, "locked": self._locked_repr(), "audit": []}
        doc["audit"].append({"at_utc": datetime.now(timezone.utc).isoformat(), **event})
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(doc, indent=1))


# ------------------------------------------------------------------------------------------- registered programs
EVENT_RESPONSE_MAP_V1 = ProgramSpec(
    program="EVENT_RESPONSE_MAP_V1",
    results_dir="results/event_response_map_v1",
    locked=(("YEAR_2024_EXCLUDED", date(2024, 1, 1), date(2024, 12, 31)),
            ("FUTURE_CONFIRMATION_2025_ONWARD", date(2025, 1, 2), OPEN_END)))
