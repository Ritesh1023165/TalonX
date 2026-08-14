"""
tests/test_dispatch_app_funnel.py
--------------------------------------
Tests the two testable-without-Streamlit pieces of talonx_dispatch.app's
Daily Funnel & Metrics tab: _fetch_daily_metrics (Redis read + key
parsing) and _funnel_counts (the 5-stage README funnel derived from the
raw per-module counters). The rest of app.py is Streamlit UI code, not
unit tested elsewhere in this project either.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from talonx_dispatch.app import _fetch_daily_metrics, _funnel_counts


def _client(keys: dict[str, str]) -> MagicMock:
    client = MagicMock()
    client.scan_iter.return_value = list(keys.keys())
    client.mget.return_value = list(keys.values())
    return client


def test_fetch_daily_metrics_groups_by_module_and_counter():
    client = _client({
        "metrics:2026-08-13:ingest:bars_read": "120",
        "metrics:2026-08-13:quant:published": "8",
        "metrics:2026-08-13:quant:failed_confluence": "3",
    })

    metrics = _fetch_daily_metrics(client, "2026-08-13")

    assert metrics == {
        "ingest": {"bars_read": 120},
        "quant": {"published": 8, "failed_confluence": 3},
    }


def test_fetch_daily_metrics_returns_empty_dict_when_no_keys():
    client = _client({})

    assert _fetch_daily_metrics(client, "2026-08-13") == {}


def test_fetch_daily_metrics_skips_none_values():
    client = _client({"metrics:2026-08-13:ingest:bars_read": None})

    assert _fetch_daily_metrics(client, "2026-08-13") == {}


def test_fetch_daily_metrics_returns_empty_dict_on_redis_error():
    client = MagicMock()
    client.scan_iter.side_effect = ConnectionError("redis down")

    assert _fetch_daily_metrics(client, "2026-08-13") == {}


def test_funnel_counts_sums_core_actions_into_one_stage():
    metrics = {
        "ingest": {"bars_read": 500},
        "quant": {"evaluated": 40},
        "brain": {"received": 12},
        "core": {"action_bullish": 5, "action_bearish": 3, "action_contradicted": 2},
        "dispatch": {"pushed_telegram": 4},
    }

    rows = _funnel_counts(metrics)

    assert rows == [
        {"Stage": "Bars Ingested", "Count": 500},
        {"Stage": "Quant Triggers", "Count": 40},
        {"Stage": "LLM Evaluated", "Count": 12},
        {"Stage": "Core Alerts", "Count": 10},
        {"Stage": "Telegram Pushes", "Count": 4},
    ]


def test_funnel_counts_defaults_missing_modules_to_zero():
    rows = _funnel_counts({})

    assert all(row["Count"] == 0 for row in rows)
    assert [row["Stage"] for row in rows] == [
        "Bars Ingested", "Quant Triggers", "LLM Evaluated", "Core Alerts", "Telegram Pushes",
    ]
