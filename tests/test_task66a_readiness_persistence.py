"""Task 66A Part 1 -- restart-safe SessionReadinessValidator persistence.
Covers: READY/DATA_NOT_READY survive restart, previous-day state rejected,
malformed state fails closed, a corrupt symbol entry cannot become
eligible, no synthetic data, restart-after-10:00 eligibility preserved,
idempotent restore, persistence survives normal shutdown, next-day reset."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from talonx_piv.readiness import (
    ReadinessStateError, ReadinessTelemetry, SessionReadinessValidator,
    load_readiness_state, save_readiness_state,
)

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 8, 24)
OTHER_SESSION = date(2026, 8, 25)


def full_validator(symbols=("AAPL",), missing=frozenset()):
    v = SessionReadinessValidator()
    start = datetime(2026, 8, 24, 9, 30, tzinfo=ET)
    for symbol in symbols:
        for i in range(30):
            if (symbol, i) not in {(s, m) for s in symbols for m in missing}:
                v.observe(symbol, SESSION, start + timedelta(minutes=i))
    return v


def test_ready_survives_restart(tmp_path):
    path = tmp_path / "state.json"
    v1 = full_validator()
    result = v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    assert result.status == "READY"
    save_readiness_state(path, v1.to_state(SESSION))

    v2 = SessionReadinessValidator()
    outcome = v2.restore_state(load_readiness_state(path), SESSION)
    assert outcome.ok and "AAPL" in outcome.restored_symbols
    # Later observation/evaluation must not change the restored decision.
    v2.observe("AAPL", SESSION, datetime(2026, 8, 24, 9, 35, tzinfo=ET))
    assert v2.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 11, 0, tzinfo=ET)).status == "READY"
    assert v2.strategy_eligible("AAPL", SESSION)


def test_data_not_ready_survives_restart(tmp_path):
    path = tmp_path / "state.json"
    v1 = full_validator(missing={7})
    result = v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    assert result.status == "DATA_NOT_READY"
    save_readiness_state(path, v1.to_state(SESSION))

    v2 = SessionReadinessValidator()
    v2.restore_state(load_readiness_state(path), SESSION)
    assert v2.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 11, 0, tzinfo=ET)).status == "DATA_NOT_READY"
    assert not v2.strategy_eligible("AAPL", SESSION)


def test_restart_after_10_retains_previously_established_eligibility(tmp_path):
    """The exact scenario found live 2026-08-24: process restarts well
    after 10:00 ET. Without restoration every symbol would read
    DATA_NOT_READY for lack of observations; with it, the true decision
    persists."""
    path = tmp_path / "state.json"
    v1 = full_validator()
    v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    save_readiness_state(path, v1.to_state(SESSION))

    v2 = SessionReadinessValidator()  # fresh instance, as a real process restart produces
    v2.restore_state(load_readiness_state(path), SESSION)
    late = datetime(2026, 8, 24, 14, 41, tzinfo=ET)  # long after 10:00, matching today's incident
    assert v2.evaluate("AAPL", SESSION, late).status == "READY"


def test_previous_day_state_is_rejected(tmp_path):
    path = tmp_path / "state.json"
    v1 = full_validator()
    v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    save_readiness_state(path, v1.to_state(SESSION))  # persisted for SESSION (Aug 24)

    v2 = SessionReadinessValidator()
    outcome = v2.restore_state(load_readiness_state(path), OTHER_SESSION)  # asking to restore for Aug 25
    assert outcome.stale and not outcome.restored_symbols
    # Nothing restored -- symbol must evaluate fresh (and fail closed, no observations yet).
    result = v2.evaluate("AAPL", OTHER_SESSION, datetime(2026, 8, 25, 10, 0, tzinfo=ET))
    assert result.status == "DATA_NOT_READY"


@pytest.mark.parametrize("bad_state", [
    {"schema_version": 999, "session_date": "2026-08-24", "finalized": {}, "observed": {}},
    {"schema_version": 1, "session_date": "not-a-date", "finalized": {}, "observed": {}},
    {"schema_version": 1, "session_date": "2026-08-24", "finalized": "not-a-dict", "observed": {}},
    "not-even-a-dict",
    [],
])
def test_malformed_state_fails_closed(tmp_path, bad_state):
    v = SessionReadinessValidator()
    outcome = v.restore_state(bad_state, SESSION)
    assert outcome.invalid and not outcome.restored_symbols
    assert v.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET)).status == "DATA_NOT_READY"


def test_missing_state_file_reports_missing(tmp_path):
    assert load_readiness_state(tmp_path / "nope.json") is None
    v = SessionReadinessValidator()
    outcome = v.restore_state(None, SESSION)
    assert outcome.missing and not outcome.restored_symbols


def test_corrupt_json_raises_readiness_state_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ReadinessStateError):
        load_readiness_state(path)


def test_partial_corrupt_symbol_entry_cannot_make_it_eligible(tmp_path):
    good = ReadinessTelemetry(
        "MSFT", SESSION.isoformat(), "READY", "2026-08-24T14:00:00+00:00", 30, 30, (), (), "COMPLETE_OPENING_DATA",
    )
    state = {
        "schema_version": 1, "session_date": SESSION.isoformat(),
        "finalized": {
            "MSFT": good.to_dict(),
            "AAPL": {"status": "READY", "synthetic_data_used": True, "session": SESSION.isoformat()},  # corrupt: claims synthetic
            "TSLA": {"status": "NOT_A_REAL_STATUS", "session": SESSION.isoformat()},  # corrupt: bad status
        },
        "observed": {},
    }
    v = SessionReadinessValidator()
    outcome = v.restore_state(state, SESSION)
    assert "MSFT" in outcome.restored_symbols
    assert "AAPL" in outcome.invalid_symbols and "TSLA" in outcome.invalid_symbols
    # AAPL/TSLA were never actually restored as READY -- must fail closed on fresh evaluation.
    assert v.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 14, 0, tzinfo=ET)).status == "DATA_NOT_READY"
    assert v.evaluate("TSLA", SESSION, datetime(2026, 8, 24, 14, 0, tzinfo=ET)).status == "DATA_NOT_READY"
    assert v.evaluate("MSFT", SESSION, datetime(2026, 8, 24, 14, 0, tzinfo=ET)).status == "READY"


def test_no_synthetic_data_created_by_persistence_round_trip(tmp_path):
    path = tmp_path / "state.json"
    v1 = full_validator(missing={3, 4, 5})
    result = v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    assert result.observed_minutes == 27 and len(result.missing_minutes) == 3
    save_readiness_state(path, v1.to_state(SESSION))

    v2 = SessionReadinessValidator()
    v2.restore_state(load_readiness_state(path), SESSION)
    restored = v2.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 14, 0, tzinfo=ET))
    assert restored.observed_minutes == 27 and len(restored.missing_minutes) == 3  # unchanged, nothing fabricated
    assert restored.synthetic_data_used is False


def test_idempotent_repeated_restore(tmp_path):
    path = tmp_path / "state.json"
    v1 = full_validator()
    v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    save_readiness_state(path, v1.to_state(SESSION))
    state = load_readiness_state(path)

    v2 = SessionReadinessValidator()
    first = v2.restore_state(state, SESSION)
    second = v2.restore_state(state, SESSION)
    assert first.restored_symbols == second.restored_symbols
    assert v2.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 11, 0, tzinfo=ET)).status == "READY"


def test_persistence_survives_normal_shutdown_round_trip(tmp_path):
    """Save -> a brand new process (new validator instance, no shared
    memory) -> load -> restore, exactly the normal-shutdown/restart path."""
    path = tmp_path / "state.json"
    v1 = full_validator(missing={2})
    v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    save_readiness_state(path, v1.to_state(SESSION))
    assert path.exists()

    v2 = SessionReadinessValidator()
    loaded = load_readiness_state(path)
    outcome = v2.restore_state(loaded, SESSION)
    assert outcome.ok
    assert v2.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 11, 0, tzinfo=ET)).status == "DATA_NOT_READY"


def test_session_reset_next_trading_day_works_correctly(tmp_path):
    path = tmp_path / "state.json"
    v1 = full_validator()
    v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET))
    save_readiness_state(path, v1.to_state(SESSION))

    v2 = SessionReadinessValidator()
    # Next trading day: restore attempted against yesterday's file for
    # TODAY's session -- correctly rejected as stale, then fresh
    # observation for the new day proceeds normally.
    stale_outcome = v2.restore_state(load_readiness_state(path), OTHER_SESSION)
    assert stale_outcome.stale
    start = datetime(2026, 8, 25, 9, 30, tzinfo=ET)
    for i in range(30):
        v2.observe("AAPL", OTHER_SESSION, start + timedelta(minutes=i))
    assert v2.evaluate("AAPL", OTHER_SESSION, datetime(2026, 8, 25, 10, 0, tzinfo=ET)).status == "READY"
    # And yesterday's finalized decision, if re-queried under its own
    # session key, is untouched by any of this.
    assert v2.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 12, 0, tzinfo=ET)).status == "DATA_NOT_READY"


def test_pending_symbol_restores_raw_observations_not_a_final_decision(tmp_path):
    """A crash before 10:00 ET (still PENDING) must restore the partial
    observations so live accumulation continues correctly, not silently
    lose progress and restart cold."""
    path = tmp_path / "state.json"
    v1 = SessionReadinessValidator()
    start = datetime(2026, 8, 24, 9, 30, tzinfo=ET)
    for i in range(20):  # only 20 of 30 minutes observed before the simulated crash
        v1.observe("AAPL", SESSION, start + timedelta(minutes=i))
    pending = v1.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 9, 50, tzinfo=ET))
    assert pending.status == "PENDING"
    save_readiness_state(path, v1.to_state(SESSION))

    v2 = SessionReadinessValidator()
    v2.restore_state(load_readiness_state(path), SESSION)
    for i in range(20, 30):  # the remaining 10 minutes arrive after restart
        v2.observe("AAPL", SESSION, start + timedelta(minutes=i))
    assert v2.evaluate("AAPL", SESSION, datetime(2026, 8, 24, 10, 0, tzinfo=ET)).status == "READY"
