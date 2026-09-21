from __future__ import annotations

import pandas as pd

from research.scripts.task63p_readiness import (
    REQUIRED_OPENING_BUCKETS,
    assess_session,
    clean_evaluation_rows,
)


def frame(minutes: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.to_datetime(minutes, utc=True),
        "symbol": "TEST",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 1.0,
    })


def test_six_opening_components_are_clean_and_one_missing_fails_closed() -> None:
    complete = frame([f"2025-02-10 14:{minute}:00Z" for minute in (30, 35, 40, 45, 50, 55)])
    clean = assess_session(complete, window="O1", symbol="TEST", session="2025-02-10")
    assert clean.status == "CLEAN"
    assert clean.observed_buckets == REQUIRED_OPENING_BUCKETS
    incomplete = complete.drop(index=2).reset_index(drop=True)
    blocked = assess_session(incomplete, window="O1", symbol="TEST", session="2025-02-10")
    assert blocked.status == "DATA_NOT_READY"
    assert blocked.missing_buckets == ("09:40",)


def test_readiness_is_invariant_to_every_post_opening_bar_and_value() -> None:
    opening = frame([f"2025-02-10 14:{minute}:00Z" for minute in (30, 35, 40, 45, 50, 55)])
    baseline = assess_session(opening, window="O1", symbol="TEST", session="2025-02-10")
    future = frame(["2025-02-10 15:00:00Z", "2025-02-10 20:59:00Z"])
    future.loc[:, ["open", "high", "low", "close", "volume"]] = [1, 9999, 0.01, 5000, 1e12]
    mutated = assess_session(
        pd.concat([opening, future], ignore_index=True),
        window="O1", symbol="TEST", session="2025-02-10",
    )
    assert mutated == baseline


def test_filter_removes_entire_not_ready_symbol_session_without_synthesis() -> None:
    source = frame([
        "2025-02-10 14:30:00Z", "2025-02-10 15:00:00Z", "2025-02-11 14:30:00Z"
    ])
    readiness = pd.DataFrame([
        {"symbol": "TEST", "session": "2025-02-10", "status": "DATA_NOT_READY"},
        {"symbol": "TEST", "session": "2025-02-11", "status": "CLEAN"},
    ])
    filtered = clean_evaluation_rows(source, readiness)
    assert len(filtered) == 1
    assert filtered.iloc[0].timestamp == source.iloc[2].timestamp
    assert filtered.iloc[0].to_dict() == source.iloc[2].to_dict()


def test_readiness_does_not_depend_on_prices_or_volume() -> None:
    source = frame([f"2025-02-10 14:{minute}:00Z" for minute in (30, 35, 40, 45, 50, 55)])
    before = assess_session(source, window="O1", symbol="TEST", session="2025-02-10")
    source.loc[:, ["open", "high", "low", "close", "volume"]] = [7, 8, 6, 7.5, 0]
    after = assess_session(source, window="O1", symbol="TEST", session="2025-02-10")
    assert after == before
