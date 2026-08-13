"""
tests/test_dispatch_store.py
---------------------------------
Tests talonx_dispatch.store.AuditStore -- the SQLite-backed alert audit
trail. Uses real sqlite3 (stdlib, no mocking needed), same approach as
tests/test_ledger.py and tests/test_core_store.py for this project's
other local SQLite stores.
"""
from __future__ import annotations

import sqlite3
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


def test_record_alert_leaves_suppress_reason_null_until_a_push_decision_is_made(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_alert(_alert())
        row = store.get_by_id(alert_id)
        assert row["suppress_reason"] is None


def test_mark_suppressed_records_the_reason(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_alert(_alert())
        store.mark_suppressed(alert_id, "ACTION_MUTED")

        row = store.get_by_id(alert_id)
        assert row["suppress_reason"] == "ACTION_MUTED"
        assert row["telegram_sent"] is False


def test_mark_telegram_sent_sets_suppress_reason_to_the_literal_none_value(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_alert(_alert())
        store.mark_telegram_sent(alert_id)

        row = store.get_by_id(alert_id)
        assert row["suppress_reason"] == "NONE"


def test_mark_telegram_failed_sets_suppress_reason_to_the_literal_none_value(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_alert(_alert())
        store.mark_telegram_failed(alert_id, "bad token")

        row = store.get_by_id(alert_id)
        assert row["suppress_reason"] == "NONE"


def test_migrates_an_alerts_table_from_before_the_suppress_reason_column(tmp_path):
    """Simulates a real pre-existing dispatch_audit.db from before
    suppress_reason was added to `alerts` -- same idempotent-migration
    guard as the long_term_alerts/summary test below. A pre-existing row
    must survive with suppress_reason=None, and the store stays usable."""
    db_path = tmp_path / "legacy_audit.db"

    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        "CREATE TABLE alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, action TEXT NOT NULL, "
        "severity TEXT NOT NULL, rationale TEXT NOT NULL, quant_direction TEXT NOT NULL, "
        "research_verdict TEXT NOT NULL, research_confidence REAL NOT NULL, signal_type TEXT NOT NULL, "
        "price REAL NOT NULL, research_summary TEXT NOT NULL, key_findings_json TEXT NOT NULL, "
        "risk_factors_json TEXT NOT NULL, model_used TEXT NOT NULL, correlated_at TEXT NOT NULL, "
        "received_at TEXT NOT NULL, telegram_sent INTEGER NOT NULL DEFAULT 0, "
        "telegram_sent_at TEXT, telegram_error TEXT)"
    )
    legacy_conn.execute(
        "INSERT INTO alerts (ticker, action, severity, rationale, quant_direction, research_verdict, "
        "research_confidence, signal_type, price, research_summary, key_findings_json, risk_factors_json, "
        "model_used, correlated_at, received_at) VALUES ('MSFT', 'confirmed_bullish', 'warning', "
        "'pre-migration rationale', 'bullish', 'bullish', 0.8, 'macd_bullish_cross', 503.81, "
        "'summary', '[]', '[]', 'gemini-flash-latest', '2026-08-11T18:51:43+00:00', "
        "'2026-08-11T18:51:44+00:00')"
    )
    legacy_conn.commit()
    legacy_conn.close()

    with AuditStore(db_path) as store:
        rows = store.recent()
        assert len(rows) == 1
        assert rows[0]["suppress_reason"] is None

        store.mark_suppressed(rows[0]["id"], "PUSH_COOLDOWN_ACTIVE")
        assert store.get_by_id(rows[0]["id"])["suppress_reason"] == "PUSH_COOLDOWN_ACTIVE"


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
    is_earnings_related: bool = False, previous_fair_value: float | None = None,
    previous_margin_of_safety_pct: float | None = None, guidance_revision_notes: str | None = None,
) -> LongTermActionableAlert:
    return LongTermActionableAlert(
        ticker=ticker, action=action, severity=AlertSeverity.CRITICAL,
        rationale="FY2025 fundamentals clear thresholds.",
        summary="Strong recurring revenue and durable moat support the thesis.",
        quality_score=8, moat_rating=MoatRating.WIDE, market_price=75.0,
        intrinsic_fair_value=100.0, margin_of_safety_pct=0.25,
        capital_allocation_assessment="Disciplined buybacks.",
        key_findings=["Strong recurring revenue"], risk_factors=["Regulatory scrutiny"],
        model_used="gemini-flash-latest", correlated_at=correlated_at, published_at=correlated_at,
        is_earnings_related=is_earnings_related, previous_fair_value=previous_fair_value,
        previous_margin_of_safety_pct=previous_margin_of_safety_pct,
        guidance_revision_notes=guidance_revision_notes,
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


def test_record_long_term_alert_persists_earnings_radar_fields(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_long_term_alert(
            _long_term_alert(
                is_earnings_related=True, previous_fair_value=210.0,
                previous_margin_of_safety_pct=0.1667, guidance_revision_notes="Guidance raised.",
            )
        )
        row = store.get_long_term_by_id(alert_id)

        assert row["is_earnings_related"] is True
        assert row["previous_fair_value"] == 210.0
        assert row["previous_margin_of_safety_pct"] == 0.1667
        assert row["guidance_revision_notes"] == "Guidance raised."


def test_record_long_term_alert_earnings_radar_fields_default_correctly(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_long_term_alert(_long_term_alert())  # routine, non-earnings alert
        row = store.get_long_term_by_id(alert_id)

        assert row["is_earnings_related"] is False
        assert row["previous_fair_value"] is None
        assert row["previous_margin_of_safety_pct"] is None
        assert row["guidance_revision_notes"] is None


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


def test_mark_long_term_suppressed_records_the_reason(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_long_term_alert(_long_term_alert())
        store.mark_long_term_suppressed(alert_id, "ACTION_MUTED")

        row = store.get_long_term_by_id(alert_id)
        assert row["suppress_reason"] == "ACTION_MUTED"
        assert row["telegram_sent"] is False


def test_mark_long_term_telegram_sent_sets_suppress_reason_to_the_literal_none_value(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        alert_id = store.record_long_term_alert(_long_term_alert())
        store.mark_long_term_telegram_sent(alert_id)

        row = store.get_long_term_by_id(alert_id)
        assert row["suppress_reason"] == "NONE"


def test_migrates_a_long_term_alerts_table_from_before_the_summary_column(tmp_path):
    """Simulates a real pre-existing dispatch_audit.db from before `summary`
    was added to long_term_alerts -- AuditStore's first-ever migration.
    A pre-existing row must survive with summary='' (the DEFAULT), and the
    store must stay fully usable (a fresh insert populates a real summary)."""
    db_path = tmp_path / "legacy_audit.db"

    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        "CREATE TABLE long_term_alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, action TEXT NOT NULL, "
        "severity TEXT NOT NULL, rationale TEXT NOT NULL, quality_score INTEGER NOT NULL, "
        "moat_rating TEXT NOT NULL, market_price REAL NOT NULL, intrinsic_fair_value REAL NOT NULL, "
        "margin_of_safety_pct REAL NOT NULL, capital_allocation_assessment TEXT NOT NULL, "
        "key_findings_json TEXT NOT NULL, risk_factors_json TEXT NOT NULL, model_used TEXT NOT NULL, "
        "correlated_at TEXT NOT NULL, received_at TEXT NOT NULL, "
        "telegram_sent INTEGER NOT NULL DEFAULT 0, telegram_sent_at TEXT, telegram_error TEXT)"
    )
    legacy_conn.execute(
        "INSERT INTO long_term_alerts (ticker, action, severity, rationale, quality_score, moat_rating, "
        "market_price, intrinsic_fair_value, margin_of_safety_pct, capital_allocation_assessment, "
        "key_findings_json, risk_factors_json, model_used, correlated_at, received_at) "
        "VALUES ('MSFT', 'hold_quality', 'info', 'pre-migration rationale', 8, 'wide', "
        "503.81, 525.0, 0.04, 'Disciplined buybacks.', '[]', '[]', 'gemini-flash-latest', "
        "'2026-08-11T18:51:43+00:00', '2026-08-11T18:51:44+00:00')"
    )
    legacy_conn.commit()
    legacy_conn.close()

    with AuditStore(db_path) as store:
        rows = store.recent_long_term()
        assert len(rows) == 1
        assert rows[0]["summary"] == ""  # DEFAULT '' for a pre-migration row
        assert rows[0]["suppress_reason"] is None  # this migration also predates suppress_reason
        assert rows[0]["is_earnings_related"] is False  # DEFAULT 0 for a pre-migration row
        assert rows[0]["previous_fair_value"] is None
        assert rows[0]["previous_margin_of_safety_pct"] is None
        assert rows[0]["guidance_revision_notes"] is None

        # And the migrated store is fully usable afterward.
        store.record_long_term_alert(_long_term_alert(ticker="AAPL"))
        rows = store.recent_long_term()
        assert {r["summary"] for r in rows} == {"", "Strong recurring revenue and durable moat support the thesis."}


# ==========================================================================
# WAL checkpoint (fixes the dashboard-slowdown-over-a-session issue --
# see run_talonx.periodic_wal_checkpoint_loop's own docstring)
# ==========================================================================

def test_checkpoint_does_not_raise(tmp_path):
    with AuditStore(tmp_path / "audit.db") as store:
        store.record_alert(_alert())
        store.checkpoint()
        assert store.count() == 1  # data survives, store stays usable
