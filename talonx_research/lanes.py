"""
Non-blocking lane model (Task 115.G / R4).

  ACTIVE   -- the live-paper strategy.  May emit real user-facing OFFICIAL
              alerts.  Paper only.  Owns the authoritative Active V2 ledger
              (C:\\workspace\\TalonX\\v2_lane.db).
  SHADOW   -- a live internal shadow.  Same incoming data where useful, its
              OWN state/ledger, NO official external alerts, NO writes to
              the active ledger.
  RESEARCH -- historical / offline.  Its own outputs, NO external sends, NO
              active-state writes.

Isolation is architectural, not OS resource management:

  * ACTIVE runs in the primary worktree from the frozen release SHA;
    SHADOW/RESEARCH run from a separate worktree/branch and separate
    ledgers -- a crash or CPU spike in one process cannot touch another's
    SQLite file or the supervisor that owns ACTIVE.
  * The Task 114 autonomous operator classifies a SHADOW/RESEARCH failure
    as DEGRADED, never SESSION_BLOCKING for ACTIVE
    (talonx_ops/prospective/events.py, talonx_ops/supervisor.py
    Classification.OPTIONAL).
  * RESEARCH replay uses ``replay_engine.assert_research_ledger_path`` --
    it physically cannot open the ACTIVE ledger.
  * RESEARCH / SHADOW external transport is DRY-RUN ONLY.

This module provides small assertions the operator/tests can call to
prove a lane is behaving.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_ACTIVE_LEDGER = Path("C:/workspace/TalonX/v2_lane.db")


def assert_lane_isolation(*, lane: str, ledger_path: str | Path,
                          external_transport: str) -> dict[str, Any]:
    lane = lane.upper()
    problems: list[str] = []
    p = Path(ledger_path).resolve()
    if lane in ("SHADOW", "RESEARCH"):
        try:
            same = p == _ACTIVE_LEDGER.resolve()
        except OSError:
            same = str(p).lower() == str(_ACTIVE_LEDGER).lower()
        if same:
            problems.append(f"{lane} lane must not use the ACTIVE ledger {_ACTIVE_LEDGER}")
        if external_transport.upper() not in ("NONE", "DRY_RUN", "DRY-RUN"):
            problems.append(f"{lane} lane external transport must be DRY-RUN, got {external_transport!r}")
    return {"lane": lane, "ledger_path": str(p), "external_transport": external_transport,
            "isolated": not problems, "problems": problems}


LANE_MODEL_DOC = __doc__
