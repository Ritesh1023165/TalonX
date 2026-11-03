"""The four data gates. All must pass before any outcome is computed; otherwise the study stops: DATA_NOT_READY."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config as C
from .splits import Split, check_split_adjustment


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    value: float | None
    threshold: float | None
    detail: str = ""


def gate1_split_adjustment(adj_close: pd.DataFrame, splits: list[Split]) -> GateResult:
    chk = check_split_adjustment(adj_close, splits)
    detail = f"{chk.passed}/{chk.checked} splits adjusted"
    if chk.failures:
        detail += "; first failures: " + ", ".join(f"{s}@{d.date()}:{r}" for s, d, r, _ in chk.failures[:5])
    rate = chk.passed / chk.checked if chk.checked else 0.0
    # No known splits at all means the check proved nothing: fail rather than pass vacuously.
    return GateResult("G_DATA_1_split_adjustment", chk.ok and chk.checked > 0, rate, 1.0, detail)


def gate2_label_coverage(universe: pd.DataFrame, available: dict[str, pd.DataFrame]) -> GateResult:
    """universe: bool DataFrame (session x symbol). available: horizon -> bool mask from ``labels.label_available``.

    Worst horizon decides. No return value is read.
    """
    worst, worst_h = 1.0, ""
    for h, av in available.items():
        u = universe.reindex(index=av.index, columns=av.columns, fill_value=False)
        total = int(u.to_numpy().sum())
        if total == 0:
            return GateResult("G_DATA_2_label_coverage", False, 0.0, C.GATE_LABEL_COVERAGE, f"{h}: empty universe")
        cov = float((av & u).to_numpy().sum()) / total
        if cov < worst:
            worst, worst_h = cov, h
    return GateResult("G_DATA_2_label_coverage", worst >= C.GATE_LABEL_COVERAGE, worst, C.GATE_LABEL_COVERAGE,
                      f"worst horizon {worst_h or 'n/a'}")


def gate3_fundamental_coverage(universe: pd.DataFrame, has_fundamental: pd.DataFrame) -> GateResult:
    """has_fundamental: bool DataFrame (rank_date x symbol), True if at least one fundamental value is usable."""
    u = universe
    h = has_fundamental.reindex(index=u.index, columns=u.columns, fill_value=False)
    total = int(u.to_numpy().sum())
    cov = float((h & u).to_numpy().sum()) / total if total else 0.0
    return GateResult("G_DATA_3_fundamental_coverage", cov >= C.GATE_FUNDAMENTAL_COVERAGE, cov,
                      C.GATE_FUNDAMENTAL_COVERAGE, f"{total} universe-days")


def gate4_no_lookahead(records: pd.DataFrame) -> GateResult:
    """records: columns ``rank_date`` (date-like) and ``available_at`` (tz-aware timestamp the value became public).

    Every value must be available before 16:00 ET on its rank date.
    """
    if records.empty:
        return GateResult("G_DATA_4_no_lookahead", False, None, 0.0, "no records to test")
    rd = pd.to_datetime(records["rank_date"]).dt.tz_localize("America/New_York") + pd.Timedelta(hours=16)
    av = pd.to_datetime(records["available_at"])
    if av.dt.tz is None:
        return GateResult("G_DATA_4_no_lookahead", False, None, 0.0, "available_at must be timezone-aware")
    late = int((av > rd).sum())
    return GateResult("G_DATA_4_no_lookahead", late == 0, float(late), 0.0, f"{late} of {len(records)} after cutoff")


def all_passed(results: list[GateResult]) -> bool:
    return len(results) == 4 and all(r.passed for r in results)
