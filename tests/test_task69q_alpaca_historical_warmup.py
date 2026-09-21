"""Task 69Q Part 9 -- prototype Alpaca historical-warmup fetch (not wired
into the live warmup path; see production_readiness_gaps.json PRG-07)."""
from __future__ import annotations

from talonx_piv.alpaca_historical_warmup import fetch_1m_bars


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body


class Transport:
    def __init__(self, body, status=200, expected_feed=None):
        self._body, self._status, self._expected_feed = body, status, expected_feed
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw.get("params")))
        if self._expected_feed is not None:
            assert kw["params"]["feed"] == self._expected_feed
        return Response(self._body, self._status)


def test_fetch_1m_bars_parses_alpaca_bar_schema():
    body = {"bars": [
        {"t": "2026-08-24T13:30:00Z", "o": 100.0, "h": 101.0, "l": 99.5, "c": 100.5, "v": 1000},
        {"t": "2026-08-24T13:31:00Z", "o": 100.5, "h": 101.5, "l": 100.0, "c": 101.0, "v": 800},
    ]}
    transport = Transport(body)
    bars = fetch_1m_bars(transport, "https://data.alpaca.markets", "key", "secret", "AAPL", "start", "end")
    assert len(bars) == 2
    assert bars[0].close == 100.5
    assert bars[0].timestamp.isoformat() == "2026-08-24T13:30:00+00:00"


def test_fetch_1m_bars_uses_iex_feed_not_sip_by_default():
    transport = Transport({"bars": []}, expected_feed="iex")
    fetch_1m_bars(transport, "https://data.alpaca.markets", "key", "secret", "AAPL", "start", "end")
    assert transport.calls[0][1]["feed"] == "iex"


def test_fetch_1m_bars_fails_closed_on_non_200():
    transport = Transport({}, status=403)
    bars = fetch_1m_bars(transport, "https://data.alpaca.markets", "key", "secret", "AAPL", "start", "end")
    assert bars == []


def test_fetch_1m_bars_skips_rows_missing_timestamp():
    body = {"bars": [{"o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]}
    transport = Transport(body)
    bars = fetch_1m_bars(transport, "https://data.alpaca.markets", "key", "secret", "AAPL", "start", "end")
    assert bars == []
