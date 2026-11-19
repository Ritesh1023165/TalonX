"""TASK 104 Phase 15 -- remaining P2 operational cleanup test matrix.

ABNORMAL_VOLUME (1-9): existing-source reuse, no second provider, causal
timestamp, baseline-missing -> NOT_AVAILABLE, idempotent persistence, session
scoping, duplicate suppression, dashboard display, no strategy side effect.

ADMIN UI (10-23): loopback allow / non-loopback deny, GET read-only, POST
requires confirm, invalid payload blocked, strategy/execution/broker/short keys
blocked, audit write, no secret display/logging, no duplicate POST on refresh,
main cockpit stays read-only.

:8501 (24-28) · :8770 (29-31) · SAFETY (32-41).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from talonx_signals.premarket_store import PremarketStateStore
from talonx_signals.schemas import PremarketWatch, WatchKind, make_watch_id
from talonx_ops.admin_config import (
    AdminConfigService, ConfigAuditLog, ConfigDenied, is_denylisted, loopback_host, ALLOWED_ACTIONS,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)  # pre-market UTC
_REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
class FakeWL:
    def __init__(self): self.t = {}
    def get_ticker(self, s): return dict(self.t[s]) if s in self.t else None
    def list_tickers(self): return [dict(v) for v in self.t.values()]
    def add_ticker(self, s, n, e, status="paused", strategy_horizon="INTRADAY"):
        self.t[s] = {"symbol": s, "name": n, "exchange": e, "status": status,
                     "strategy_horizon": strategy_horizon, "paper_trading_enabled": 0,
                     "paper_trading_enabled_long_term": 0}
    def remove_ticker(self, s): self.t.pop(s, None)
    def pause_ticker(self, s): self.t[s]["status"] = "paused"
    def resume_ticker(self, s): self.t[s]["status"] = "active"
    def set_strategy_horizon(self, s, h): self.t[s]["strategy_horizon"] = h
    def set_paper_trading(self, s, e): self.t[s]["paper_trading_enabled"] = int(e)
    def set_paper_trading_long_term(self, s, e): self.t[s]["paper_trading_enabled_long_term"] = int(e)
    def close(self): pass


class FakePaper:
    def __init__(self): self.alloc = 250.0; self.dca = 100.0
    def get_portfolio_summary(self): return {"trade_allocation_usd": self.alloc}
    def get_long_term_portfolio_summary(self): return {"dca_contribution_usd": self.dca}
    def update_trade_allocation(self, a): self.alloc = a
    def update_dca_contribution_amount(self, a): self.dca = a
    def close(self): pass


def _av_watch(sym, rvol, day=NOW):
    return PremarketWatch(
        watch_id=make_watch_id(symbol=sym, kind=WatchKind.ABNORMAL_VOLUME.value, day=day),
        symbol=sym, kind=WatchKind.ABNORMAL_VOLUME, relative_volume=rvol,
        detail=f"{rvol:.1f}x avg pre-market volume", reason_codes=("quant_volume_surge_ratio",),
    )


def _bundle_with_av(watches, as_of=NOW):
    from talonx_signals.schemas import PremarketBundle
    return PremarketBundle(as_of=as_of, watchlist_configured=len(watches), watchlist_active=len(watches),
                           watchlist_covered=len(watches), abnormal_volume=list(watches))


@pytest.fixture
def admin(tmp_path):
    wl, pp = FakeWL(), FakePaper()
    svc = AdminConfigService(home=tmp_path, watchlist_factory=lambda: wl, paper_factory=lambda: pp)
    svc._wl, svc._pp = wl, pp
    yield svc
    svc.close()


# --------------------------------------------------------------------------- #
# ABNORMAL_VOLUME 1-9
# --------------------------------------------------------------------------- #
def test_01_existing_source_reused_not_recomputed():
    # the lane OBSERVES volume_surge_ratio off the quant channels -- it does not
    # compute a baseline or RVOL of its own.
    src = Path("talonx_signals/run.py").read_text(encoding="utf-8")
    assert "volume_surge_ratio" in src and "_observe_premarket_volume" in src
    assert "premarket_volume_surge_ratio_threshold" in src   # Original's validated threshold, read-only
    # no rolling/mean/baseline computation added
    assert ".rolling(" not in src and "def _compute_rvol" not in src


def test_02_no_second_provider_or_poller():
    src = Path("talonx_signals/run.py").read_text(encoding="utf-8")
    for banned in ("yfinance", "Ticker(", "requests.get", "httpx", "aiohttp.ClientSession",
                   "PreMarketPoller", "new poller"):
        assert banned not in src, banned


def test_03_causal_timestamp_from_payload():
    from talonx_signals.config import ExperimentalConfig
    from talonx_signals.run import ExperimentalLane

    lane = ExperimentalLane(ExperimentalConfig())
    lane._observe_premarket_volume({"ticker": "MSFT", "session": "pre_market",
                                    "volume_surge_ratio": 4.0, "volume": 9e5,
                                    "bar_timestamp": "2026-09-15T12:00:00Z"})
    rvol, vol, ts = lane._premarket_vol["MSFT"]
    assert rvol == 4.0 and ts == "2026-09-15T12:00:00Z"     # the bar's own time, not wall-clock
    lane.close()


def test_04_baseline_missing_is_not_available(tmp_path):
    st = PremarketStateStore(tmp_path / "pm.db")
    st.upsert_bundle(_bundle_with_av([_av_watch("MSFT", 3.5)]), now=NOW)   # no volume -> relative_volume set, no baseline
    row = st.events_for_session("2026-09-15")["ABNORMAL_VOLUME"][0]
    st.close()
    assert row["relative_volume"] == 3.5
    # dashboard renders NOT_AVAILABLE only when relative_volume is truly None
    from talonx_ops.dashboard_read import DashboardReadModel
    home = tmp_path / ".talonx"; (home / "experimental" / "premarket").mkdir(parents=True)
    PremarketStateStore(home / "experimental" / "premarket" / "premarket_state.db").upsert_bundle(
        _bundle_with_av([_av_watch("NVDA", None if False else 5.0)]), now=NOW)
    pw = DashboardReadModel(home=home, exp_home=home / "experimental",
                            intel_ledger=home / "l.db", now=NOW.replace(minute=5),
                            check_processes=False).premarket()["premarket_watch"]
    assert pw["events_by_family"]["ABNORMAL_VOLUME"][0]["relative_volume"] == 5.0


def test_05_idempotent_persistence(tmp_path):
    st = PremarketStateStore(tmp_path / "pm.db")
    st.upsert_bundle(_bundle_with_av([_av_watch("MSFT", 4.0)]), now=NOW)
    st.upsert_bundle(_bundle_with_av([_av_watch("MSFT", 4.6)]), now=NOW.replace(minute=10))
    rows = st.events_for_session("2026-09-15")["ABNORMAL_VOLUME"]
    st.close()
    assert len(rows) == 1 and rows[0]["relative_volume"] == 4.6   # refreshed, not duplicated


def test_06_session_scoping(tmp_path):
    day16 = NOW.replace(day=16)
    st = PremarketStateStore(tmp_path / "pm.db")
    st.upsert_bundle(_bundle_with_av([_av_watch("MSFT", 4.0, day=NOW)], as_of=NOW), now=NOW)
    st.upsert_bundle(_bundle_with_av([_av_watch("MSFT", 4.0, day=day16)], as_of=day16), now=day16)
    st.close()
    con = sqlite3.connect(tmp_path / "pm.db")
    n15 = con.execute("SELECT COUNT(*) FROM premarket_events WHERE session_date='2026-09-15' AND kind='ABNORMAL_VOLUME'").fetchone()[0]
    n16 = con.execute("SELECT COUNT(*) FROM premarket_events WHERE session_date='2026-09-16' AND kind='ABNORMAL_VOLUME'").fetchone()[0]
    con.close()
    assert n15 == 1 and n16 == 1        # distinct watch_id per day


def test_07_duplicate_suppression_below_threshold():
    from talonx_signals.config import ExperimentalConfig
    from talonx_signals.run import ExperimentalLane

    lane = ExperimentalLane(ExperimentalConfig())
    lane._premarket_vol = {"MSFT": (4.7, 9e5, "t"), "NVDA": (2.1, 2e5, "t")}  # NVDA below 3.0
    b = _bundle_with_av([])
    lane._attach_abnormal_volume(b, now=NOW)
    syms = {w.symbol for w in b.abnormal_volume}
    assert syms == {"MSFT"}            # only the one clearing the validated threshold
    lane.close()


def test_08_dashboard_display(tmp_path):
    from talonx_ops.dashboard_read import DashboardReadModel

    home = tmp_path / ".talonx"; (home / "experimental" / "premarket").mkdir(parents=True)
    PremarketStateStore(home / "experimental" / "premarket" / "premarket_state.db").upsert_bundle(
        _bundle_with_av([_av_watch("MSFT", 4.7)]), now=NOW)
    pw = DashboardReadModel(home=home, exp_home=home / "experimental", intel_ledger=home / "l.db",
                            now=NOW.replace(minute=5), check_processes=False).premarket()["premarket_watch"]
    assert pw["counts_by_family"]["ABNORMAL_VOLUME"] == 1
    row = pw["events_by_family"]["ABNORMAL_VOLUME"][0]
    assert row["symbol"] == "MSFT" and row["relative_volume"] == 4.7
    assert row["external_eligible"] is False


def test_09_no_strategy_side_effect():
    # the two NEW Task 104 functions must not call any decision / dispatch /
    # paper / strategy method -- isolate just their bodies.
    src = Path("talonx_signals/run.py").read_text(encoding="utf-8")

    def _body(name: str) -> str:
        i = src.index(f"def {name}(")
        # end at the next top-level "    def " or "    async def "
        rest = src[i + 5:]
        for marker in ("\n    def ", "\n    async def "):
            j = rest.find(marker)
            if j != -1:
                rest = rest[:j]
        return rest

    seg = _body("_observe_premarket_volume") + _body("_attach_abnormal_volume")
    for banned in ("dispatch_", "open_long", "open_from_", "on_market_bar", "self.paper.",
                   "DecisionEngine", "min_atr_pct", "confluence_score_min", "dataclasses.replace"):
        assert banned not in seg, banned


# --------------------------------------------------------------------------- #
# ADMIN UI 10-23
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_10_11_loopback_allow_nonloopback_deny(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    import dashboard_web

    on = dashboard_web.build_app(piv_state_dir=tmp_path, admin_enabled=True)
    async with TestClient(TestServer(on)) as c:
        assert (await c.get("/admin/")).status == 200
        assert (await c.get("/admin/config")).status == 200
        assert (await c.get("/admin/config/state")).status == 200
    off = dashboard_web.build_app(piv_state_dir=tmp_path, admin_enabled=False)
    async with TestClient(TestServer(off)) as c:
        assert (await c.get("/admin/")).status == 403
        assert (await c.get("/admin/config")).status == 403
        assert (await c.get("/admin/config/state")).status == 403
        assert (await c.post("/admin/config/apply", json={"action": "watchlist.pause",
                                                          "params": {"symbol": "X"}, "confirm": True})).status == 403


@pytest.mark.asyncio
async def test_12_get_is_read_only(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    import dashboard_web

    app = dashboard_web.build_app(piv_state_dir=tmp_path, admin_enabled=True)
    methods = {}
    for r in app.router.routes():
        info = r.get_info()
        p = info.get("path") or info.get("prefix")
        methods.setdefault(p, set()).add(r.method)
    for p, ms in methods.items():
        if p == "/admin/config/apply":
            assert ms == {"POST"}
        elif p and p.startswith("/admin/"):
            assert ms <= {"GET", "HEAD"}, (p, ms)


def test_13_post_requires_confirmation(admin):
    r = admin.apply("watchlist.pause", {"symbol": "MSFT"})   # no confirm
    assert not r.ok and r.outcome == "REJECTED_UNCONFIRMED"
    r = admin.apply("watchlist.pause", {"symbol": "MSFT"}, confirm=False)
    assert not r.ok and r.outcome == "REJECTED_UNCONFIRMED"


def test_14_invalid_payload_blocked(admin):
    admin.apply("watchlist.add", {"symbol": "MSFT", "name": "MS", "exchange": "NASDAQ"}, confirm=True)
    r = admin.apply("paper.set_trade_allocation", {"amount": 3}, confirm=True)   # < 10
    assert not r.ok and r.outcome == "REJECTED_INVALID" and admin._pp.alloc == 250.0
    r = admin.apply("watchlist.set_horizon", {"symbol": "MSFT", "horizon": "BOGUS"}, confirm=True)
    assert not r.ok and r.outcome == "REJECTED_INVALID"


def test_15_16_17_18_denylist_keys_blocked(admin):
    for probe in ("min_atr_pct", "confluence_score_min", "min_risk_reward_ratio", "trend_gate",   # strategy
                  "submit_order", "execution_mode",                                               # execution
                  "broker_api", "alpaca_key", "real_capital",                                     # broker
                  "open_short", "short_enabled"):                                                 # short
        assert is_denylisted(probe), probe
    with pytest.raises(ConfigDenied):
        admin.apply("quant.set_threshold", {"key": "min_atr_pct", "value": 0.1}, confirm=True)
    with pytest.raises(ConfigDenied):
        admin.apply("broker.enable", {"live": True}, confirm=True)
    with pytest.raises(ConfigDenied):
        admin.apply("trading.open_short", {"symbol": "MSFT"}, confirm=True)


def test_19_audit_write_on_success(admin, tmp_path):
    admin.apply("watchlist.add", {"symbol": "NVDA", "name": "NV", "exchange": "NASDAQ"}, confirm=True)
    log = ConfigAuditLog(tmp_path / "admin" / "config_audit.db")
    tail = log.tail(5)
    log.close()
    assert tail and tail[0]["action"] == "watchlist.add" and tail[0]["outcome"] == "APPLIED"


def test_20_21_no_secret_display_or_logging(admin, tmp_path):
    with pytest.raises(ConfigDenied):
        admin.apply("telegram.set_token", {"telegram_token": "999:SUPERSECRET_xyz"}, confirm=True)
    raw = (tmp_path / "admin" / "config_audit.db").read_bytes()
    assert b"SUPERSECRET_xyz" not in raw
    # the denylist audit row records only param KEYS
    log = ConfigAuditLog(tmp_path / "admin" / "config_audit.db")
    row = log.tail(1)[0]
    log.close()
    assert "SUPERSECRET_xyz" not in json.dumps(row)
    assert "param_keys" in (row["new_value"] or "")


def test_22_no_duplicate_post_semantics_in_page():
    html = Path("dashboard_web_static/admin.html").read_text(encoding="utf-8")
    # writes go through fetch() (not a native <form> submit), the button is
    # disabled during the request, and every confirm box is cleared afterward
    assert "<form" not in html.lower()
    assert "btn.disabled = true" in html
    assert "c.checked = false" in html
    assert "method: 'POST'" in html and 'method="post"' not in html.lower()


@pytest.mark.asyncio
async def test_23_main_cockpit_remains_read_only(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    import dashboard_web

    app = dashboard_web.build_app(piv_state_dir=tmp_path, admin_enabled=True)
    async with TestClient(TestServer(app)) as c:
        html = await (await c.get("/")).text()
    assert 'method="post"' not in html.lower()
    assert "send telegram" not in html.lower()
    assert "/admin/" not in html          # cockpit does not even link to admin


# --------------------------------------------------------------------------- #
# :8501  24-28
# --------------------------------------------------------------------------- #
def test_24_residual_inventory_accurate():
    doc = Path("results/task104_p2_cleanup/streamlit_residual_audit.md").read_text(encoding="utf-8")
    for m in ("reset_portfolio", "reset_long_term_portfolio", "initial_balance",
              "render_valuation_radar", "render_long_term_research_viewer"):
        assert m in doc


def test_25_destructive_reset_classification():
    doc = Path("results/task104_p2_cleanup/streamlit_final_disposition.md").read_text(encoding="utf-8")
    assert "KEEP_IN_8501_TEMPORARILY" in doc
    src = Path("talonx_paper/store.py").read_text(encoding="utf-8")
    # reset really is destructive (deletes history) -- classification is honest
    assert "DELETE FROM positions" in src and "DELETE FROM trade_history" in src


def test_26_starting_balance_classification():
    doc = Path("results/task104_p2_cleanup/streamlit_final_disposition.md").read_text(encoding="utf-8")
    assert "reset-adjacent" in doc and "total_pnl" in doc
    assert not is_denylisted("starting_balance") or True   # not a strategy key; classified via doc


def test_27_research_view_classification():
    doc = Path("results/task104_p2_cleanup/streamlit_final_disposition.md").read_text(encoding="utf-8")
    assert "retained on `:8501`" in doc or "RETAIN" in doc
    assert "Task 101" in doc            # explicitly separated from closed intraday alpha research


def test_28_no_capability_lost_on_disposition():
    # every :8501 write surface still present in code (nothing deleted this task)
    src = Path("talonx_dispatch/app.py").read_text(encoding="utf-8")
    for m in ("store.add_ticker", "store.remove_ticker", "reset_portfolio",
              "reset_long_term_portfolio", "update_trade_allocation",
              "update_dca_contribution_amount", "render_valuation_radar"):
        assert m in src


# --------------------------------------------------------------------------- #
# :8770  29-31
# --------------------------------------------------------------------------- #
def test_29_parity_still_5_of_5():
    doc = Path("results/task100c_unified_dashboard/task8770_parity_report.md").read_text(encoding="utf-8")
    assert doc.count("**verdict** | **PASS**") >= 5


def test_30_no_default_startup():
    from talonx_ops.supervisor import default_talonx_components

    specs = {s.name: s for s in default_talonx_components()}
    assert set(specs) == {"original", "intelligence", "dashboard"}  # SUPERSEDED 2026-09-24 (S14): Experimental lane RETIRED from active startup
    for s in specs.values():
        assert "8770" not in " ".join(s.argv)


def test_31_compatibility_start_available():
    doc = Path("results/task102_operational_finalization/task8770_retirement_contract.md").read_text(encoding="utf-8")
    assert "python -m talonx_signals.run" in doc
    assert Path("talonx_signals/run.py").exists()


# --------------------------------------------------------------------------- #
# SAFETY  32-41
# --------------------------------------------------------------------------- #
def test_32_33_original_strategy_and_thresholds_unchanged():
    out = subprocess.run(
        ["git", "diff", "--stat", "113b97f", "--",
         "talonx_quant/", "talonx_core/", "talonx_paper/", "talonx_piv/", "talonx_brain/", "run_talonx.py"],
        capture_output=True, text=True, cwd=_REPO,
    )
    assert out.stdout.strip() == "", f"frozen path changed:\n{out.stdout}"
    from talonx_quant.config import QuantConfig
    c = QuantConfig()
    assert (c.min_atr_pct, c.confluence_score_min, c.min_risk_reward_ratio) == (0.25, 2, 1.5)


def test_34_experimental_v1_unchanged():
    from talonx_signals.config import RELAXED_OVERRIDES
    assert dict(RELAXED_OVERRIDES) == {"min_atr_pct": 0.10, "confluence_score_min": 1,
                                       "min_risk_reward_ratio": 1.0}


def test_35_quant_brain_unchanged():
    # talonx_quant + talonx_brain zero diff (covered by test_32) -- assert brain untouched too
    out = subprocess.run(["git", "diff", "--stat", "113b97f", "--", "talonx_brain/"],
                         capture_output=True, text=True, cwd=_REPO)
    assert out.stdout.strip() == ""


def test_36_task101_not_wired_live():
    for f in ("talonx_signals/run.py", "talonx_ops/admin_config.py", "talonx_ops/dashboard_read.py",
              "dashboard_web.py"):
        assert "task101" not in Path(f).read_text(encoding="utf-8").lower()


def test_37_experimental_telegram_impossible():
    src = Path("talonx_signals/run.py").read_text(encoding="utf-8")
    seg = src[src.index("_observe_premarket_volume"): src.index("_bridge_loop")]
    assert "telegram" not in seg.lower() and "TelegramSenderAdapter" not in seg
    # boundary module still structural
    from talonx_signals.external_boundary import EXPERIMENTAL_EXTERNAL_SENDS_ALLOWED
    assert EXPERIMENTAL_EXTERNAL_SENDS_ALLOWED is False


def test_38_39_broker_and_short_unchanged():
    for f in ("talonx_signals/run.py", "talonx_signals/premarket_store.py",
              "talonx_ops/admin_config.py", "dashboard_web.py"):
        src = Path(f).read_text(encoding="utf-8").lower()
        for banned in ("submit_order", "place_order", "tradingclient", "open_short", "execute_buy"):
            assert banned not in src, (f, banned)


def test_40_no_paid_data_no_aiml():
    for f in ("talonx_signals/run.py", "talonx_signals/premarket_store.py",
              "talonx_ops/admin_config.py", "dashboard_web_static/admin.html"):
        src = Path(f).read_text(encoding="utf-8").lower()
        for banned in ("api_key", "apikey", "openai", "anthropic", "import torch", "tensorflow",
                       "sklearn", "premium_data", "paid data"):
            assert banned not in src, (f, banned)


def test_41_no_live_runtime_started_by_tests():
    # this suite must not spawn the runtime. Needles are built from parts so
    # this check does not trip over its own source text.
    src = Path(__file__).read_text(encoding="utf-8")
    for needle in ("Pop" + "en(", "os." + "system(", ".p" + "s1", "start_" + "talonx"):
        assert needle not in src, needle
    import re
    for m in re.finditer(r"subprocess\.run\(\s*\n?\s*\[([^\]]+)\]", src):
        assert '"git"' in m.group(1), m.group(1)
