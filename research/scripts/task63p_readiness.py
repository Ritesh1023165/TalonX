"""Task 63P timestamp-only, fail-closed ORPB session readiness semantics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd


ET = "America/New_York"
REQUIRED_OPENING_BUCKETS = (
    "09:30", "09:35", "09:40", "09:45", "09:50", "09:55",
)
FROZEN_DATA_NOT_READY = frozenset({
    ("O1", "BKNG", "2025-02-10"),
    ("O1", "BKNG", "2025-02-11"),
    ("O1", "KLAC", "2025-02-07"),
    ("O2", "BKNG", "2025-03-26"),
    ("O3", "BKNG", "2025-04-25"),
    ("O3", "BKNG", "2025-04-30"),
})


@dataclass(frozen=True)
class SessionReadiness:
    window: str
    symbol: str
    session: str
    status: str
    reason: str
    observed_buckets: tuple[str, ...]
    missing_buckets: tuple[str, ...]


def opening_buckets(frame: pd.DataFrame, session: str) -> tuple[str, ...]:
    """Use only timestamps from 09:30 through 09:59 ET for one session."""
    local = frame["timestamp"].dt.tz_convert(ET)
    opening = frame[
        (local.dt.strftime("%Y-%m-%d") == session)
        & (local.dt.hour == 9)
        & (local.dt.minute >= 30)
        & (local.dt.minute < 60)
    ]
    minutes = opening["timestamp"].dt.tz_convert(ET).dt.minute
    return tuple(sorted({f"09:{(int(minute) // 5) * 5:02d}" for minute in minutes}))


def assess_session(
    frame: pd.DataFrame, *, window: str, symbol: str, session: str
) -> SessionReadiness:
    observed = opening_buckets(frame, session)
    missing = tuple(item for item in REQUIRED_OPENING_BUCKETS if item not in observed)
    status = "CLEAN" if not missing else "DATA_NOT_READY"
    reason = "COMPLETE_SIX_OPENING_BUCKETS" if not missing else (
        "MISSING_OPENING_BUCKETS:" + ",".join(missing)
    )
    return SessionReadiness(window, symbol, session, status, reason, observed, missing)


def build_readiness_table(
    frame: pd.DataFrame,
    universe: Iterable[str],
    windows: Iterable[dict],
) -> pd.DataFrame:
    local = frame["timestamp"].dt.tz_convert(ET)
    opening = frame[
        (local.dt.hour == 9) & (local.dt.minute >= 30) & (local.dt.minute < 60)
    ][["symbol", "timestamp"]].copy()
    opening_local = opening["timestamp"].dt.tz_convert(ET)
    opening["session"] = opening_local.dt.strftime("%Y-%m-%d")
    opening["bucket"] = [
        f"09:{(int(minute) // 5) * 5:02d}" for minute in opening_local.dt.minute
    ]
    observed_by_pair = {
        (str(symbol), str(session)): tuple(sorted(set(group.bucket)))
        for (symbol, session), group in opening.groupby(["symbol", "session"], sort=False)
    }
    rows = []
    for window in windows:
        name = str(window["name"])
        for symbol in universe:
            for session in window["evaluation_sessions"]:
                observed = observed_by_pair.get((str(symbol), str(session)), ())
                missing = tuple(
                    item for item in REQUIRED_OPENING_BUCKETS if item not in observed
                )
                status = "CLEAN" if not missing else "DATA_NOT_READY"
                rows.append({
                    "window": name,
                    "symbol": str(symbol),
                    "session": str(session),
                    "status": status,
                    "reason": "COMPLETE_SIX_OPENING_BUCKETS" if not missing else (
                        "MISSING_OPENING_BUCKETS:" + ",".join(missing)
                    ),
                    "observed_buckets": "|".join(observed),
                    "missing_buckets": "|".join(missing),
                })
    return pd.DataFrame(rows).sort_values(
        ["window", "session", "symbol"], kind="mergesort"
    ).reset_index(drop=True)


def clean_evaluation_rows(frame: pd.DataFrame, readiness: pd.DataFrame) -> pd.DataFrame:
    """Return an input-row subset; never synthesize, fill, or alter a market-data row."""
    allowed = readiness[readiness.status == "CLEAN"][["symbol", "session"]]
    allowed_pairs = set(map(tuple, allowed.itertuples(index=False, name=None)))
    local_sessions = frame["timestamp"].dt.tz_convert(ET).dt.strftime("%Y-%m-%d")
    keep = [
        (str(symbol), str(session)) in allowed_pairs
        for symbol, session in zip(frame.symbol, local_sessions)
    ]
    return frame.loc[keep].copy().reset_index(drop=True)


def data_not_ready_set(readiness: pd.DataFrame) -> frozenset[tuple[str, str, str]]:
    blocked = readiness[readiness.status == "DATA_NOT_READY"]
    return frozenset(
        map(tuple, blocked[["window", "symbol", "session"]].itertuples(index=False, name=None))
    )
