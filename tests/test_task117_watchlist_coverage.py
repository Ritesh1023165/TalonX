"""Task 117 overnight P5 -- configured watchlist -> honest strategy coverage map.
Read-only; isolated fixture watchlist.db.  No production universe change.
"""
from __future__ import annotations

import sqlite3

from talonx_ops.watchlist_coverage import build_coverage_map, to_markdown


def _wl(tmp_path, rows):
    con = sqlite3.connect(tmp_path / "watchlist.db")
    con.execute("CREATE TABLE tickers (symbol TEXT, name TEXT, added_at TEXT, exchange TEXT, "
                "status TEXT, paper_trading_enabled INT, strategy_horizon TEXT, "
                "paper_trading_enabled_long_term INT)")
    con.executemany("INSERT INTO tickers VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    return tmp_path


def test_dual_horizon_us_name_is_polled_and_v2_eligible_per_tick(tmp_path):
    _wl(tmp_path, [("NVDA", "NVIDIA", "x", "NASDAQ", "active", 1, "DUAL_HORIZON", 1)])
    m = build_coverage_map(home=tmp_path)
    c = m["tickers"][0]
    assert c["v2_collection_scope"] == "POLLED"
    assert "EVALUATED PER-TICK" in c["v2_strategy_eligibility"]
    assert "membership-OR-liquidity" in c["v2_strategy_eligibility"]
    assert "v2_lane.db" in c["v2_paper_portfolio"]
    assert c["unsupported_reason"] == ""


def test_intraday_only_name_has_no_v2_lane(tmp_path):
    _wl(tmp_path, [("PATH", "UiPath", "x", "NASDAQ", "paused", 1, "INTRADAY", 0)])
    c = build_coverage_map(home=tmp_path)["tickers"][0]
    assert c["v2_collection_scope"] == "NOT_POLLED"
    assert "INTRADAY only" in c["v2_strategy_eligibility"]
    assert c["unsupported_reason"] == "owner did not request a multi-day horizon here"


def test_non_us_listing_is_ineligible_for_v2(tmp_path):
    _wl(tmp_path, [("SKHY", "SK Hynix", "x", "Korea Exchange (KRX)", "active", 1, "DUAL_HORIZON", 1)])
    c = build_coverage_map(home=tmp_path)["tickers"][0]
    assert c["v2_collection_scope"] == "NOT_POLLED"
    assert "INELIGIBLE" in c["v2_strategy_eligibility"]
    assert "non-US" in c["unsupported_reason"] or "Form 4 filer" in c["v2_strategy_eligibility"]


def test_five_scopes_are_present_and_distinct(tmp_path):
    _wl(tmp_path, [("AAPL", "Apple", "x", "NASDAQ", "active", 1, "DUAL_HORIZON", 1)])
    m = build_coverage_map(home=tmp_path)
    assert set(m["scopes"]) == {"1_collection", "2_user_alert",
                                "3_frozen_strategy_eligibility",
                                "4_paper_execution_eligibility",
                                "5_historical_validation_population"}
    assert "not silently substituted" in m["scopes"]["3_frozen_strategy_eligibility"].lower() \
        or "not silently substituted" in m["scopes"]["3_frozen_strategy_eligibility"]


def test_no_validated_intraday_or_longterm_edge_claimed(tmp_path):
    _wl(tmp_path, [("MSFT", "Microsoft", "x", "NASDAQ", "active", 1, "DUAL_HORIZON", 1)])
    m = build_coverage_map(home=tmp_path)
    assert m["summary"]["intraday_validated_edge"] is False
    assert m["summary"]["longterm_validated_edge"] is False
    md = to_markdown(m)
    assert "NO validated edge" in md and "Not a V2 substitute" in md


def test_markdown_renders_without_error(tmp_path):
    _wl(tmp_path, [("NVDA", "NVIDIA", "x", "NASDAQ", "active", 1, "DUAL_HORIZON", 1),
                   ("PATH", "UiPath", "x", "NASDAQ", "paused", 1, "INTRADAY", 0)])
    md = to_markdown(build_coverage_map(home=tmp_path))
    assert "| ticker |" in md and "NVDA" in md and "PATH" in md


def test_authoritative_scope_used_when_directory_cache_present(tmp_path, monkeypatch):
    """When the real intelligence.service resolution is available it is used
    verbatim (resolvable/excluded/unresolved), not a listing heuristic."""
    from talonx_ops import watchlist_coverage as wc
    monkeypatch.setattr(wc, "_authoritative_scope",
                        lambda home: {"AAA": "RESOLVABLE",
                                      "BBB": "UNRESOLVED: known_non_filer: foreign private issuer",
                                      "CCC": "EXCLUDED: status=paused"})
    _wl(tmp_path, [("AAA", "A", "x", "NASDAQ", "active", 1, "DUAL_HORIZON", 1),
                   ("BBB", "B", "x", "NYSE", "active", 1, "DUAL_HORIZON", 1),
                   ("CCC", "C", "x", "NYSE", "paused", 1, "INTRADAY", 0)])
    m = build_coverage_map(home=tmp_path)
    assert m["scope_resolution"].startswith("authoritative")
    by = {c["symbol"]: c for c in m["tickers"]}
    assert by["AAA"]["v2_collection_scope"] == "POLLED"
    assert by["BBB"]["v2_collection_scope"] == "NOT_POLLED"
    assert "foreign private issuer" in by["BBB"]["unsupported_reason"]
    assert m["active_not_polled"] == [{"symbol": "BBB",
                                       "reason": "known_non_filer: foreign private issuer"}]
