"""
tests/test_dispatch_store.py
---------------------------------
Tests talonx_dispatch.store.AuditStore -- the SQLite-backed alert audit
trail. Uses real sqlite3 (stdlib, no mocking needed), same approach as
tests/test_ledger.py and tests/test_core_store.py for this project's
other local SQLite stores.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    LongTermActionableAlert,
    MoatRating,
    ResearchVerdict,
    SignalDirection,
    TriggeringSignalRef,
)
from talonx_dispatch.store import AuditStore

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _alert(
    ticker: str = "AAPL",
    action: AlertAction = AlertAction.CONFIRMED_BULLISH,
    correlated_at: datetime = NOW,
) -> ActionableAlert:
    return ActionableAlert(
        ticker=ticker,
        action=action,
        severity=AlertSeverity.WARNING,
        rationale="rationale text",
        quant_direction=SignalDirection.BULLISH,
        research_verdict=ResearchVerdict.BULLISH,
        research_confidence=0.75,
        triggering_signal=TriggeringSignalRef(
            ticker=ticker,
            signal_type="rsi_oversold_volume_surge",
            direction=SignalDirection.BULLISH,
            message="RSI oversold with volume surge",
            price=200.0,
            bar_timestamp=NOW,
        ),
        research_summary="summary text",
        key_findings=["finding one", "finding two"],
        risk_factors=["risk one"],
        model_used="gemini-flash-latest",
        signal_received_at=NOW,
        report_received_at=NOW,
        correlated_at=correlated_at,
        published_at=NOW,
    )


def test_record_alert_returns_an_id(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_alert(_alert())
        assert alert_id == 1
        assert store.count() == 1


def test_recent_returns_most_recent_first(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert(ticker="AAPL"))
        store.record_alert(_alert(ticker="NVDA"))
        rows = store.recent(limit=10)
        assert [r["ticker"] for r in rows] == ["NVDA", "AAPL"]


def test_recent_round_trips_key_findings_and_risk_factors_as_lists(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert())
        row = store.recent(limit=1)[0]
        assert row["key_findings"] == ["finding one", "finding two"]
        assert row["risk_factors"] == ["risk one"]


def test_mark_telegram_sent_updates_flag(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_alert(_alert())
        store.mark_telegram_sent(alert_id)
        row = store.recent(limit=1)[0]
        assert row["telegram_sent"] is True
        assert row["telegram_sent_at"] is not None


def test_mark_telegram_failed_records_error_without_setting_sent(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_alert(_alert())
        store.mark_telegram_failed(alert_id, "Telegram send failed: bad token")
        row = store.recent(limit=1)[0]
        assert row["telegram_sent"] is False
        assert "bad token" in row["telegram_error"]


def test_watchlist_summary_groups_by_ticker(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert(ticker="AAPL"))
        store.record_alert(_alert(ticker="AAPL"))
        store.record_alert(_alert(ticker="NVDA"))
        summary = {row["ticker"]: row["alert_count"] for row in store.watchlist_summary()}
        assert summary == {"AAPL": 2, "NVDA": 1}


def test_watchlist_summary_reflects_most_recent_action(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert(ticker="AAPL", action=AlertAction.CONFIRMED_BULLISH))
        store.record_alert(_alert(ticker="AAPL", action=AlertAction.CONTRADICTED))
        summary = store.watchlist_summary()
        assert summary[0]["last_action"] == "contradicted"


def test_concurrent_access_does_not_crash_watchlist_summary(tmp_path):
    """
    Regression test for a real crash: app.py caches ONE AuditStore
    (check_same_thread=False) across Streamlit's per-session reruns, which
    can run concurrently on different threads (multiple tabs, or an
    autorefresh tick overlapping a still-rendering previous run). Without
    the store's internal lock, watchlist_summary()'s two-step query
    (aggregate, then a per-ticker detail lookup) could interleave with a
    concurrent write and hit `latest is None` -- crashing the whole
    dashboard render. This hammers record_alert()/watchlist_summary() from
    several threads at once and asserts nothing raises.
    """
    with AuditStore(tmp_path / "audit.db", check_same_thread=False) as store:
        errors: list[Exception] = []

        def writer(ticker: str) -> None:
            for _ in range(20):
                store.record_alert(_alert(ticker=ticker))

        def reader() -> None:
            for _ in range(20):
                try:
                    store.watchlist_summary()
                    store.recent(limit=50)
                except Exception as exc:  # noqa: BLE001 -- capture, don't let a thread crash silently
                    errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=("AAPL",)),
            threading.Thread(target=writer, args=("NVDA",)),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert store.count() == 40


def test_get_by_id_returns_the_matching_row(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_alert(_alert(ticker="NVDA"))
        row = store.get_by_id(alert_id)
        assert row is not None
        assert row["id"] == alert_id
        assert row["ticker"] == "NVDA"


def test_get_by_id_returns_none_for_unknown_id(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        assert store.get_by_id(999) is None


def test_purge_older_than_deletes_only_stale_rows(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        old_id = store.record_alert(_alert(ticker="OLD", correlated_at=NOW - timedelta(days=10)))
        recent_id = store.record_alert(_alert(ticker="RECENT", correlated_at=NOW - timedelta(hours=1)))

        cutoff = NOW - timedelta(days=5)
        purged = store.purge_older_than(cutoff)

        assert purged == 1
        assert store.get_by_id(old_id) is None
        assert store.get_by_id(recent_id) is not None
        assert store.count() == 1


def test_purge_older_than_returns_zero_when_nothing_is_stale(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert(correlated_at=NOW))
        purged = store.purge_older_than(NOW - timedelta(days=5))
        assert purged == 0
        assert store.count() == 1


def test_alerts_between_filters_to_the_window(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert(ticker="BEFORE", correlated_at=NOW - timedelta(days=1)))
        in_window_id = store.record_alert(_alert(ticker="IN", correlated_at=NOW))
        store.record_alert(_alert(ticker="AFTER", correlated_at=NOW + timedelta(days=1)))

        rows = store.alerts_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))

        assert [r["id"] for r in rows] == [in_window_id]
        assert rows[0]["ticker"] == "IN"


def test_alerts_between_end_is_exclusive(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert(correlated_at=NOW))
        rows = store.alerts_between(NOW - timedelta(hours=1), NOW)
        assert rows == []


def test_alerts_between_returns_empty_list_when_nothing_matches(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        assert store.alerts_between(NOW, NOW + timedelta(hours=1)) == []


def test_state_persists_across_reopen(tmp_path):
    path = tmp_path / "audit.db"
    with AuditStore(path) as store:
        store.record_alert(_alert())

    # Reopen as a fresh connection (simulating consumer.py and app.py
    # running as separate processes against the same file) -- must survive.
    with AuditStore(path) as store2:
        assert store2.count() == 1


# ==========================================================================
# Phase 2 LONG_TERM path
# ==========================================================================

def _long_term_alert(
    ticker: str = "AAPL", action: AlertAction = AlertAction.HIGH_CONVICTION_BUY, correlated_at: datetime = NOW,
) -> LongTermActionableAlert:
    return LongTermActionableAlert(
        ticker=ticker, action=action, severity=AlertSeverity.CRITICAL,
        rationale="FY2025 fundamentals clear thresholds.",
        quality_score=8, moat_rating=MoatRating.WIDE, market_price=75.0,
        intrinsic_fair_value=100.0, margin_of_safety_pct=0.25,
        capital_allocation_assessment="Disciplined buybacks.",
        key_findings=["Strong recurring revenue"], risk_factors=["Regulatory scrutiny"],
        model_used="gemini-flash-latest", correlated_at=correlated_at, published_at=correlated_at,
    )


def test_record_long_term_alert_returns_an_id(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_long_term_alert(_long_term_alert())
        assert alert_id == 1
        assert store.count_long_term() == 1


def test_long_term_and_intraday_alerts_are_fully_independent(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert())
        store.record_long_term_alert(_long_term_alert())

        assert store.count() == 1
        assert store.count_long_term() == 1


def test_get_long_term_by_id_returns_the_stored_row(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_long_term_alert(_long_term_alert())
        row = store.get_long_term_by_id(alert_id)

        assert row["ticker"] == "AAPL"
        assert row["action"] == "high_conviction_buy"
        assert row["moat_rating"] == "wide"
        assert row["quality_score"] == 8
        assert row["key_findings"] == ["Strong recurring revenue"]
        assert row["risk_factors"] == ["Regulatory scrutiny"]
        assert row["telegram_sent"] is False


def test_get_long_term_by_id_returns_none_for_unknown_id(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        assert store.get_long_term_by_id(999) is None


def test_mark_long_term_telegram_sent(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_long_term_alert(_long_term_alert())
        store.mark_long_term_telegram_sent(alert_id)

        row = store.get_long_term_by_id(alert_id)
        assert row["telegram_sent"] is True
        assert row["telegram_sent_at"] is not None


def test_mark_long_term_telegram_failed(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_long_term_alert(_long_term_alert())
        store.mark_long_term_telegram_failed(alert_id, "bad token")

        row = store.get_long_term_by_id(alert_id)
        assert row["telegram_sent"] is False
        assert "bad token" in row["telegram_error"]


def test_long_term_alerts_between_filters_to_the_window(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_long_term_alert(_long_term_alert(ticker="OLD", correlated_at=NOW - timedelta(days=10)))
        store.record_long_term_alert(_long_term_alert(ticker="IN", correlated_at=NOW))

        rows = store.long_term_alerts_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        assert [r["ticker"] for r in rows] == ["IN"]


def test_purge_long_term_older_than_deletes_stale_rows(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_long_term_alert(_long_term_alert(correlated_at=NOW - timedelta(days=10)))
        store.record_long_term_alert(_long_term_alert(correlated_at=NOW))

        purged = store.purge_long_term_older_than(NOW - timedelta(days=1))

        assert purged == 1
        assert store.count_long_term() == 1


def test_recent_long_term_orders_newest_first(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_long_term_alert(_long_term_alert(ticker="FIRST", correlated_at=NOW - timedelta(hours=1)))
        store.record_long_term_alert(_long_term_alert(ticker="SECOND", correlated_at=NOW))

        rows = store.recent_long_term()
        assert [r["ticker"] for r in rows] == ["SECOND", "FIRST"]


def test_long_term_state_persists_across_reopen(tmp_path):
    path = tmp_path / "audit.db"
    with AuditStore(path) as store:
        store.record_long_term_alert(_long_term_alert())

    with AuditStore(path) as store2:
        assert store2.count_long_term() == 1
