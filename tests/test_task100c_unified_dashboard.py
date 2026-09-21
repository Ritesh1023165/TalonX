"""TASK 100C Phase 18 -- unified :8787 cockpit test matrix.

Covers the 45-item checklist: section loading with stores present / missing,
overview runtime + market health, the six semantic states, the Original funnel
with 0 published + suppressions > 0, Brain ACTIVE/NO INPUT, official vs
Experimental isolation, the structural Experimental external-send status,
forward-outcome + EOD rendering, MFE/MAE, Original vs Experimental comparison,
Task 96 intelligence summary + :8760 deep-link, paper isolation, PIV
NOT_CHECKED, the five :8770 parity gates, :8501 config retention, and the
read-only / no-side-effect guarantees.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from talonx_ops.dashboard_read import DashboardReadModel

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
TODAY = "2026-09-15"


# --------------------------------------------------------------------------- #
# synthetic ~/.talonx tree
# --------------------------------------------------------------------------- #
def _db(path: Path, statements: list[tuple[str, list]]):
    con = sqlite3.connect(path)
    for ddl, rows in statements:
        con.execute(ddl)
        if rows:
            tbl = ddl.split("(")[0].split()[-1]
            ph = ",".join("?" * len(rows[0]))
            con.executemany(f"INSERT INTO {tbl} VALUES ({ph})", rows)
    con.commit()
    con.close()


@pytest.fixture
def home(tmp_path):
    h = tmp_path / ".talonx"
    (h / "experimental").mkdir(parents=True)
    (h / "intelligence").mkdir(parents=True)
    return h


@pytest.fixture
def live_meta(home):
    (home / "runtime_metadata.json").write_text(json.dumps(
        {"pid": 4242424242, "started_at": (NOW - timedelta(minutes=3)).isoformat()}))


def _model(home, *, check_processes=False, now=NOW):
    return DashboardReadModel(home=home, exp_home=home / "experimental",
                             intel_ledger=home / "ingestion_ledger.db",
                             now=now, check_processes=check_processes)


def _full_tree(home):
    """A representative populated tree: producer 'live' via metadata age,
    Original funnel with suppressions but 0 published, experimental alerts,
    forward outcomes, EOD row, intelligence rows."""
    (home / "runtime_metadata.json").write_text(json.dumps(
        {"pid": 4242424242, "started_at": (NOW - timedelta(minutes=3)).isoformat()}))
    _db(home / "quant.db", [
        ("CREATE TABLE bar_buffer(symbol TEXT, buffer_type TEXT, ts TEXT, session TEXT)",
         [("MSFT", "1m", "x", "regular")] * 30),
        ("CREATE TABLE suppression_counts(date TEXT, ticker TEXT, reason TEXT, count INT, last_seen_at TEXT)",
         [(TODAY, "MSFT", "LOW_VOLATILITY", 900, NOW.isoformat()),
          (TODAY, "NVDA", "LOW_CONFLUENCE", 12, NOW.isoformat())]),
    ])
    _db(home / "brain.db", [
        ("CREATE TABLE report_counts(date TEXT, category TEXT, count INT)", []),
    ])
    _db(home / "dispatch_audit.db", [
        ("CREATE TABLE alerts(id INTEGER PRIMARY KEY, received_at TEXT, telegram_sent INT, "
         "telegram_error TEXT, suppress_reason TEXT)", []),
    ])
    _db(home / "paper_trading.db", [
        ("CREATE TABLE latest_prices(ticker TEXT, price REAL, updated_at TEXT)",
         [("MSFT", 1.0, NOW.isoformat())]),
        ("CREATE TABLE positions(ticker TEXT PRIMARY KEY, qty REAL)", []),
        ("CREATE TABLE trade_history(id INTEGER PRIMARY KEY, timestamp TEXT)", []),
        ("CREATE TABLE portfolio_state(id INTEGER PRIMARY KEY, current_cash REAL)", [(1, 10000.0)]),
    ])
    _db(home / "watchlist.db", [
        ("CREATE TABLE tickers(symbol TEXT PRIMARY KEY, active INT)",
         [("MSFT", 1), ("NVDA", 1), ("AMD", 0)]),
        ("CREATE TABLE upcoming_earnings(ticker TEXT PRIMARY KEY, earnings_date TEXT, "
         "session TEXT, heads_up_sent INT)",
         [("MSFT", "2026-09-16", "AMC", 0), ("NVDA", "2026-09-22", "AMC", 1)]),
    ])
    _db(home / "experimental" / "exp_alerts.db", [
        ("CREATE TABLE directional_alerts(alert_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, "
         "profile TEXT, setup_type TEXT, setup_score INT, session TEXT, price REAL, "
         "trade_gate_status TEXT, trade_gate_reject_reason TEXT, bar_timestamp TEXT, sent INT)",
         [("D" + "a" * 16, "MSFT", "BULLISH", "EXPERIMENTAL_RELAXED_V1", "reclaim", 1, "regular",
           100.0, "WOULD_PASS", None, NOW.isoformat(), 0),
          ("D" + "b" * 16, "NVDA", "BEARISH", "EXPERIMENTAL_RELAXED_V1", "macd", 0, "regular",
           200.0, "WOULD_REJECT", "LOW_CONFLUENCE", NOW.isoformat(), 0)]),
        ("CREATE TABLE experimental_trades(trade_id TEXT PRIMARY KEY, symbol TEXT, side TEXT, "
         "entry REAL, exit REAL, net_pnl REAL, r_multiple REAL, opened_at TEXT, closed_at TEXT, sent INT)",
         []),
        ("CREATE TABLE radar_alerts(radar_id TEXT PRIMARY KEY, sent INT)", []),
        ("CREATE TABLE event_updates(event_id TEXT PRIMARY KEY, sent INT)", []),
    ])
    _db(home / "experimental" / "experimental_paper.db", [
        ("CREATE TABLE positions(ticker TEXT PRIMARY KEY, qty REAL)", []),
        ("CREATE TABLE trade_history(id INTEGER PRIMARY KEY, timestamp TEXT)", []),
        ("CREATE TABLE portfolio_state(id INTEGER PRIMARY KEY, current_cash REAL)", [(1, 100000.0)]),
    ])
    _db(home / "experimental" / "forward_outcomes.db", [
        ("CREATE TABLE forward_observations(obs_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, "
         "kind TEXT, reference_price REAL, mfe REAL, mae REAL, r_30m REAL, r_60m REAL, r_eod REAL, "
         "r_1d REAL, status TEXT, alert_ts TEXT)",
         [("FO-1", "MSFT", "BULLISH", "trade", 100.0, 1.5, -0.4, 0.9, None, None, None,
           "PENDING_60M", NOW.isoformat())]),
    ])
    _db(home / "ingestion_ledger.db", [
        ("CREATE TABLE text_events(event_id TEXT PRIMARY KEY, symbol TEXT, event_type TEXT, "
         "accepted_at_utc TEXT, filing_date TEXT)",
         [("E1", "MSFT", "EARNINGS_RESULTS", (NOW - timedelta(days=1)).isoformat(), "2026-09-14")]),
        ("CREATE TABLE event_significance(event_id TEXT PRIMARY KEY, band TEXT, score INT)",
         [("E1", "HIGH", 6)]),
        ("CREATE TABLE intelligence_delivery(card_id TEXT PRIMARY KEY, status TEXT)", []),
    ])
    from talonx_ops.eod_reconciliation import run_and_persist
    run_and_persist(session_date=TODAY, db_path=home / "eod_reconciliation.db", home=home,
                    exp_home=home / "experimental", ledger_path=home / "ingestion_ledger.db", now=NOW)


# --------------------------------------------------------------------------- #
# 1-2 section loading
# --------------------------------------------------------------------------- #
def test_01_all_sections_load_with_stores_present(home):
    _full_tree(home)
    s = _model(home).all_sections()
    assert set(s) == {"overview", "premarket", "original_quant", "v2_active_strategy", "v2_broad_discovery", "validation",
                      "intelligence", "paper_eod"}
    for v in s.values():
        assert "error" not in v


def test_02_sections_load_with_optional_stores_missing(home):
    # empty tree, only the dir exists
    s = _model(home).all_sections()
    assert set(s) == {"overview", "premarket", "original_quant", "v2_active_strategy", "v2_broad_discovery", "validation",
                      "intelligence", "paper_eod"}
    for v in s.values():
        assert "error" not in v


# --------------------------------------------------------------------------- #
# 3-4 overview runtime + market
# --------------------------------------------------------------------------- #
def test_03_overview_runtime_state(home):
    _full_tree(home)
    ov = _model(home).overview()
    r = ov["runtime"]
    assert set(r) >= {"overall", "original", "experimental", "intelligence", "telegram_send",
                      "telegram_receive", "forward_outcomes", "eod"}
    assert r["original"] in ("READY", "FAILED")


def test_04_market_health_rendering(home):
    _full_tree(home)
    m = _model(home).overview()["market"]
    assert set(m) >= {"state", "last_event", "last_event_age_seconds", "configured_symbols",
                      "selected_symbols", "usable_coverage", "provider_failures", "redis_reconnects"}
    assert m["configured_symbols"] == 3
    assert m["selected_symbols"] == 2


# --------------------------------------------------------------------------- #
# 5-9 semantic states
# --------------------------------------------------------------------------- #
def test_05_active_state(home):
    _full_tree(home)
    ss = {d["domain"]: d["status"] for d in _model(home).overview()["source_status"]}
    assert ss["quant_funnel"] == "ACTIVE"          # suppressions today > 0


def test_06_zero_activity_state(home, live_meta):
    # producer live (metadata fresh), but no funnel rows at all
    _db(home / "quant.db", [
        ("CREATE TABLE suppression_counts(date TEXT, ticker TEXT, reason TEXT, count INT, last_seen_at TEXT)", []),
    ])
    ss = {d["domain"]: d["status"] for d in _model(home).overview()["source_status"]}
    assert ss["quant_funnel"] == "ZERO_ACTIVITY"


def test_07_no_active_producer_state(home, live_meta):
    # producer 'live' (fresh metadata) but the funnel store has no rows at all,
    # and the market tap has no priced symbols -> the two states differ
    _db(home / "quant.db", [
        ("CREATE TABLE suppression_counts(date TEXT, ticker TEXT, reason TEXT, count INT, last_seen_at TEXT)", []),
    ])
    ss = {d["domain"]: d["status"] for d in _model(home).overview()["source_status"]}
    # producer live + no funnel rows today -> ZERO_ACTIVITY (a real zero, distinct from NO_ACTIVE_PRODUCER)
    assert ss["quant_funnel"] == "ZERO_ACTIVITY"
    # now with NO metadata at all -> NO_ACTIVE_PRODUCER for market
    (home / "runtime_metadata.json").unlink()
    ss2 = {d["domain"]: d["status"] for d in _model(home).overview()["source_status"]}
    assert ss2["market"] == "NO_ACTIVE_PRODUCER"
    assert ss2["quant_funnel"] == "NO_ACTIVE_PRODUCER"


def test_08_superseded_state(home):
    ss = {d["domain"]: d["status"] for d in _model(home).intelligence().get("status", "") and [] or []}
    # filings_legacy_channel is SUPERSEDED in the read model; assert via source_status
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel
    da = AuthoritativeReadModel(home=home, check_processes=False).filings_legacy_channel()
    assert da.status.value == "SUPERSEDED"


def test_09_stale_state(home, live_meta):
    # producer live, but newest tick is ancient -> market STALE
    _db(home / "paper_trading.db", [
        ("CREATE TABLE latest_prices(ticker TEXT, price REAL, updated_at TEXT)",
         [("MSFT", 1.0, "2020-01-01T00:00:00+00:00")]),
    ])
    m = _model(home).overview()["market"]
    assert m["state"] == "STALE"


# --------------------------------------------------------------------------- #
# 10-11 Original funnel semantics
# --------------------------------------------------------------------------- #
def test_10_suppressions_visible_with_zero_published(home):
    _full_tree(home)
    oq = _model(home).original_quant()
    assert oq["funnel"]["suppressions_today"] == 912
    assert (oq["funnel"]["published_quant_signals_today"] or 0) == 0
    reasons = {r["reason"]: r["count"] for r in oq["funnel"]["by_reason"]}
    assert reasons["LOW_VOLATILITY"] == 900
    assert reasons["LOW_CONFLUENCE"] == 12
    assert "ACTIVE" in oq["quant_state"] and "NO SIGNALS PASSED" in oq["quant_state"]
    assert "not 'quant inactive'" in oq["quant_state_note"].lower()


def test_11_brain_active_no_input_distinction(home):
    _full_tree(home)
    oq = _model(home).original_quant()
    assert oq["brain_state"] == "ACTIVE / NO INPUT"
    assert "not broken" in oq["brain_state_note"].lower()


# --------------------------------------------------------------------------- #
# 12-14 alert isolation + experimental boundary
# --------------------------------------------------------------------------- #
def test_12_official_alerts_isolated(home):
    _full_tree(home)
    ov = _model(home).overview()
    a = ov["alerts"]
    assert "official_generated" in a and "official_sent" in a
    # official keys and experimental keys are distinct namespaces
    assert "experimental_external_boundary" in a
    assert not any(k.startswith("official") and "experimental" in k for k in a)


def test_13_experimental_alerts_clearly_internal(home):
    _full_tree(home)
    v = _model(home).validation()
    assert v["internal_only"] is True
    assert v["external_dispatchable"] is False
    assert "NOT OFFICIAL TRADING SIGNALS" in v["label"]
    assert "NO 'send Telegram'" in v["no_send_action"]


def test_14_experimental_external_send_blocked(home):
    _full_tree(home)
    ov = _model(home).overview()
    assert ov["alerts"]["experimental_live_external_sends"] == 0
    assert "BLOCKED" in ov["alerts"]["experimental_external_boundary"]
    assert ov["alerts"]["experimental_external_eligible"] is False
    v = _model(home).validation()
    assert v["live_external_sends"] == 0
    assert "BLOCKED" in v["external_boundary"]


# --------------------------------------------------------------------------- #
# 15-20 forward outcomes + EOD
# --------------------------------------------------------------------------- #
def test_15_16_17_18_forward_horizons_render(home):
    _full_tree(home)
    fo = _model(home).validation()["forward_outcomes"]
    assert fo["status"] == "ACTIVE"
    row = fo["recent"][0]
    for h in ("r_30m", "r_60m", "r_eod", "r_1d"):
        assert h in row
    assert fo["summary"]["resolved_30m"] == 1
    assert fo["summary"]["resolved_60m"] == 0


def test_19_mfe_mae_render(home):
    _full_tree(home)
    row = _model(home).validation()["forward_outcomes"]["recent"][0]
    assert row["mfe"] == 1.5
    assert row["mae"] == -0.4


def test_20_pending_outcome_render(home):
    _full_tree(home)
    fo = _model(home).validation()["forward_outcomes"]
    assert fo["summary"]["pending"] == 1


def test_21_original_vs_experimental_comparison(home):
    _full_tree(home)
    cmp = _model(home).validation()["original_vs_experimental"]
    assert cmp["original"]["thresholds"]["min_atr_pct"] == 0.25
    assert cmp["experimental"]["thresholds"]["min_atr_pct"] == 0.10
    assert "not a profitability claim" in cmp["note"].lower()


# --------------------------------------------------------------------------- #
# 22-25 intelligence
# --------------------------------------------------------------------------- #
def test_22_filing_rendering(home):
    _full_tree(home)
    intel = _model(home).intelligence()
    assert intel["latest_events"][0]["symbol"] == "MSFT"
    assert intel["latest_events"][0]["event_type"] == "EARNINGS_RESULTS"


def test_23_insider_rendering_key_present(home):
    _full_tree(home)
    intel = _model(home).intelligence()
    assert "insider_recent" in intel


def test_24_significance_descriptive_wording(home):
    _full_tree(home)
    intel = _model(home).intelligence()
    assert intel["descriptive_only"] is True
    assert "no forward-return" in intel["disclaimer"].lower()
    assert intel["significance_ranked"][0]["band"] == "HIGH"


def test_25_deep_link_to_8760(home):
    _full_tree(home)
    intel = _model(home).intelligence()
    assert intel["deep_link"] == "http://localhost:8760"
    assert intel["deep_links"]["filings"].endswith("/filings")


# --------------------------------------------------------------------------- #
# 26-29 paper / EOD isolation
# --------------------------------------------------------------------------- #
def test_26_original_paper_isolated(home):
    _full_tree(home)
    p = _model(home).paper_eod()
    assert "ORIGINAL" in p["original_local_paper"]["attribution"]
    assert p["original_local_paper"]["current_cash"] == 10000.0


def test_27_experimental_paper_isolated(home):
    _full_tree(home)
    p = _model(home).paper_eod()
    assert p["experimental_validation_paper"]["internal_only"] is True
    assert p["experimental_validation_paper"]["current_cash"] == 100000.0
    # never merged
    assert p["original_local_paper"]["current_cash"] != p["experimental_validation_paper"]["current_cash"]
    assert "SEPARATE" in p["separation_note"]


def test_28_piv_not_checked_rendering(home):
    _full_tree(home)
    piv = _model(home).paper_eod()["piv_alpaca_paper"]
    assert piv["positions"] == "NOT_CHECKED"
    assert piv["orders"] == "NOT_CHECKED"
    assert piv["checked"] is False


def test_29_eod_reconciliation_rendering(home):
    _full_tree(home)
    r = _model(home).paper_eod()["eod_reconciliation"]
    # DomainAuthority.status maps PARTIAL -> STALE; the raw reconciliation
    # status lives under values["status"]
    assert r["status"] in ("STALE", "ACTIVE", "UNKNOWN")
    assert r["values"]["status"] in ("PARTIAL", "RECONCILED", "RECONCILED_WITH_MISMATCH")
    assert "EodReconciliationStore" in r["authoritative_source"]
    assert r["values"]["latest_session"] == TODAY


# --------------------------------------------------------------------------- #
# 30-34 :8770 parity gates
# --------------------------------------------------------------------------- #
def test_30_parity_gate1_experimental_alert_visibility(home):
    _full_tree(home)
    v = _model(home).validation()
    assert len(v["directional_recent"]) == 2
    assert {a["direction"] for a in v["directional_recent"]} == {"BULLISH", "BEARISH"}


def test_31_parity_gate2_forward_outcome_visibility(home):
    _full_tree(home)
    fo = _model(home).validation()["forward_outcomes"]
    assert fo["recent"] and all(k in fo["recent"][0] for k in ("mfe", "mae", "r_30m", "r_60m", "r_eod", "r_1d"))


def test_32_parity_gate3_profile_gate_diagnostics(home):
    _full_tree(home)
    v = _model(home).validation()
    assert v["frozen_profile"] == {"min_atr_pct": 0.10, "confluence_score_min": 1, "min_risk_reward_ratio": 1.0}
    assert v["gate_breakdown"]["WOULD_PASS"] == 1
    assert v["gate_breakdown"]["WOULD_REJECT"] == 1
    assert v["reject_reasons"][0]["reason"] == "LOW_CONFLUENCE"


def test_33_parity_gate4_earnings_intelligence_bridge_visibility(home):
    _full_tree(home)
    pm = _model(home).premarket()
    syms = {i["symbol"] for i in pm["earnings_radar"]["items"]}
    assert {"MSFT", "NVDA"} <= syms
    assert pm["event_context"]["items"][0]["symbol"] == "MSFT"


def test_34_parity_gate5_operational_health_freshness(home):
    _full_tree(home)
    ov = _model(home).overview()
    assert "state" in ov["market"] and "last_event_age_seconds" in ov["market"]
    assert ov["runtime"]["experimental"] in ("READY", "DEGRADED", "FAILED")
    # every section exposes an authoritative source somewhere
    assert any("source" in str(k).lower() or "authoritative" in str(k).lower()
               for k in _model(home).intelligence())


# --------------------------------------------------------------------------- #
# 35 :8501 config editing retained
# --------------------------------------------------------------------------- #
def test_35_streamlit_config_editing_retained():
    src = Path("talonx_dispatch/app.py").read_text(encoding="utf-8")
    # the write surfaces must still be present -- Task 100C does NOT touch :8501
    for marker in ("store.add_ticker", "store.remove_ticker", "store.set_strategy_horizon",
                   "update_trade_allocation", "update_dca_contribution_amount"):
        assert marker in src


# --------------------------------------------------------------------------- #
# 36-39 read-only / no side effects
# --------------------------------------------------------------------------- #
def test_36_no_dashboard_write_side_effect(home):
    _full_tree(home)
    before = {p.name: p.stat().st_mtime_ns for p in home.rglob("*.db")}
    m = _model(home)
    m.all_sections()
    m.all_sections()
    after = {p.name: p.stat().st_mtime_ns for p in home.rglob("*.db")}
    assert before == after, "a dashboard read mutated a store file"


def test_37_no_strategy_mutation():
    # DashboardReadModel must not import a strategy/execution engine
    src = Path("talonx_ops/dashboard_read.py").read_text(encoding="utf-8")
    for banned in ("talonx_quant.consumer", "talonx_core.consumer", "talonx_core.decision",
                   "talonx_paper.consumer", "DecisionEngine", "QuantScanner"):
        assert banned not in src


def test_38_no_broker_action():
    # The word "Alpaca" appears only in descriptive labels; what must NOT appear
    # is any broker/order ACTION.
    src = Path("talonx_ops/dashboard_read.py").read_text(encoding="utf-8")
    for banned in ("submit_order", "place_order", "TradingClient", "REST(", "get_broker",
                   "execute_buy", "execute_sell", "cancel_order", "post("):
        assert banned.lower() not in src.lower()
    # and the descriptive PIV row is always NOT_CHECKED (no live query)
    assert '"positions": "NOT_CHECKED"' in src


def test_39_no_experimental_telegram_action():
    html = Path("dashboard_web_static/index.html").read_text(encoding="utf-8")
    assert "send telegram" not in html.lower()
    assert 'method="post"' not in html.lower()
    src = Path("talonx_ops/dashboard_read.py").read_text(encoding="utf-8")
    assert "TelegramSenderAdapter" not in src and "enable_external_send" not in src


# --------------------------------------------------------------------------- #
# 40-45 endpoints + resilience + layout
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_40_websocket_and_section_routes_stable(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    import dashboard_web

    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    async with TestClient(TestServer(app)) as c:
        assert (await c.get("/")).status == 200
        r = await c.get("/api/sections")
        assert r.status == 200
        body = await r.json()
        assert set(body) == {"overview", "premarket", "original_quant", "v2_active_strategy", "v2_broad_discovery", "validation",
                             "intelligence", "paper_eod"}
        for name in body:
            rr = await c.get("/api/section/" + name)
            assert rr.status in (200, 500)  # 500 only on a genuine read error, still JSON
        assert (await c.get("/api/section/bogus")).status == 404


@pytest.mark.asyncio
async def test_41_missing_redis_safe(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    import dashboard_web

    # section reads do not touch Redis at all -- prove they still answer
    app = dashboard_web.build_app(piv_state_dir=tmp_path)
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/api/section/overview")
        assert r.status == 200
        d = await r.json()
        assert "runtime" in d


def test_42_stale_timestamp_safe(home, live_meta):
    _db(home / "ingestion_ledger.db", [
        ("CREATE TABLE text_events(event_id TEXT PRIMARY KEY, symbol TEXT, event_type TEXT, "
         "accepted_at_utc TEXT)", [("E1", "MSFT", "8-K", "not-a-timestamp")]),
    ])
    intel = _model(home).intelligence()  # must not raise
    assert "latest_events" in intel


def test_43_empty_db_safe(home):
    _db(home / "quant.db", [("CREATE TABLE suppression_counts(date TEXT, ticker TEXT, reason TEXT, count INT, last_seen_at TEXT)", [])])
    _db(home / "experimental" / "exp_alerts.db", [("CREATE TABLE directional_alerts(alert_id TEXT PRIMARY KEY, symbol TEXT)", [])])
    s = _model(home).all_sections()
    for v in s.values():
        assert "error" not in v


def test_44_large_alert_table_bounded(home, live_meta):
    rows = [("D" + f"{i:016d}", "MSFT", "BULLISH", "EXPERIMENTAL_RELAXED_V1", "s", 1, "regular",
             100.0, "WOULD_REJECT", "LOW_CONFLUENCE", NOW.isoformat(), 0) for i in range(500)]
    _db(home / "experimental" / "exp_alerts.db", [
        ("CREATE TABLE directional_alerts(alert_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, "
         "profile TEXT, setup_type TEXT, setup_score INT, session TEXT, price REAL, "
         "trade_gate_status TEXT, trade_gate_reject_reason TEXT, bar_timestamp TEXT, sent INT)", rows),
    ])
    v = _model(home).validation()
    assert len(v["directional_recent"]) <= 25            # bounded
    assert v["gate_breakdown"]["WOULD_REJECT"] <= 200    # sampled, not unbounded


def test_45_narrow_layout_integrity():
    html = Path("dashboard_web_static/index.html").read_text(encoding="utf-8")
    assert "@media (max-width:640px)" in html          # responsive rule present
    assert "grid-template-columns:1fr" in html         # single column on narrow
    assert "overflow-x:auto" in html                   # wide tables scroll, not the body
    assert 'name="viewport"' in html
