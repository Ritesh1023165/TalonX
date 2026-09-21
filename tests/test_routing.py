"""
Task 131 Remediation Directive 1 -- ``RoutingDecision.to_dict()`` regression
tests. The reviewed method lives in ``talonx_ops.official_dispatch``
(there is no separate ``routing.py`` module in this repo -- the remediation
request named the routing/dispatch module informally; this file is placed
at the exact path requested).

The real defect: a prior edit inserted ``broad_discovery_dispatch_enabled()``
directly above ``to_dict()`` without correcting its indentation, leaving
``to_dict`` as dead code nested INSIDE ``broad_discovery_dispatch_enabled``
(unreachable, never callable as ``RoutingDecision(...).to_dict()``) rather
than a method of the class. Not a SyntaxError (the file still imported and
ran) -- a silent, structural bug: any caller of ``.to_dict()`` would raise
``AttributeError``. These tests exercise ``.to_dict()`` directly across
every feature-toggle combination so a regression of this kind fails loudly.
"""
from __future__ import annotations

import pytest

from talonx_ops.official_dispatch import (
    ORIGIN_BROAD_DISCOVERY,
    ORIGIN_PRODUCT_WATCHLIST,
    OfficialExternalRouter,
    RoutingDecision,
    broad_discovery_dispatch_enabled,
)


def _router():
    return OfficialExternalRouter(delivered_probe=lambda fam, key: False)


def test_to_dict_is_a_real_bound_method_not_dead_code():
    # the defect this test exists to catch: to_dict must be reachable as an
    # instance method, not merely present as unreachable source text.
    rd = RoutingDecision(family="insider_buy_cluster_v2", eligible=True,
                         already_delivered=False, path="official_telegram", reason="r")
    assert callable(getattr(rd, "to_dict", None))
    d = rd.to_dict()
    assert isinstance(d, dict)


def test_to_dict_shape_is_complete():
    rd = RoutingDecision(family="insider_buy_cluster_v2", eligible=True,
                         already_delivered=False, path="official_telegram", reason="ok",
                         origin=ORIGIN_PRODUCT_WATCHLIST)
    assert rd.to_dict() == {
        "family": "insider_buy_cluster_v2", "eligible": True, "already_delivered": False,
        "path": "official_telegram", "reason": "ok", "should_send": True,
        "origin": ORIGIN_PRODUCT_WATCHLIST,
    }


@pytest.mark.parametrize("ingest_flag,dispatch_flag", [
    ("", ""), ("true", ""), ("", "true"), ("true", "true"),
])
def test_to_dict_works_across_every_toggle_combination(monkeypatch, ingest_flag, dispatch_flag):
    if ingest_flag:
        monkeypatch.setenv("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", ingest_flag)
    else:
        monkeypatch.delenv("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", raising=False)
    if dispatch_flag:
        monkeypatch.setenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", dispatch_flag)
    else:
        monkeypatch.delenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", raising=False)

    router = _router()
    for origin in (ORIGIN_PRODUCT_WATCHLIST, ORIGIN_BROAD_DISCOVERY):
        rd = router.decide("insider_buy_cluster_v2", "dedup", origin=origin)
        d = rd.to_dict()
        assert set(d) == {"family", "eligible", "already_delivered", "path", "reason",
                          "should_send", "origin"}
        assert d["origin"] == origin
        assert isinstance(d["eligible"], bool)

    # experimental family: to_dict must still work even when not eligible
    d2 = router.decide("experimental_relaxed_v1", "dedup").to_dict()
    assert d2["eligible"] is False
    assert d2["should_send"] is False


def test_broad_discovery_toggle_itself_still_a_plain_function(monkeypatch):
    # guards against a REPEAT of the exact defect: broad_discovery_dispatch_
    # enabled must remain a standalone function, never re-acquire a nested
    # def inside it.
    monkeypatch.delenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", raising=False)
    assert broad_discovery_dispatch_enabled() is False
    monkeypatch.setenv("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", "true")
    assert broad_discovery_dispatch_enabled() is True
    import inspect
    src = inspect.getsource(broad_discovery_dispatch_enabled)
    assert "def to_dict" not in src
