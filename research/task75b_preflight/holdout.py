"""Task75B stateful holdout guard -- enforced at BOTH the download layer and the data-load/evaluation layer.

Reserved (Task75A holdout_lock.json, unchanged):
  VALIDATION   2024-06-01 .. 2024-09-02
  REPLICATION  2024-10-21 .. 2024-12-20

States (durable, results/task75b_preflight/holdout_state.json; transitions only forward, audited):
  PREFLIGHT                 validation LOCKED, replication LOCKED
  TASK75B_READY             validation may be downloaded/read; replication LOCKED
  VALIDATION_RUNNING        validation readable; replication LOCKED
  VALIDATION_PASS           replication becomes ELIGIBLE for a later explicit unlock (still LOCKED)
  REPLICATION_UNLOCKED      replication readable (only reachable from VALIDATION_PASS)
  VALIDATION_FAIL           replication PERMANENTLY locked for V1
  VALIDATION_INCONCLUSIVE   replication PERMANENTLY locked for V1
There is no generic READY flag that unlocks both windows.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "results" / "task75b_preflight" / "holdout_state.json"
VALIDATION = (date(2024, 6, 1), date(2024, 9, 2))
REPLICATION = (date(2024, 10, 21), date(2024, 12, 20))
STATES = ("PREFLIGHT", "TASK75B_READY", "VALIDATION_RUNNING", "VALIDATION_PASS", "VALIDATION_FAIL",
          "VALIDATION_INCONCLUSIVE", "REPLICATION_UNLOCKED")
TRANSITIONS = {"PREFLIGHT": {"TASK75B_READY"}, "TASK75B_READY": {"VALIDATION_RUNNING"},
               "VALIDATION_RUNNING": {"VALIDATION_PASS", "VALIDATION_FAIL", "VALIDATION_INCONCLUSIVE"},
               "VALIDATION_PASS": {"REPLICATION_UNLOCKED"}, "VALIDATION_FAIL": set(),
               "VALIDATION_INCONCLUSIVE": set(), "REPLICATION_UNLOCKED": set()}
VALIDATION_OPEN = {"TASK75B_READY", "VALIDATION_RUNNING", "VALIDATION_PASS", "VALIDATION_FAIL",
                   "VALIDATION_INCONCLUSIVE", "REPLICATION_UNLOCKED"}
REPLICATION_OPEN = {"REPLICATION_UNLOCKED"}
# the live application worktree -- research code must never write under it
LIVE_ROOTS = (Path("C:/workspace/TalonX").resolve(),)


class HoldoutViolation(RuntimeError):
    pass


def _d(x) -> date:
    return x if isinstance(x, date) and not isinstance(x, datetime) else date.fromisoformat(str(x)[:10])


def intersects(start, end, window: tuple[date, date]) -> bool:
    """Inclusive interval intersection."""
    s, e = _d(start), _d(end)
    if e < s:
        s, e = e, s
    return s <= window[1] and e >= window[0]


@dataclass
class HoldoutGuard:
    state: str = "PREFLIGHT"
    path: Path = STATE_PATH

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "HoldoutGuard":
        if path.exists():
            st = json.loads(path.read_text())["state"]
            if st not in STATES:
                raise HoldoutViolation(f"unknown holdout state {st!r} (fail closed)")
            return cls(st, path)
        return cls("PREFLIGHT", path)

    def check_range(self, start, end, *, layer: str) -> None:
        """Raise unless [start, end] is allowed in the current state. layer = DOWNLOAD | LOAD (both enforced)."""
        if intersects(start, end, VALIDATION) and self.state not in VALIDATION_OPEN:
            raise HoldoutViolation(f"{layer}: {start}..{end} intersects VALIDATION {VALIDATION} in state {self.state}")
        if intersects(start, end, REPLICATION) and self.state not in REPLICATION_OPEN:
            raise HoldoutViolation(f"{layer}: {start}..{end} intersects REPLICATION {REPLICATION} in state {self.state}")

    def check_frame(self, df, *, layer: str = "LOAD", ts_col: str = "timestamp") -> None:
        """Evaluation-layer guard: refuse a loaded frame containing ANY protected-window timestamp."""
        if df is None or len(df) == 0:
            return
        import pandas as pd
        t = pd.to_datetime(df[ts_col], utc=True)
        self.check_range(t.min().date(), t.max().date(), layer=layer)

    def transition(self, new: str, *, authorized_by: str, reason: str) -> None:
        if new not in TRANSITIONS[self.state]:
            raise HoldoutViolation(f"illegal transition {self.state} -> {new}")
        prev, self.state = self.state, new
        self._write(event={"transition": f"{prev}->{new}", "authorized_by": authorized_by, "reason": reason})

    def record(self, event: dict) -> None:
        """Append-only audit entry (never rewrites earlier entries)."""
        self._write(event=event)

    def _write(self, event: dict) -> None:
        assert_research_path(self.path)
        doc = json.loads(self.path.read_text()) if self.path.exists() else {"audit": []}
        doc["state"] = self.state
        doc["validation"] = [str(x) for x in VALIDATION]
        doc["replication"] = [str(x) for x in REPLICATION]
        doc["audit"].append({"at_utc": datetime.now(timezone.utc).isoformat(), **event})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(doc, indent=1))

    def validation_locked(self) -> bool:
        return self.state not in VALIDATION_OPEN

    def replication_locked(self) -> bool:
        return self.state not in REPLICATION_OPEN


def assert_research_path(p: Path) -> None:
    """Preflight code may only write inside this research worktree -- never under the live application worktree."""
    rp = Path(p).resolve()
    for live in LIVE_ROOTS:
        if rp == live or live in rp.parents:
            raise HoldoutViolation(f"refusing to write under the live application worktree: {rp}")
