"""Task 99G -- live forward-outcome wiring fix. Focused areas 1-20 per the
task spec: record creation, causal MFE/MAE, pre-alert-bar isolation, +30m/
+60m/EOD/+1D resolution timing (real NYSE session boundaries via
market_sessions), idempotency (duplicate bar, duplicate call), restart
recovery, immutability of resolved horizons, missing-data safety, per-symbol
isolation, multi-symbol correctness, BULLISH/BEARISH semantics, DB
compatibility, and malformed-event resilience. TEST_FIXTURE_ONLY -- NOT
ALPHA EVIDENCE.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from talonx_signals import market_sessions
from talonx_signals.run import _parse_event_ts
from talonx_signals.schemas import (
    AlertDirection, DirectionalAlert, MarketSession, SetupEvidence, TradeGateStatus, make_alert_id,
)
from talonx_signals.telemetry import ForwardOutcomeRecorder, ForwardOutcomeStore

# 2026-08-07 is a real NYSE trading day (Friday); its close is 20:00 UTC
# (16:00 ET) and the next valid session is Monday 2026-08-10, close 20:00 UTC
# -- both verified directly against exchange_calendars (XNYS) in development.
FRI = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)          # 11:00 ET, mid-RTH
FRI_CLOSE = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)    # 16:00 ET
MON_CLOSE = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)   # next session close


@pytest.fixture
def store(tmp_path):
    s = ForwardOutcomeStore(tmp_path / "fo.db")
    yield s
    s.close()


def _alert(symbol="AAPL", direction=AlertDirection.BULLISH, price=100.0, ts=FRI):
    return DirectionalAlert(
        alert_id=make_alert_id(symbol=symbol, direction=direction.value, setup_type="macd_bullish_cross",
                               session="regular", episode_ts=ts),
        symbol=symbol, direction=direction, profile="FROZEN_CONTROL", setup_type="macd_bullish_cross",
        setup_score=2, session=MarketSession.REGULAR, price=price,
        trade_gate_status=TradeGateStatus.WOULD_PASS, evidence=SetupEvidence(),
        bar_timestamp=ts, generated_at=ts,
    )


# ---------------------------------------------------------------------------
# 1. record creation
# ---------------------------------------------------------------------------

def test_1_forward_outcome_record_created(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert())
    row = store._get(obs)
    assert row is not None
    assert row["status"] == "PENDING_30M"
    assert row["reference_price"] == 100.0
    assert row["symbol"] == "AAPL"


# ---------------------------------------------------------------------------
# 2/3. MFE / MAE causal update
# ---------------------------------------------------------------------------

def test_2_mfe_increases_on_favourable_post_alert_bar(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=5), 103.0)
    row = store._get(obs)
    assert row["mfe"] == pytest.approx(3.0)


def test_3_mae_worsens_on_adverse_post_alert_bar(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=5), 97.0)
    row = store._get(obs)
    assert row["mae"] == pytest.approx(-3.0)


# ---------------------------------------------------------------------------
# 4. pre-alert bars ignored
# ---------------------------------------------------------------------------

def test_4_pre_alert_bar_never_contaminates_mfe_mae(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0, ts=FRI))
    # a bar timestamped BEFORE the alert -- must be a complete no-op
    rec.on_market_bar("AAPL", FRI - timedelta(minutes=5), 500.0)
    row = store._get(obs)
    assert row["mfe"] == 0.0 and row["mae"] == 0.0
    assert row["status"] == "PENDING_30M"


# ---------------------------------------------------------------------------
# 5/6. +30m timing
# ---------------------------------------------------------------------------

def test_5_30m_does_not_resolve_before_due_time(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=29, seconds=59), 110.0)
    assert store._get(obs)["r_30m"] is None


def test_6_30m_resolves_on_first_valid_bar_at_or_after_due(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 102.0)
    row = store._get(obs)
    assert row["r_30m"] == pytest.approx(2.0)
    assert row["status"] == "PENDING_60M"


# ---------------------------------------------------------------------------
# 7. +60m
# ---------------------------------------------------------------------------

def test_7_60m_resolves_on_first_valid_bar_at_or_after_due(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=59), 101.0)  # too early
    assert store._get(obs)["r_60m"] is None
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=60), 103.0)
    row = store._get(obs)
    assert row["r_60m"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# 8. EOD resolution (real NYSE session close, not wall clock)
# ---------------------------------------------------------------------------

def test_8_eod_does_not_resolve_before_session_close(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(hours=3), 105.0)  # 14:00 ET, still RTH
    assert store._get(obs)["r_eod"] is None
    assert store._get(obs)["status"] == "PENDING_EOD"


def test_8_eod_resolves_at_or_after_the_real_session_close(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI_CLOSE, 104.0)
    row = store._get(obs)
    assert row["r_eod"] == pytest.approx(4.0)
    assert row["status"] == "PENDING_1D"


# ---------------------------------------------------------------------------
# 9. +1D pending until the next VALID trading session (weekend-aware)
# ---------------------------------------------------------------------------

def test_9_1d_stays_pending_across_the_weekend_gap(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI_CLOSE, 104.0)  # resolves EOD
    # a tick that WOULD exist on the weekend (never really would from a live
    # feed, but proves no false fill even if one arrived) must not resolve +1D
    rec.on_market_bar("AAPL", FRI_CLOSE + timedelta(hours=30), 999.0)  # Saturday
    row = store._get(obs)
    assert row["r_1d"] is None
    assert row["status"] == "PENDING_1D"


def test_9_1d_resolves_at_the_next_valid_session_close(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI_CLOSE, 104.0)
    rec.on_market_bar("AAPL", MON_CLOSE - timedelta(minutes=1), 200.0)  # Monday, still RTH
    assert store._get(obs)["r_1d"] is None
    rec.on_market_bar("AAPL", MON_CLOSE, 99.0)
    row = store._get(obs)
    assert row["r_1d"] == pytest.approx(-1.0)
    assert row["status"] == "COMPLETE"


# ---------------------------------------------------------------------------
# 10/11. idempotency
# ---------------------------------------------------------------------------

def test_10_duplicate_market_bar_is_idempotent(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 105.0)
    row1 = dict(store._get(obs))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 105.0)  # exact duplicate
    row2 = dict(store._get(obs))
    assert row1["r_30m"] == row2["r_30m"] == pytest.approx(5.0)
    assert row1["mfe"] == row2["mfe"]


def test_11_duplicate_recorder_call_is_idempotent_and_does_not_overwrite(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_price(obs, FRI + timedelta(minutes=30), 105.0)
    first = store._get(obs)["r_30m"]
    # a LATER, different price at/after the same due time must never overwrite
    # an already-resolved horizon
    rec.on_price(obs, FRI + timedelta(minutes=45), 999.0)
    assert store._get(obs)["r_30m"] == first


# ---------------------------------------------------------------------------
# 12. restart recovery
# ---------------------------------------------------------------------------

def test_12_restart_resumes_pending_records_correctly(tmp_path):
    path = tmp_path / "fo.db"
    s1 = ForwardOutcomeStore(path)
    rec1 = ForwardOutcomeRecorder(s1)
    obs = rec1.open_from_directional(_alert(price=100.0))
    rec1.on_market_bar("AAPL", FRI + timedelta(minutes=15), 101.0)  # process "stops" at 10:15
    s1.close()

    # "restart": brand-new Store/Recorder objects on the same path
    s2 = ForwardOutcomeStore(path)
    rec2 = ForwardOutcomeRecorder(s2)
    assert s2._get(obs)["r_30m"] is None  # still correctly pending after restart
    rec2.on_market_bar("AAPL", FRI + timedelta(minutes=30), 103.0)  # +30m becomes due
    row = s2._get(obs)
    assert row["r_30m"] == pytest.approx(3.0)
    s2.close()


# ---------------------------------------------------------------------------
# 13. resolved horizons are immutable
# ---------------------------------------------------------------------------

def test_13_resolved_horizons_are_immutable(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 110.0)
    resolved_30m = store._get(obs)["r_30m"]
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=35), 50.0)
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=60), 60.0)
    assert store._get(obs)["r_30m"] == resolved_30m  # untouched by later ticks


# ---------------------------------------------------------------------------
# 14. missing data leaves horizon pending
# ---------------------------------------------------------------------------

def test_14_missing_data_leaves_horizon_pending_not_fabricated(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(price=100.0))
    # only ONE early bar ever arrives; +30m/+60m/eod/+1d must all stay pending
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=5), 101.0)
    row = store._get(obs)
    assert row["r_30m"] is None and row["r_60m"] is None
    assert row["r_eod"] is None and row["r_1d"] is None
    assert row["status"] == "PENDING_30M"


def test_14b_unparseable_timestamp_is_never_used(store):
    """run._parse_event_ts must return None (never fabricate "now") for a
    missing/garbled payload timestamp -- the caller then simply skips that
    bar for telemetry purposes."""
    assert _parse_event_ts(None) is None
    assert _parse_event_ts("") is None
    assert _parse_event_ts("not-a-timestamp") is None
    assert _parse_event_ts("2026-08-07T15:00:00Z") == FRI


# ---------------------------------------------------------------------------
# 15/16. per-symbol isolation + multi-symbol correctness
# ---------------------------------------------------------------------------

def test_15_unrelated_symbol_cannot_corrupt_another_symbols_outcome(store):
    rec = ForwardOutcomeRecorder(store)
    obs_aapl = rec.open_from_directional(_alert(symbol="AAPL", price=100.0))
    # a bar for a totally different, unrelated symbol
    n = rec.on_market_bar("MSFT", FRI + timedelta(minutes=30), 9999.0)
    assert n == 0  # nothing pending for MSFT
    row = store._get(obs_aapl)
    assert row["mfe"] == 0.0 and row["mae"] == 0.0 and row["r_30m"] is None


def test_16_multiple_simultaneous_symbols_resolve_independently(store):
    rec = ForwardOutcomeRecorder(store)
    obs_a = rec.open_from_directional(_alert(symbol="AAPL", price=100.0))
    obs_m = rec.open_from_directional(_alert(symbol="MSFT", price=200.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 110.0)  # +10%
    rec.on_market_bar("MSFT", FRI + timedelta(minutes=30), 190.0)  # -5%
    a = store._get(obs_a); m = store._get(obs_m)
    assert a["r_30m"] == pytest.approx(10.0)
    assert m["r_30m"] == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# 17/18. directional return semantics
# ---------------------------------------------------------------------------

def test_17_bullish_return_calculation(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(direction=AlertDirection.BULLISH, price=100.0))
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 105.0)
    row = store._get(obs)
    assert row["r_30m"] == pytest.approx(5.0)
    assert row["hit_30m"] == 1  # BULLISH + price up = favourable


def test_18_bearish_return_calculation(store):
    rec = ForwardOutcomeRecorder(store)
    obs = rec.open_from_directional(_alert(symbol="TSLA", direction=AlertDirection.BEARISH, price=100.0))
    rec.on_market_bar("TSLA", FRI + timedelta(minutes=30), 95.0)  # price fell 5%
    row = store._get(obs)
    assert row["r_30m"] == pytest.approx(-5.0)
    assert row["hit_30m"] == 1  # BEARISH + price down = favourable (directional accuracy only)
    # never a simulated short P&L field populated
    assert row["gross_pnl"] is None and row["net_pnl"] is None


# ---------------------------------------------------------------------------
# 19. existing database compatibility (no schema migration was needed/added)
# ---------------------------------------------------------------------------

def test_19_new_methods_work_against_the_pre_task99g_schema_unchanged(tmp_path):
    """Task 99G added zero new columns to forward_observations -- prove the
    new pending_for_symbol/summary methods work against a DB created with
    exactly the pre-99G DDL (byte-identical to the current one)."""
    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE forward_observations (
            obs_id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL,
            symbol TEXT NOT NULL, direction TEXT, profile TEXT NOT NULL, setup TEXT,
            setup_score INTEGER, horizon TEXT, catalyst TEXT, trade_gate_status TEXT,
            trade_gate_reject_reason TEXT, admitted_by TEXT, alert_ts TEXT NOT NULL,
            reference_price REAL NOT NULL, r_30m REAL, r_60m REAL, r_eod REAL, r_1d REAL,
            hit_30m INTEGER, hit_60m INTEGER, hit_eod INTEGER, hit_1d INTEGER,
            mfe REAL, mae REAL, entry REAL, stop REAL, target REAL, quantity REAL,
            exit REAL, exit_reason TEXT, gross_pnl REAL, est_costs REAL, net_pnl REAL,
            r_multiple REAL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    con.execute(
        "INSERT INTO forward_observations (obs_id, kind, source_id, symbol, direction, profile, "
        "alert_ts, reference_price, mfe, mae, status, created_at, updated_at) VALUES "
        "('FO-legacy','directional','D-legacy','AAPL','BULLISH','FROZEN_CONTROL',?,100.0,0.0,0.0,"
        "'PENDING_30M',?,?)",
        (FRI.isoformat(), FRI.isoformat(), FRI.isoformat()),
    )
    con.commit()
    con.close()

    store = ForwardOutcomeStore(path)  # opens the pre-existing legacy-shaped DB
    rec = ForwardOutcomeRecorder(store)
    pending = store.pending_for_symbol("AAPL")
    assert len(pending) == 1 and pending[0]["obs_id"] == "FO-legacy"
    rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 103.0)
    row = store._get("FO-legacy")
    assert row["r_30m"] == pytest.approx(3.0)
    summary = store.summary()
    assert summary["total"] == 1 and summary["resolved_30m"] == 1
    store.close()


# ---------------------------------------------------------------------------
# 20. malformed event never kills the recorder loop
# ---------------------------------------------------------------------------

def test_20_malformed_symbol_lookup_never_raises(store, monkeypatch):
    rec = ForwardOutcomeRecorder(store)
    rec.open_from_directional(_alert(price=100.0))

    def boom(symbol):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(store, "pending_for_symbol", boom)
    n = rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 105.0)
    assert n == 0  # degraded gracefully, did not raise


def test_20b_one_bad_observation_does_not_break_the_rest_of_the_batch(store, monkeypatch):
    rec = ForwardOutcomeRecorder(store)
    obs_good = rec.open_from_directional(_alert(symbol="AAPL", price=100.0))
    rec.open_from_directional(_alert(symbol="AAPL", direction=AlertDirection.BEARISH, price=100.0,
                                     ts=FRI + timedelta(seconds=1)))

    real_on_price = rec.on_price
    calls = {"n": 0}

    def flaky(obs_id, ts, price):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom on the first row")
        return real_on_price(obs_id, ts, price)

    monkeypatch.setattr(rec, "on_price", flaky)
    n = rec.on_market_bar("AAPL", FRI + timedelta(minutes=30), 105.0)
    assert n == 2  # both rows attempted despite the first raising


# ---------------------------------------------------------------------------
# market_sessions helper -- direct coverage
# ---------------------------------------------------------------------------

def test_session_close_utc_matches_known_nyse_close():
    assert market_sessions.session_close_utc(FRI.date()) == FRI_CLOSE


def test_session_close_utc_none_on_a_weekend():
    assert market_sessions.session_close_utc(datetime(2026, 8, 8).date()) is None  # Saturday


def test_next_session_close_utc_skips_the_weekend():
    assert market_sessions.next_session_close_utc(FRI.date()) == MON_CLOSE
