"""
Task 117 Phase 0 F2 -- daily-bar pricing adapter mechanism.

The live V2 companion currently depends only on a static CSV directory
(newest bar 2026-08-14) -> any fresh cluster with an entry session after
that date gets SKIPPED_NO_ENTRY_BAR.  ``talonx_v2.pricing`` adds a
swappable adapter with strict bar validation, PROVISIONAL/FINAL
distinction, explicit unavailability reasons, and a composite
history+live layout.

These tests exercise the MECHANISM only.  The live companion default
stays ``csv`` (frozen-conformant); the IEX tail is NON_CONFORMANT vs the
Alpaca-SIP contract and is not wired in.  No network here.
"""
from __future__ import annotations

from datetime import date

import pytest

from talonx_v2.pricing import (Bar, CompositeBarAdapter, PriceUnavailable,
                               PricingResolver, make_resolver, validate_bar)

TODAY = date(2026, 9, 9)


class _MemAdapter:
    def __init__(self, name, rows_by_sym):
        self.name = name
        self._rows = rows_by_sym

    def history(self, symbol):
        return list(self._rows.get(symbol, []))

    def session(self, symbol, session):
        s = session.isoformat()
        return next((r for r in self._rows.get(symbol, []) if r["date"] == s), None)


def _row(d, o=100.0, c=101.0, v=1_000_000):
    return {"date": d, "open": o, "close": c, "volume": v}


# --------------------------------------------------------------------------- #
# validate_bar
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,want,reason", [
    ({"date": "2026-09-08", "open": 0, "close": 10, "volume": 5},
     "2026-09-08", "REJECTED_NONFINITE_OR_NONPOSITIVE_PRICE"),
    ({"date": "2026-09-08", "open": -1, "close": 10, "volume": 5},
     "2026-09-08", "REJECTED_NONFINITE_OR_NONPOSITIVE_PRICE"),
    ({"date": "2026-09-08", "open": float("nan"), "close": 10, "volume": 5},
     "2026-09-08", "REJECTED_NONFINITE_OR_NONPOSITIVE_PRICE"),
    ({"date": "2026-09-08", "open": 10, "close": 10, "volume": -3},
     "2026-09-08", "REJECTED_BAD_VOLUME"),
    ({"date": "2026-09-07", "open": 10, "close": 10, "volume": 5},
     "2026-09-08", "REJECTED_WRONG_SESSION_2026-09-07"),
    ({"date": "", "open": 10, "close": 10, "volume": 5}, "2026-09-08", "REJECTED_NO_DATE"),
    ({"date": "2026-09-20", "open": 10, "close": 10, "volume": 5},
     "2026-09-20", "FUTURE_SESSION"),
])
def test_validate_bar_rejections(raw, want, reason):
    out = validate_bar(raw, symbol="X", want_session=want, today=TODAY, source="t")
    assert isinstance(out, PriceUnavailable) and out.reason == reason


def test_validate_bar_today_is_provisional():
    out = validate_bar(_row("2026-09-09"), symbol="X", want_session="2026-09-09",
                       today=TODAY, source="t")
    assert isinstance(out, Bar) and out.status == "PROVISIONAL"


def test_validate_bar_past_is_final():
    out = validate_bar(_row("2026-09-08"), symbol="X", want_session="2026-09-08",
                       today=TODAY, source="t")
    assert isinstance(out, Bar) and out.status == "FINAL"


# --------------------------------------------------------------------------- #
# PricingResolver
# --------------------------------------------------------------------------- #
def _resolver(rows):
    r = PricingResolver(adapter=_MemAdapter("mem", rows))
    r.today = lambda: TODAY
    return r


def test_resolver_missing_bar_is_no_bar():
    r = _resolver({"X": [_row("2026-09-04")]})
    out = r.resolve("X", date(2026, 9, 8))
    assert isinstance(out, PriceUnavailable) and out.reason == "NO_BAR"
    assert r.price_lookup("X", date(2026, 9, 8)) is None


def test_resolver_future_session_blocked():
    r = _resolver({"X": [_row("2026-09-08")]})
    out = r.resolve("X", date(2026, 9, 15))
    assert isinstance(out, PriceUnavailable) and out.reason == "FUTURE_SESSION"


def test_resolver_today_bar_is_provisional_only():
    r = _resolver({"X": [_row("2026-09-09")]})
    out = r.resolve("X", date(2026, 9, 9))
    assert isinstance(out, PriceUnavailable) and out.reason == "PROVISIONAL_ONLY"
    assert r.price_lookup("X", date(2026, 9, 9)) is None


def test_resolver_final_bar_returns_prices():
    r = _resolver({"X": [_row("2026-09-08", o=50.0, c=52.0, v=2_000_000)]})
    px = r.price_lookup("X", date(2026, 9, 8))
    assert px == {"open": 50.0, "close": 52.0, "volume": 2_000_000}


def test_bars_lookup_excludes_provisional_today():
    rows = {"X": [_row("2026-09-07"), _row("2026-09-08"), _row("2026-09-09")]}
    r = _resolver(rows)
    got = r.bars_lookup("X")
    assert [b["date"] for b in got] == ["2026-09-07", "2026-09-08"]  # no 09-09 leak


# --------------------------------------------------------------------------- #
# composite
# --------------------------------------------------------------------------- #
def test_composite_prefers_history_then_live_tail():
    hist = _MemAdapter("hist", {"X": [_row("2026-08-12"), _row("2026-08-13")]})
    live = _MemAdapter("live", {"X": [_row("2026-08-13", c=999.0), _row("2026-09-08", c=77.0)]})
    comp = CompositeBarAdapter(hist, live)
    h = comp.history("X")
    assert [b["date"] for b in h] == ["2026-08-12", "2026-08-13", "2026-09-08"]
    # 08-13 came from history, not the live duplicate
    assert next(b for b in h if b["date"] == "2026-08-13")["close"] == 101.0
    # recent tail only from live
    assert comp.session("X", date(2026, 9, 8))["close"] == 77.0


def test_make_resolver_default_is_csv_conformant(tmp_path):
    r = make_resolver(mode="csv", bar_dirs=[str(tmp_path)])
    assert r.adapter.name.startswith("csv:")


def test_make_resolver_composite_iex_is_labelled_nonconformant(tmp_path):
    r = make_resolver(mode="composite-iex", bar_dirs=[str(tmp_path)])
    assert "NON_CONFORMANT" in r.adapter.name and "iex" in r.adapter.name


def test_make_resolver_rejects_unknown_mode(tmp_path):
    with pytest.raises(ValueError):
        make_resolver(mode="bloomberg", bar_dirs=[str(tmp_path)])
