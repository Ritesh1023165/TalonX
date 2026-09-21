"""
Task 131 Directive 5 -- the BROAD_DISCOVERY dispatch toggle in
``OfficialExternalRouter`` / ``talonx_v2.delivery.deliver_outbox``.

A BROAD_DISCOVERY-origin alert needs its OWN explicit external-send gate
(TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY), independent of the ingestion-side
toggle (Directive 4) and independent of V2Service's own execution_allowlist
-- defense in depth. Unset/false (the default) must not change existing
routing for any PRODUCT_WATCHLIST-origin alert.
"""
from __future__ import annotations

from talonx_ops.official_dispatch import (
    ORIGIN_BROAD_DISCOVERY,
    ORIGIN_PRODUCT_WATCHLIST,
    OfficialExternalRouter,
    broad_discovery_dispatch_enabled,
)


def _router():
    return OfficialExternalRouter(delivered_probe=lambda fam, key: False)


def test_default_origin_is_unaffected_and_unchanged(monkeypatch):
    monkeypatch.delenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", raising=False)
    rd = _router().decide("insider_buy_cluster_v2", "dedup1")
    assert rd.eligible is True
    assert rd.origin == ORIGIN_PRODUCT_WATCHLIST


def test_broad_discovery_origin_held_when_toggle_off(monkeypatch):
    monkeypatch.delenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", raising=False)
    assert broad_discovery_dispatch_enabled() is False
    rd = _router().decide("insider_buy_cluster_v2", "dedup1", origin=ORIGIN_BROAD_DISCOVERY)
    assert rd.eligible is False
    assert "BROAD_DISCOVERY" in rd.reason
    assert rd.origin == ORIGIN_BROAD_DISCOVERY


def test_broad_discovery_origin_eligible_when_toggle_on(monkeypatch):
    monkeypatch.setenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", "true")
    assert broad_discovery_dispatch_enabled() is True
    rd = _router().decide("insider_buy_cluster_v2", "dedup1", origin=ORIGIN_BROAD_DISCOVERY)
    assert rd.eligible is True
    assert rd.origin == ORIGIN_BROAD_DISCOVERY


def test_experimental_family_still_ineligible_regardless_of_origin(monkeypatch):
    monkeypatch.setenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", "true")
    rd = _router().decide("experimental_relaxed_v1", "dedup1", origin=ORIGIN_BROAD_DISCOVERY)
    assert rd.eligible is False
    assert "internal-only" in rd.reason


def test_deliver_outbox_tags_origin_by_symbol(monkeypatch, tmp_path):
    monkeypatch.setenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", "true")
    from talonx_v2.delivery import DryRunTransport, deliver_outbox
    from talonx_v2.store import V2Store

    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    store.enqueue_alert(
        event_id="e1", episode_id="ep1", kind="ENTRY_FILL", action="BUY", symbol="NEWSYM",
        strategy_version="INSIDER_BUY_CLUSTER_V2@1", dedup_key="ep1:BUY:ENTRY_FILL",
        payload_text="test", provenance={},
    )
    store.enqueue_alert(
        event_id="e2", episode_id="ep2", kind="ENTRY_FILL", action="BUY", symbol="AAPL",
        strategy_version="INSIDER_BUY_CLUSTER_V2@1", dedup_key="ep2:BUY:ENTRY_FILL",
        payload_text="test", provenance={},
    )
    router = _router()
    summary = deliver_outbox(store, router=router, transport=DryRunTransport(),
                             broad_discovery_symbols=frozenset({"NEWSYM"}))
    assert summary["considered"] == 2
    # DryRunTransport always HOLDS (by design -- no real send this run); what
    # this test actually verifies is that the ROUTER did not additionally
    # reject the BROAD_DISCOVERY-origin row for identity/origin reasons --
    # both rows are held for the SAME transport-level reason, not a
    # BROAD_DISCOVERY-specific one.
    reasons = {r["symbol"]: r["last_error"] for r in store.all_outbox()}
    assert "BROAD_DISCOVERY" not in reasons["NEWSYM"]
    assert reasons["NEWSYM"] == reasons["AAPL"]
