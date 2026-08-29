"""Task 83 §4 -- the Streamlit dashboard's read-only PIV & Comparison
section.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Streamlit rendering itself is not
unit-tested here (consistent with tests/test_dispatch_app_funnel.py); the
non-Streamlit payload builder and the section's source are.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from talonx_compare.collector import ComparisonCollector
from talonx_compare.config import CompareConfig
from talonx_compare.dashboard_views import streamlit_piv_comparison_payload
from talonx_compare.testing import write_piv_state

DATE = "2026-08-28"
APP_PATH = Path(__file__).resolve().parent.parent / "talonx_dispatch" / "app.py"


def _payload(tmp_path, with_evidence=True):
    piv = tmp_path / "piv"
    write_piv_state(
        piv,
        freshness={"provider_state": "HEALTHY", "symbols": {"AAPL": "FRESH", "MSFT": "STALE"}},
        readiness={"session_date": DATE, "finalized": {"AAPL": {"status": "READY"}}},
        reconciliation={"complete": True, "consistent": True},
        shadow={"sh_d1": {"decision_id": "d1", "symbol": "AAPL", "status": "OPEN",
                          "filled_at": f"{DATE}T14:10:00+00:00"}},
        eod={"status": "PASSED", "trading_date_et": DATE},
    )
    cfg = CompareConfig(state_dir=tmp_path / "cs", evidence_root=tmp_path / "ev", piv_state_dir=piv)
    if with_evidence:
        ComparisonCollector(cfg).collect_once()
    return streamlit_piv_comparison_payload(config=cfg, piv_state_dir=piv), cfg


# --- 4.1 existing sections preserved -------------------------------------

def test_existing_sections_intact():
    src = APP_PATH.read_text(encoding="utf-8")
    for existing in ("\\U0001F4C8 Intraday Monitor", "\\U0001F48E Long-Term Radar",
                     "\\U0001F4CA Daily Funnel & Metrics", "⚙️ Watchlist & Settings"):
        assert existing in src, existing
    # the four original render functions are still defined
    tree = ast.parse(src)
    defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for fn in ("render_metrics", "render_alert_history", "render_feed", "render_paper_trading",
               "render_daily_funnel_metrics", "render_ticker_watchlist",
               "render_paper_trading_settings"):
        assert fn in defs, fn
    assert "render_piv_comparison" in defs


def test_piv_comparison_section_is_wired_into_the_radio():
    src = APP_PATH.read_text(encoding="utf-8")
    assert "PIV & Comparison" in src
    assert "render_piv_comparison()" in src


# --- 4.2 section panels ------------------------------------------------

def test_piv_comparison_section_panels(tmp_path):
    payload, _ = _payload(tmp_path)
    for key in ("available_dates", "selected_date", "archived_funnels", "live_quant_funnel",
                "readiness_freshness_exclusions", "decisions_and_reason_codes",
                "notification_and_lifecycle", "outcomes_by_execution_class",
                "eod_reconciliation", "divergence_table", "per_stage_totals",
                "source_health", "archive_integrity", "capability_limitations",
                "unresolved_questions"):
        assert key in payload, key
    assert payload["strategy_approval_status"] == "UNVALIDATED"
    assert payload["profitability"] == "UNDETERMINED"


# --- 4.3 date/session selection ------------------------------------

def test_date_session_selection(tmp_path):
    payload, cfg = _payload(tmp_path)
    assert payload["selected_date"] == DATE
    assert DATE in payload["available_dates"]
    # explicit selection of a specific date is honoured
    again = streamlit_piv_comparison_payload(config=cfg, piv_state_dir=cfg.piv_state_dir,
                                             trading_date=DATE)
    assert again["selected_date"] == DATE


# --- 4.4 outcomes separated by execution class -------------------

def test_outcomes_separated_by_execution_class(tmp_path):
    payload, _ = _payload(tmp_path)
    obc = payload["outcomes_by_execution_class"]
    assert set(obc) >= {"SIMULATED_PAPER", "PIV_SHADOW", "PIV_PAPER", "EXPERIMENTAL"}
    assert "never summed" in obc["note"]
    # they are distinct objects, not one merged number
    assert obc["PIV_SHADOW"] is not obc["PIV_PAPER"]


# --- 4.5 archive-integrity + source-health diagnostics --------

def test_archive_integrity_diagnostics(tmp_path):
    payload, cfg = _payload(tmp_path)
    assert payload["archive_integrity"]["file_hashes_ok"] is True
    # tamper with an evidence file -> integrity check must flag it
    (cfg.evidence_root / DATE / "comparison.json").write_text("{}", encoding="utf-8")
    tampered = streamlit_piv_comparison_payload(config=cfg, piv_state_dir=cfg.piv_state_dir,
                                                trading_date=DATE)
    assert tampered["archive_integrity"]["file_hashes_ok"] is False
    assert tampered["archive_integrity"]["problems"]


def test_not_run_state_is_honest_when_no_evidence(tmp_path):
    payload, _ = _payload(tmp_path, with_evidence=False)
    assert payload["available_dates"] == []
    assert payload["archive_health"]["state"] in ("NOT_RUN", "MISSING")


# --- 4.6 no control widgets --------------------------------------

def test_no_control_widgets_in_piv_comparison_section():
    """render_piv_comparison must not call any Streamlit widget that
    mutates state or triggers an action -- only read-only display
    widgets."""
    src = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "render_piv_comparison")
    called = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "st":
            called.add(node.func.attr)
    forbidden = {"button", "form", "form_submit_button", "download_button", "file_uploader",
                 "text_input", "number_input", "checkbox", "toggle", "slider", "text_area",
                 "chat_input", "data_editor", "camera_input", "color_picker"}
    assert not (called & forbidden), f"forbidden control widgets: {called & forbidden}"
    # selectbox for date choice is allowed (it only picks which archived
    # date to VIEW -- it changes nothing in Original or PIV)
    assert "selectbox" in called
    allowed = {"subheader", "caption", "selectbox", "columns", "metric", "markdown",
               "dataframe", "json", "write", "info", "divider"}
    assert called <= allowed, f"unexpected st.* calls: {called - allowed}"


def test_no_piv_activation_or_broker_or_approval_language_as_control():
    """No PIV activation / broker execution / experimental authorization /
    safety override / strategy-approval CONTROL in the section source."""
    src = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "render_piv_comparison")
    fn_src = ast.get_source_segment(src, fn).lower()
    # these words may appear as read-only *labels*; what must be absent is
    # a mutating call. Assert no assignment to / call of an approval flag.
    for banned_call in ("submit_order", "order_intent", "set_strategy_status", "approve",
                        "enable_experimental", "activate", "kill_switch", "st.button"):
        assert banned_call not in fn_src, banned_call
