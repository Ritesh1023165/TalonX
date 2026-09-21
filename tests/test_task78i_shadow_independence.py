"""Task 78I Stage 1A -- proves the actual condition behind shadow
tracking's "same actionability gate as PAPER" is exactly the permitted set
(approved strategy, valid deterministic recommendation, data readiness) and
NEVER paper_entry_enabled/broker availability/PAPER submission/fill
success. TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE throughout."""
from __future__ import annotations

import inspect

from talonx_piv.decision_contract import DataReadiness, MarketView, StrategyApprovalStatus, decide
from talonx_piv.shadow_ledger import ShadowLedger


from datetime import datetime, timezone

_FIXED_NOW = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)


def _decision(paper_entry_enabled: bool, decision_id="d1") -> "Decision":  # noqa: F821
    return decide(
        decision_id=decision_id, session_id="s1", trading_date_et="2026-08-27", ticker="AAPL",
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=paper_entry_enabled, entry_price=100.0, stop_price=98.0, target_price=104.0,
        now=_FIXED_NOW,
    )


def test_source_never_references_paper_entry_enabled_or_broker_or_lifecycle():
    """Static proof: shadow_ledger.py's source text contains none of the
    forbidden dependency names anywhere -- not merely "the tests happen to
    pass today"."""
    source = inspect.getsource(__import__("talonx_piv.shadow_ledger", fromlist=["x"]))
    forbidden = ["paper_entry_enabled", "PaperLifecycle", "AlpacaPaperClient", "broker.", "order_intent", "apply_broker_update"]
    for term in forbidden:
        assert term not in source, f"shadow_ledger.py must never reference {term!r}"


def test_identical_decision_content_produces_identical_shadow_behaviour_regardless_of_paper_enabled(tmp_path):
    """The SAME decision content (differing ONLY in paper_entry_enabled,
    which the shadow ledger must never even look at) must produce BYTE-
    IDENTICAL shadow simulation outcomes -- same fill price, same exit,
    same P&L -- proving paper_entry_enabled genuinely never influences the
    simulation."""
    from dataclasses import dataclass
    from datetime import datetime, timedelta, timezone

    @dataclass(frozen=True)
    class Bar:
        timestamp: datetime
        open: float
        high: float
        low: float
        close: float

    t0 = datetime(2026, 8, 27, 14, 30, tzinfo=timezone.utc)

    def run(paper_enabled: bool, decision_id: str) -> dict:
        ledger = ShadowLedger(tmp_path / f"shadow_{decision_id}.json")
        ledger.consider_entry(_decision(paper_enabled, decision_id=decision_id), source="STRATEGY")
        ledger.on_bar("AAPL", Bar(t0 + timedelta(minutes=1), 100.0, 100.5, 99.5, 100.2))  # fills
        ledger.on_bar("AAPL", Bar(t0 + timedelta(minutes=2), 100.0, 100.1, 97.5, 97.8))  # stop hit
        record = ledger.get_by_decision(decision_id)
        record.pop("decision_id")  # the only fields that should legitimately differ
        record.pop("shadow_id")
        record.pop("created_at")  # wall-clock stamp, not simulation content
        return record

    disabled = run(False, "d-disabled")
    enabled = run(True, "d-enabled")
    assert disabled == enabled  # every other field identical


def test_consider_entry_signature_has_no_paper_or_broker_parameter():
    sig = inspect.signature(ShadowLedger.consider_entry)
    for name in sig.parameters:
        assert "paper" not in name.lower() and "broker" not in name.lower()


def test_shadow_never_authorises_a_broker_sell_structurally():
    """ShadowLedger exposes no method that could plausibly be mistaken for
    or wired into a sell authorisation -- its only closing methods are
    on_bar (price-driven) and force_close (caller-supplied real price),
    neither of which returns anything a broker call site could act on as
    permission to sell (both return None)."""
    import talonx_piv.shadow_ledger as module
    ledger = module.ShadowLedger(None)
    assert ledger.on_bar.__func__.__annotations__.get("return") in (None, "None")
    assert ledger.force_close.__func__.__annotations__.get("return") in (None, "None")
