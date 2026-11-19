"""Legacy cleanup for the continuous engine: retired Experimental lane + un-mixed Quant metrics (B9/B12/B13)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_17_retired_experimental_lane_absent_from_active_startup():
    from talonx_ops.supervisor import default_talonx_components
    specs = default_talonx_components(include_v2=True)
    argv = " ".join(" ".join(s.argv) for s in specs)
    assert "experimental" not in {s.name for s in specs}
    assert "talonx_signals.run" not in argv
    from talonx_opportunity.supervise import COMPONENTS
    assert not [c for c in COMPONENTS if "exp" in c.lower()]


def test_18_quant_metrics_not_mixed_across_lanes():
    src = (REPO / "talonx_dispatch" / "telegram_listener.py").read_text(encoding="utf-8")
    assert "likely never reached Brain" not in src
    assert "CONTROL" in src


# ------------------------------------------------------------------------------------------ yfinance incidents (B10)
def _yf():
    import talonx_ingest.market_data.yfinance_poll as mod
    from talonx_ingest.config import MarketDataConfig
    cfg = MarketDataConfig(yfinance_poll_interval_seconds=0.0, yfinance_backoff_base_seconds=0.0,
                           yfinance_backoff_max_seconds=0.0, yfinance_degraded_cycle_failure_rate=0.5,
                           yfinance_session_reset_after_failures=3)
    flushed = []

    class _Pub:
        async def incr_metric(self, client, counter, n):
            flushed.append((counter, n))
    return mod, mod.YFinancePoller(cfg, metrics_publisher=_Pub()), flushed


def test_upstream_throttle_is_one_incident_not_dozens_of_failures(monkeypatch):
    import asyncio
    mod, p, flushed = _yf()
    monkeypatch.setattr(mod, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    syms = [f"S{i}" for i in range(43)]

    def fetch(symbols):
        for s in symbols:
            p._classify_and_record(s, KeyError("currentTradingPeriod"))
            p._requests_failed += 1
        p.stop()
        return []
    monkeypatch.setattr(p, "_fetch_snapshots", fetch)

    async def _noop(e):
        return None
    asyncio.run(p.stream(syms, _noop))
    got = dict(flushed)
    assert got["provider_upstream_incidents"] == 1 and got["provider_throttle_incidents"] == 1
    assert got["provider_symbol_errors_in_incidents"] == 43
    assert "provider_requests_failed" not in got


def test_isolated_symbol_failure_stays_a_hard_failure(monkeypatch):
    import asyncio
    from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType
    from datetime import datetime, timezone
    mod, p, flushed = _yf()
    syms = ["A", "B", "C", "D"]

    def fetch(symbols):
        p._requests_failed += 1
        p.stop()
        return [MarketEvent(symbol=s, event_type=MarketEventType.BAR, source=DataSource.POLLING,
                            timestamp=datetime.now(timezone.utc), open=1, high=1, low=1, close=1, volume=1, raw={})
                for s in symbols[:3]]
    monkeypatch.setattr(p, "_fetch_snapshots", fetch)
    monkeypatch.setattr(mod, "is_premarket_window", lambda: True)

    async def _noop(e):
        return None
    asyncio.run(p.stream(syms, _noop))
    got = dict(flushed)
    assert got.get("provider_requests_failed") == 1 and "provider_upstream_incidents" not in got


# ------------------------------------------------------------------------------------------ Intelligence (B11)
class _Cfg:
    deliver_intelligence_cards = True
    dry_run_delivery = False
    deliver_cards_enforce_age_cutoff = True


class _Ev:
    def __init__(self, accepted):
        self.accepted_at_utc = accepted


def _engine(cfg):
    from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
    e = EnrichmentEngine.__new__(EnrichmentEngine)
    e.config = cfg
    return e


def test_stale_at_enqueue_uses_the_outbox_rule_and_only_when_enforced():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 9, 24, 4, 22, tzinfo=timezone.utc)
    e = _engine(_Cfg())
    old = _Ev(now - timedelta(hours=9))          # the Session-04 ORCL/NVDA case: 9 h > 6 h IMMEDIATE
    assert "IMMEDIATE cutoff" in e._stale_at_enqueue(old, "IMMEDIATE", now)
    assert e._stale_at_enqueue(old, "DIGEST", now) is None                         # 9 h <= 24 h: still fresh
    assert e._stale_at_enqueue(_Ev(now - timedelta(hours=1)), "IMMEDIATE", now) is None
    assert e._stale_at_enqueue(_Ev(None), "IMMEDIATE", now) is None                # no evidence -> outbox decides
    assert e._stale_at_enqueue(_Ev((now - timedelta(hours=9)).replace(tzinfo=None)), "IMMEDIATE", now) is None
    off = _Cfg()
    off.dry_run_delivery = True
    assert _engine(off)._stale_at_enqueue(old, "IMMEDIATE", now) is None           # nothing would expire it


def test_digest_disabled_is_visible(monkeypatch):
    from talonx_ops.intel_queue import digest_delivery_state, format_breakdown
    monkeypatch.delenv("TALONX_INTEL_DELIVER_DIGEST_ENABLED", raising=False)
    assert digest_delivery_state() == "DIGEST_DISABLED"
    b = {"LIVE_PENDING": 3, "LIVE_PENDING_BY_ROUTE": {"DIGEST": 3}, "LIVE_PENDING_OLDEST_MIN": 1.0,
         "LIVE_FAILED_24H": 0, "HELD": 0, "EXPIRED_24H": 0, "EXPIRED_ALL_TIME": 0, "SENT_1H": 0, "SENT_24H": 0,
         "LAST_SENT_UTC": None, "DIGEST_DELIVERY": digest_delivery_state()}
    assert any("DIGEST_DISABLED, 3 pending will not be sent" in x for x in format_breakdown(b))
    monkeypatch.setenv("TALONX_INTEL_DELIVER_DIGEST_ENABLED", "1")
    assert digest_delivery_state() == "ENABLED"


# ------------------------------------------------------------------------------------------ retired lane (B9)
def test_retired_experimental_does_not_degrade_health():
    from talonx_ops.supervisor import Supervisor, default_talonx_components
    sup = Supervisor(default_talonx_components(include_dashboard=False))
    h = sup.aggregate_health()
    assert h["experimental"] == "RETIRED" and h["forward_outcomes"] == "RETIRED"


def test_retired_lane_refuses_a_live_start():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "talonx_signals.run"], cwd=REPO, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 4 and "RETIRED" in r.stderr


def test_read_model_reports_experimental_retired():
    from talonx_ops.authoritative_read_model import AuthoritativeReadModel
    p = AuthoritativeReadModel(check_processes=False).experimental_producer()
    assert p["retired"] is True and p["status"] == "RETIRED" and p["live"] is False
