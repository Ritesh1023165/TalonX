"""FINAL V2 RELEASE ACCEPTANCE -- representative end-to-end flows + the explicit release gate.

Every flow runs the REAL V2Service tick/pipeline/ledger against isolated temp DBs with:
  * a fake SIP endpoint (no network), the real ``AlpacaSipBarAdapter`` + calendar-aware finality,
  * a RecordingTransport / failing transport at the final Telegram boundary (no real send),
  * an isolated ops (Sentinel) outbox whose destinations are DISABLED (rows stay PENDING; nothing is sent).
An autouse fixture scrubs every Telegram/notify env var, so no destination can ever resolve.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import test_pq2a_corporate_actions as base
from talonx_v2 import calendar as v2cal, dividends as dv
from talonx_v2 import provider_contract as pc
from talonx_v2 import release_gate as rg
from talonx_v2.config import V2Config
from talonx_v2.corporate_actions import (
    CorporateActionGuard, StaticCorporateActionSource, make_dividend_event, make_split_event)
from talonx_v2.delivery import RecordingTransport
from talonx_v2.form4_source import from_rows
from talonx_v2.pricing import make_resolver
from talonx_v2.service import V2Service
from talonx_v2.sip_adapter import ProviderTimeout
from talonx_v2.store import V2Store
from talonx_ops.notify import OPERATIONS, TRADE_EVENT
from talonx_ops.notify.outbox import NotifyStore

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
ACT_FRI = date(2026, 8, 14)
ENTRY_MON = date(2026, 8, 17)                       # Session 1
EXIT_10TD = date(2026, 8, 31)                       # Session 11 counting entry as day 0 -> the +10 exit session
SYM = "AAA"


@pytest.fixture(autouse=True)
def _no_telegram_anywhere(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("TELEGRAM_", "TALONX_NOTIFY_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "1")


def clk(d: date, h=20, m=30) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ET).astimezone(UTC)


def t_of(s: date) -> str:
    return datetime(s.year, s.month, s.day, tzinfo=ET).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sipbar(s: date, o, c, v=1_000_000):
    return {"t": t_of(s), "o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1, "c": c, "v": v, "n": 10, "vw": o}


def history(entry=ENTRY_MON):
    return [sipbar(s, 100.0, 100.0) for s in [x for x in v2cal._sessions() if x < entry][-20:]]


class FakeSip:
    def __init__(self, bars, exc=None):
        self.bars, self.exc, self.calls = list(bars), exc, []

    def __call__(self, url, params):
        self.calls.append(dict(params))
        if self.exc:
            raise self.exc
        return {"bars": {params["symbols"]: list(self.bars)}, "next_page_token": None}


class _Router:
    def decide(self, family, dedup_key=""):
        class R:
            pass
        r = R()
        r.family, r.eligible, r.already_delivered, r.reason = family, family == "insider_buy_cluster_v2", False, "eligible"
        return r


def rows(sym=SYM, act=ACT_FRI):
    return [{"symbol": sym, "issuer_cik": sym + "_CIK", "owner_cik": o, "filing_date": act.isoformat(),
             "accession": f"a{o}", "transaction_value": 200000, "transaction_code": "P"} for o in ("o1", "o2")]


class Rig:
    def __init__(self, tmp: Path, *, bars=None, events=(), transport=None, deliver=True, exc=None, name="v"):
        self.tmp = tmp
        self.clock = {"now": clk(ACT_FRI)}
        self.fake = FakeSip(bars if bars is not None else history() + [sipbar(ENTRY_MON, 101.0, 102.0), sipbar(EXIT_10TD, 110.0, 110.0)], exc=exc)
        self.guard = CorporateActionGuard(StaticCorporateActionSource(list(events)), cache_ttl_s=0)
        self.transport = transport or RecordingTransport()
        self.ops = NotifyStore(str(tmp / f"{name}_notify.db"))
        self.db = str(tmp / f"{name}.db")
        cfg = V2Config(db_path=self.db, starting_cash_usd=100_000.0, campaign_id=rg.RELEASE_PROFILE.campaign_id)
        self.svc = V2Service(config=cfg, bar_dirs=[tmp], form4_kind="parquet", status_path=str(tmp / f"{name}_s.json"),
                             router=_Router(), transport=self.transport, deliver=deliver, pricing_mode="sip",
                             corporate_actions=self.guard, release_mode=True, ops_notify_store=self.ops)
        self.svc._resolver = make_resolver(mode="sip", bar_dirs=[], today=lambda: self.svc._as_of_holder["d"] or ACT_FRI,
                                           now=lambda: self.clock["now"], sip_http_get=self.fake, ca_source=self.guard)
        self.svc._records = lambda *, as_of: from_rows(rows())

    def tick(self, d: date, h=20, m=30) -> dict:
        self.clock["now"] = clk(d, h, m)
        return self.svc.tick(as_of=d)

    @property
    def store(self) -> V2Store:
        return V2Store(self.db, starting_cash=100_000.0, campaign_id=rg.RELEASE_PROFILE.campaign_id)

    def ops_rows(self, dest=OPERATIONS):
        return self.ops.all_outbox(destination=dest)


def entered_rig(tmp, **kw) -> Rig:
    r = Rig(tmp, **kw)
    r.tick(ACT_FRI)
    r.tick(ENTRY_MON)
    assert len(r.store.open_positions()) == 1
    return r


# =========================================================================== #
# FLOW 1 -- normal trade, end to end
# =========================================================================== #
def test_flow1_normal_trade_intent_fill_hold_exit_settlement_total_return_and_operator_view(tmp_path):
    ex = v2cal.add_sessions(ENTRY_MON, 4)                                  # dividend ex-date inside the hold
    div = make_dividend_event(SYM, ex, "0.40", payable_date=EXIT_10TD + timedelta(days=4))   # paid AFTER the exit
    r = Rig(tmp_path, events=[div])
    # 1) evidence -> pre-open intent + durable Signal alert
    st = r.tick(ACT_FRI)
    assert st["entry_intents_created_this_tick"] == 1
    assert [x["kind"] for x in r.store.all_outbox()] == ["ENTRY_INTENT"]
    # 2) entry session: SIP open 101.00 -> whole-share sizing -> paper fill
    st = r.tick(ENTRY_MON)
    assert st["entries_this_tick"] == 1
    s = r.store
    pos = s.open_positions()[0]
    assert (pos["shares"], pos["entry_price"], pos["position_cost"]) == (99.0, 101.0, 9_999.0)   # floor(10000/101)
    assert s.cash() == 100_000.0 - 9_999.0
    assert s.all_entry_intents()[0]["status"] == "FILLED"
    prov = json.loads(pos["entry_price_provenance"])
    assert (prov["provider"], prov["feed"], prov["field"], prov["session"], prov["adjustment_state"], prov["contract"]) == (
        "alpaca:sip:1Day:adjustment=split", "sip", "open", ENTRY_MON.isoformat(), "SPLIT_ADJUSTED", "V2_RELEASE_PRICE_CONTRACT@1")
    kinds = [x["kind"] for x in s.all_outbox()]
    assert kinds == ["ENTRY_INTENT", "ENTRY_FILL"]
    assert all(x["destination"] == "TRADE_EVENT" for x in s.all_outbox())            # Signal
    assert len(r.transport.sent) >= 1                                                # delivered through the recording boundary
    # 3) hold: nothing happens mid-hold, no forced flatten
    mid = v2cal.add_sessions(ENTRY_MON, 5)
    st = r.tick(mid)
    assert st["exits_this_tick"] == 0 and st["eod_forced_flatten"] is False and len(r.store.open_positions()) == 1
    # 4) Session-10 exit at the SIP close 110.00
    st = r.tick(EXIT_10TD)
    assert st["exits_this_tick"] == 1
    s = r.store
    closed = s.all_positions()[0]
    assert closed["status"] == "CLOSED" and closed["exit_price"] == 110.0 and closed["exit_session"] == EXIT_10TD.isoformat()
    assert closed["realized_pnl_usd"] == pytest.approx(99 * 110.0 - 9_999.0)                # price P&L 891.00
    xprov = json.loads(closed["exit_price_provenance"])
    assert (xprov["field"], xprov["feed"], xprov["session"]) == ("close", "sip", EXIT_10TD.isoformat())
    assert [x["kind"] for x in s.all_outbox()][-1] == "EXIT_FILL"
    # dividend entitlement accrued at settlement, NOT yet cash (payable later)
    ent = s.dividend_entitlements()[0]
    assert (ent["state"], ent["eligible_qty"], ent["amount_usd"]) == ("ACCRUED", "99", 39.6)
    assert s.cash() == pytest.approx(100_000.0 + 891.0)
    # 5) payable date -> credited later; trade never reopened
    before = dict(s.all_positions()[0])
    r.tick(EXIT_10TD + timedelta(days=4))
    s = r.store
    assert s.dividends_credited_total() == 39.6 and s.cash() == pytest.approx(100_000.0 + 891.0 + 39.6)
    assert dict(s.all_positions()[0]) == before
    # 6) operator view (read-only): price P&L + dividend = total return, reconciles exactly
    from talonx_ops.paper_performance import build_v2_paper_performance
    perf = build_v2_paper_performance(Path(r.db))
    assert perf["reconciliation"]["status"] == "EXACT"
    ct = perf["closed_trades"][0]
    assert (ct["price_pnl_usd"], ct["dividend_pnl_usd"]) == (pytest.approx(891.0), pytest.approx(39.6))
    assert ct["total_return_pnl_usd"] == pytest.approx(930.6)
    assert perf["total_return_pnl"]["realized_price_plus_credited_dividends"] == pytest.approx(930.6)


# =========================================================================== #
# FLOW 2 -- missing entry price -> recovery -> Session-3 boundary
# =========================================================================== #
def test_flow2_missing_entry_price_recovers_within_session_3_and_never_after(tmp_path):
    s2, s3, s4 = (v2cal.add_sessions(ENTRY_MON, k) for k in (1, 2, 3))
    no_entry = history() + [sipbar(EXIT_10TD, 110.0, 110.0)]
    # (a) the Session-1 bar shows up only during Session 3 -> filled at SESSION 1's open
    r = Rig(tmp_path, bars=no_entry, name="a")
    r.tick(ACT_FRI)
    r.tick(ENTRY_MON); r.tick(s2)
    assert r.store.all_positions() == [] and len(r.store.pending_entry_intents()) == 1     # retained, no fill, no zero price
    r.fake.bars = history() + [sipbar(ENTRY_MON, 101.0, 102.0), sipbar(s2, 150.0, 150.0)]
    r.svc._resolver.adapter._cache.clear()
    r.tick(s3)
    pos = r.store.all_positions()[0]
    assert pos["entry_price"] == 101.0 and json.loads(pos["entry_price_provenance"])["session"] == ENTRY_MON.isoformat()
    # (b) the bar appears only AFTER Session 3 -> the window has closed: no fill, intent expires
    r2 = Rig(tmp_path, bars=no_entry, name="b")
    r2.tick(ACT_FRI); r2.tick(ENTRY_MON); r2.tick(s2); r2.tick(s3)
    r2.fake.bars = history() + [sipbar(ENTRY_MON, 101.0, 102.0)]
    r2.svc._resolver.adapter._cache.clear()
    r2.tick(s4)
    assert r2.store.all_positions() == [] and r2.store.cash() == 100_000.0
    assert r2.store.all_entry_intents()[0]["status"] != "FILLED"


# =========================================================================== #
# FLOW 3 -- missing exit close -> +5 recovery -> EXIT_UNRESOLVED
# =========================================================================== #
def test_flow3_missing_exit_close_recovers_in_plus_5_then_exit_unresolved_with_block_and_sentinel_event(tmp_path):
    bars = history() + [sipbar(ENTRY_MON, 101.0, 102.0)]
    r = Rig(tmp_path, bars=bars)
    r.tick(ACT_FRI); r.tick(ENTRY_MON)
    # target close missing; +1.. available? no -> hold through the window
    for k in range(0, 5):
        r.tick(v2cal.add_sessions(EXIT_10TD, k))
        assert r.store.all_positions()[0]["status"] == "OPEN"                    # still inside the +5 window
    r.tick(v2cal.add_sessions(EXIT_10TD, 5))
    pos = r.store.all_positions()[0]
    assert pos["status"] == "EXIT_UNRESOLVED" and pos["exit_price"] is None and pos["realized_pnl_usd"] is None
    assert [t["action"] for t in r.store.trades()] == ["BUY"]                      # no invented SELL, no stop, no zero
    assert r.store.n_open() == 1 and r.store.cash() == 100_000.0 - 9_999.0        # capacity + cost retained
    assert r.store.blocked_reason() is not None                                    # durable account block
    types = {x["event_type"] for x in r.ops_rows()}
    assert any("EXIT_UNRESOLVED" in t or "ACCOUNT_BLOCK" in t for t in types)     # Sentinel-owned event, PENDING (no send)
    # (a close arriving after +5 is never used)
    r.fake.bars = bars + [sipbar(v2cal.add_sessions(EXIT_10TD, 6), 200.0, 200.0)]
    r.svc._resolver.adapter._cache.clear()
    r.tick(v2cal.add_sessions(EXIT_10TD, 6))
    assert r.store.all_positions()[0]["status"] == "EXIT_UNRESOLVED"


def test_flow3b_exit_recovery_uses_the_earliest_eligible_close_within_plus_5(tmp_path):
    ff2 = v2cal.add_sessions(EXIT_10TD, 2)
    r = Rig(tmp_path, bars=history() + [sipbar(ENTRY_MON, 101.0, 102.0), sipbar(ff2, 120.0, 120.0)])
    r.tick(ACT_FRI); r.tick(ENTRY_MON)
    for k in (0, 1, 2):
        r.tick(v2cal.add_sessions(EXIT_10TD, k))
    pos = r.store.all_positions()[0]
    assert (pos["status"], pos["exit_session"], pos["exit_price"]) == ("CLOSED", ff2.isoformat(), 120.0)


# =========================================================================== #
# FLOW 4 -- split during hold
# =========================================================================== #
def test_flow4_split_during_hold_gives_correct_shares_basis_and_pnl(tmp_path):
    ex = v2cal.add_sessions(ENTRY_MON, 4)
    bars = history() + [sipbar(ENTRY_MON, 101.0, 102.0), sipbar(EXIT_10TD, 11.0, 11.0)]      # post-split basis at exit
    r = entered_rig(tmp_path, bars=bars, events=[make_split_event(SYM, ex, 10, 1)])
    r.tick(v2cal.add_sessions(ENTRY_MON, 6))                                                   # sweep applies the split
    assert r.store.effective_shares_exact(r.store.open_positions()[0]["position_id"]) == 990
    r.tick(EXIT_10TD)
    s = r.store
    pos = s.all_positions()[0]
    assert pos["status"] == "CLOSED" and pos["position_cost"] == 9_999.0 and pos["shares"] == 99.0   # entry row untouched
    assert [t for t in s.trades() if t["action"] == "SELL"][0]["shares"] == 990.0
    assert pos["realized_pnl_usd"] == pytest.approx(990 * 11.0 - 9_999.0)                     # +$891, not -$8,900
    assert pos["realized_pnl_usd"] > 0


# =========================================================================== #
# FLOW 5 -- dividend during hold (paid before exit -> credited at settlement tick)
# =========================================================================== #
def test_flow5_dividend_during_hold_accrues_at_settlement_and_credits_when_payable(tmp_path):
    ex = v2cal.add_sessions(ENTRY_MON, 3)
    div = make_dividend_event(SYM, ex, "0.50", payable_date=ex + timedelta(days=3))          # payable BEFORE the exit
    r = entered_rig(tmp_path, events=[div])
    r.tick(EXIT_10TD)
    s = r.store
    assert s.all_positions()[0]["status"] == "CLOSED"
    assert s.dividends_credited_total() == 49.5 and s.cash() == pytest.approx(100_000.0 + 891.0 + 49.5)
    # idempotent across more ticks
    for k in (1, 2):
        r.tick(v2cal.add_sessions(EXIT_10TD, k))
    assert r.store.dividends_credited_total() == 49.5 and len(r.store.dividend_entitlements()) == 1


# =========================================================================== #
# FLOW 6 -- provider outage: no fabricated trade/settlement, operational visibility
# =========================================================================== #
def test_flow6_provider_outage_never_fabricates_a_trade_or_settlement_and_is_visible(tmp_path):
    down = Rig(tmp_path, exc=ProviderTimeout("timeout"), name="down")
    down.tick(ACT_FRI); down.tick(ENTRY_MON)
    assert down.store.all_positions() == [] and down.store.cash() == 100_000.0
    st = json.loads((tmp_path / "down_s.json").read_text())
    assert st["pricing_unavailable_recent"] and any("PROVIDER_TIMEOUT" in x for x in st["pricing_unavailable_recent"])
    assert st["release_mode"] is True
    # outage during the hold: the open position is not settled on a made-up price, then settles when data returns
    r = entered_rig(tmp_path, name="hold")
    r.fake.exc = ProviderTimeout("timeout")
    r.svc._resolver.adapter._cache.clear()
    r.tick(EXIT_10TD)
    assert r.store.all_positions()[0]["status"] == "OPEN" and [t["action"] for t in r.store.trades()] == ["BUY"]
    r.fake.exc = None
    r.svc._resolver.adapter._cache.clear()
    r.tick(v2cal.add_sessions(EXIT_10TD, 1))
    pos = r.store.all_positions()[0]
    assert pos["status"] == "CLOSED" and pos["exit_price"] == 110.0                         # first eligible close, target session


# =========================================================================== #
# FLOW 7 -- Telegram failure: paper execution unaffected, durable retry
# =========================================================================== #
class _FailingTransport:
    name = "failing"

    def __init__(self):
        self.calls = 0

    def send(self, payload_text, *, meta):
        self.calls += 1
        return {"ok": False, "detail": "telegram 500"}


def test_flow7_telegram_failure_does_not_touch_paper_execution_and_state_is_durably_retryable(tmp_path):
    ft = _FailingTransport()
    r = Rig(tmp_path, transport=ft)
    r.tick(ACT_FRI); r.tick(ENTRY_MON)
    s = r.store
    assert len(s.open_positions()) == 1 and s.cash() == 100_000.0 - 9_999.0                   # execution unaffected
    by_kind = {x["kind"]: x for x in s.all_outbox()}
    assert ft.calls >= 1
    # the stale pre-open INSTRUCTION is never re-delivered as fresh; the fill notification stays durably RETRYable
    assert by_kind["ENTRY_INTENT"]["state"] == "EXPIRED"
    assert by_kind["ENTRY_FILL"]["state"] == "RETRY" and by_kind["ENTRY_FILL"]["attempts"] == 1
    assert by_kind["ENTRY_FILL"]["next_attempt_utc"] and "telegram 500" in by_kind["ENTRY_FILL"]["last_error"]
    # a working transport later drains the durable row exactly once; nothing lost, nothing duplicated, still no re-open of the trade
    from talonx_v2.delivery import deliver_outbox
    good = RecordingTransport()
    later = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    deliver_outbox(r.store, router=_Router(), transport=good, now=later)
    deliver_outbox(r.store, router=_Router(), transport=good, now=later + timedelta(hours=1))
    after = {x["kind"]: x for x in r.store.all_outbox()}
    assert after["ENTRY_FILL"]["state"] == "SENT" and after["ENTRY_INTENT"]["state"] == "EXPIRED"
    assert len(good.sent) == 1                                                                   # exactly one delivery
    assert len(r.store.open_positions()) == 1 and r.store.cash() == 100_000.0 - 9_999.0


# =========================================================================== #
# FLOW 8 -- restart: state, provenance and idempotency preserved
# =========================================================================== #
def test_flow8_restart_preserves_campaign_provenance_reservations_and_idempotency(tmp_path):
    ex = v2cal.add_sessions(ENTRY_MON, 3)                                                          # split ex-date
    dex = v2cal.add_sessions(ENTRY_MON, 6)                                                         # dividend ex-date (post-split shares)
    div = make_dividend_event(SYM, dex, "0.40", payable_date=EXIT_10TD + timedelta(days=2))
    r = entered_rig(tmp_path, events=[make_split_event(SYM, ex, 10, 1), div],
                    bars=history() + [sipbar(ENTRY_MON, 101.0, 102.0), sipbar(EXIT_10TD, 11.0, 11.0)])
    r.tick(v2cal.add_sessions(ENTRY_MON, 6))
    camp = r.store.campaign_identity()
    prov_before = r.store.open_positions()[0]["entry_price_provenance"]
    # ---- "restart": a brand-new service object on the SAME ledger, a fresh guard/provider ----
    r2 = Rig.__new__(Rig)
    r2.tmp, r2.clock, r2.fake = tmp_path, {"now": clk(v2cal.add_sessions(ENTRY_MON, 7))}, r.fake
    r2.guard = CorporateActionGuard(StaticCorporateActionSource([make_split_event(SYM, ex, 10, 1), div]), cache_ttl_s=0)
    r2.transport, r2.db = RecordingTransport(), r.db
    r2.ops = NotifyStore(str(tmp_path / "v_notify.db"))
    r2.svc = V2Service(config=V2Config(db_path=r.db, starting_cash_usd=100_000.0, campaign_id=rg.RELEASE_PROFILE.campaign_id), bar_dirs=[tmp_path], form4_kind="parquet",
                       status_path=str(tmp_path / "s2.json"), router=_Router(), transport=r2.transport, deliver=True,
                       pricing_mode="sip", corporate_actions=r2.guard, release_mode=True, ops_notify_store=r2.ops)
    r2.svc._resolver = make_resolver(mode="sip", bar_dirs=[], today=lambda: r2.svc._as_of_holder["d"] or ACT_FRI,
                                     now=lambda: r2.clock["now"], sip_http_get=r.fake, ca_source=r2.guard)
    r2.svc._records = lambda *, as_of: from_rows(rows())
    for k in (7, 8):                                                                            # repeated sweeps after restart
        r2.tick(v2cal.add_sessions(ENTRY_MON, k))
    s = r2.store
    pid = s.open_positions()[0]["position_id"]
    assert s.campaign_identity() == camp and s.cash() == 100_000.0 - 9_999.0                    # starting cash never reset
    assert s.effective_shares_exact(pid) == 990                                                # split NOT re-applied
    assert s.open_positions()[0]["entry_price_provenance"] == prov_before
    r2.tick(EXIT_10TD)
    r2.tick(EXIT_10TD + timedelta(days=2))
    r2.tick(EXIT_10TD + timedelta(days=3))
    s = r2.store
    assert s.dividends_credited_total() == 396.0 and len(s.dividend_entitlements()) == 1        # 990 x 0.40, credited once
    assert len([t for t in s.trades() if t["action"] == "SELL"]) == 1


# =========================================================================== #
# FLOW 9 -- account block: new admission denied, obligations still safe
# =========================================================================== #
def _second_issuer_admitted(tmp_path, *, block: bool, name: str):
    """Identical scenario +/- an active account block: AAA is entered; later a NEW qualifying issuer (CCC) fires."""
    r = entered_rig(tmp_path, name=name)
    if block:
        from talonx_ops import account_blocks
        with r.store.transaction() as c:
            account_blocks.record_block(c, account_id=r.store.account_id, reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                        reference="acceptance", detail="synthetic block")
        assert r.store.blocked_reason() is not None
    d2 = v2cal.add_sessions(ENTRY_MON, 2)                                    # CCC's activation session
    entry2 = v2cal.next_session_strictly_after(d2)
    r.fake.bars = history(entry2) + [sipbar(entry2, 50.0, 51.0), sipbar(EXIT_10TD, 110.0, 110.0)]
    r.svc._resolver.adapter._cache.clear()
    r.svc._records = lambda *, as_of: from_rows(rows() + rows("CCC", act=d2))
    r.tick(d2)
    r.tick(entry2)
    return r


def test_flow9_account_block_denies_new_admission_but_exits_and_obligations_still_settle(tmp_path):
    free = _second_issuer_admitted(tmp_path, block=False, name="free")
    assert any(p["symbol"] == "CCC" for p in free.store.all_positions())                      # control: without a block it IS admitted
    blocked = _second_issuer_admitted(tmp_path, block=True, name="blk")
    assert not any(p["symbol"] == "CCC" for p in blocked.store.all_positions())               # the block denies the new admission
    assert not any(i["symbol"] == "CCC" and i["status"] == "FILLED" for i in blocked.store.all_entry_intents())
    # obligations stay safe: the existing position's Session-10 exit still settles, cash is correct, the block persists
    blocked.fake.bars = history(ENTRY_MON) + [sipbar(ENTRY_MON, 101.0, 102.0), sipbar(EXIT_10TD, 110.0, 110.0)]
    blocked.svc._resolver.adapter._cache.clear()
    blocked.tick(EXIT_10TD)
    pos = [p for p in blocked.store.all_positions() if p["symbol"] == SYM][0]
    assert pos["status"] == "CLOSED" and pos["realized_pnl_usd"] == pytest.approx(891.0)
    assert blocked.store.blocked_reason() is not None                                         # cleared only by an audited clearance
    st = json.loads((tmp_path / "blk_s.json").read_text())
    assert "LEDGER_MISMATCH" in st["account_blocks_active"] and st["release_mode"] is True


# =========================================================================== #
# FLOW 10 -- release readiness (SIP contract verified, fingerprints match, Lab OFF)
# =========================================================================== #
class _Ready:
    def __init__(self, honour=True, exc=None):
        self.honour, self.exc, self.calls = honour, exc, 0

    def __call__(self, url, params):
        self.calls += 1
        if self.exc:
            raise self.exc
        if params["symbols"] == "AAPL":
            return {"bars": {"AAPL": [sipbar(date(2026, 10, 2), 300.0, 301.0, 50_000_000)]}}
        split = params["adjustment"] == "split" and self.honour
        o, c, v = (119.77, 120.89, 412_385_800) if split else (1197.7, 1208.88, 41_238_580)
        return {"bars": {"NVDA": [sipbar(date(2024, 6, 7), o, c, v)]}}


def good_env(tmp_path, validated=True, fname="validation.json"):
    env = {"APCA_API_KEY_ID": "k", "APCA_API_SECRET_KEY": "s",
           "TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN": "sig-token-SECRET", "TALONX_NOTIFY_TRADE_EVENT_CHAT_ID": "sig-chat-SECRET",
           "TALONX_NOTIFY_OPERATIONS_BOT_TOKEN": "sen-token-SECRET", "TALONX_NOTIFY_OPERATIONS_CHAT_ID": "sen-chat-SECRET"}
    env.update({"TALONX_V2_CAMPAIGN_ID": rg.RELEASE_PROFILE.campaign_id, "TALONX_V2_STARTING_CASH_USD": "100000",
                "TALONX_V2_ALLOCATION_USD": "10000", "TALONX_V2_EXECUTION_MODE": "PAPER",
                "TALONX_NOTIFY_DB_PATH": str(tmp_path / rg.RELEASE_PROFILE.notify_db_filename)})
    from talonx_ops.notify import resolve_destination_config
    from talonx_ops.operator_read import _destination_fingerprint
    for k, v in env.items():
        os.environ[k] = v
    try:
        fp = {d: _destination_fingerprint(resolve_destination_config(d)) for d in ("TRADE_EVENT", "OPERATIONS")}
    finally:
        for k in env:
            os.environ.pop(k, None)
    rec = {"schema_version": 1, "kind": "ri4_controlled_telegram_validation",
           "destinations": {d: {"state": "SENT" if validated else "PENDING", "configuration_fingerprint": fp[d]} for d in fp}}
    p = tmp_path / fname
    p.write_text(json.dumps(rec))
    return env, p


def gate(tmp_path, *, env=None, vpath=None, mode="sip", deliver=True, transport="telegram", http=None, db=None):
    if env is None:
        env, vpath = good_env(tmp_path)
    return rg.evaluate_release_readiness(db_path=db or (tmp_path / "none.db"), pricing_mode=mode, deliver=deliver,
                                         transport=transport, env=env, http_get=http or _Ready(),
                                         now=lambda: clk(date(2026, 10, 5)), validation_path=vpath)


def test_flow10_release_gate_ready_with_sip_contract_fingerprints_and_lab_off(tmp_path):
    rep = gate(tmp_path)
    by = {c.name: c for c in rep.checks}
    assert rep.status == "READY", [f"{c.name}: {c.detail}" for c in rep.failed]
    for name in ("release_pricing_mode", "provider_readiness", "provider_contract_fingerprint", "strategy_fingerprint",
                 "provider_semantics", "paper_only_frozen_contract", "signal_destination_configured",
                 "sentinel_destination_configured", "signal_sentinel_distinct", "lab_off",
                 "signal_delivery_validation_bound", "sentinel_delivery_validation_bound", "signal_delivery_enabled",
                 "account_blocks", "startup_reconciliation"):
        assert by[name].status == "PASS", (name, by[name].detail)
    assert "ac5e51aa3599d6c9" in by["provider_contract_fingerprint"].detail and "e2acf6454789217e" in by["strategy_fingerprint"].detail
    blob = json.dumps(rep.to_dict())
    for secret in ("SECRET", "sig-token", "sen-chat", "APCA"):                                    # no secret ever emitted
        assert secret not in blob


@pytest.mark.parametrize("mutate,failing", [
    (dict(mode="csv"), "release_pricing_mode"),
    (dict(mode="composite-yf"), "release_pricing_mode"),
    (dict(http=_Ready(honour=False)), "provider_readiness"),
    (dict(http=_Ready(exc=ProviderTimeout("t"))), "provider_readiness"),
    (dict(deliver=False), "signal_delivery_enabled"),
    (dict(transport="dryrun"), "signal_delivery_enabled"),
])
def test_flow10_release_gate_refuses_each_unsafe_configuration(tmp_path, mutate, failing):
    rep = gate(tmp_path, **mutate)
    assert rep.status == "NOT_READY" and failing in {c.name for c in rep.failed}


def test_flow10_gate_refuses_missing_credentials_unvalidated_or_changed_destinations_and_lab_on(tmp_path):
    env, vp = good_env(tmp_path)
    no_apca = {k: v for k, v in env.items() if not k.startswith("APCA")}
    assert "provider_readiness" in {c.name for c in gate(tmp_path, env=no_apca, vpath=vp).failed}
    env2, vp2 = good_env(tmp_path, validated=False, fname="unvalidated.json")
    assert {"signal_delivery_validation_bound", "sentinel_delivery_validation_bound"} <= {c.name for c in gate(tmp_path, env=env2, vpath=vp2).failed}
    changed = dict(env, TALONX_NOTIFY_OPERATIONS_CHAT_ID="a-different-chat")                      # credentials/chat changed after validation
    assert "sentinel_delivery_validation_bound" in {c.name for c in gate(tmp_path, env=changed, vpath=vp).failed}
    aliased = dict(env, TALONX_NOTIFY_OPERATIONS_BOT_TOKEN=env["TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN"],
                   TALONX_NOTIFY_OPERATIONS_CHAT_ID=env["TALONX_NOTIFY_TRADE_EVENT_CHAT_ID"])
    assert "signal_sentinel_distinct" in {c.name for c in gate(tmp_path, env=aliased, vpath=vp).failed}
    lab = dict(env, TALONX_NOTIFY_RESEARCH_ENABLED="1", TALONX_NOTIFY_RESEARCH_BOT_TOKEN="lab-token", TALONX_NOTIFY_RESEARCH_CHAT_ID="lab-chat")
    assert "lab_off" in {c.name for c in gate(tmp_path, env=lab, vpath=vp).failed}                # Lab must be OFF for release
    assert not [c for c in gate(tmp_path, env=dict(env, TALONX_NOTIFY_RESEARCH_ENABLED="0"), vpath=vp).failed]


def test_flow10_gate_reads_the_ledger_read_only_and_refuses_active_blocks_and_reconciliation_failures(tmp_path):
    r = entered_rig(tmp_path)
    ok = gate(tmp_path, db=r.db)
    assert ok.status == "READY", [f"{c.name}: {c.detail}" for c in ok.failed]
    camp = {c.name: c for c in ok.checks}["campaign_identity"]
    assert camp.status == "PASS" and "INSIDER_BUY_CLUSTER_V2@1" in camp.detail
    import hashlib
    h_before = hashlib.md5(Path(r.db).read_bytes()).hexdigest()
    gate(tmp_path, db=r.db)
    assert hashlib.md5(Path(r.db).read_bytes()).hexdigest() == h_before                          # the gate never mutates the ledger
    from talonx_ops import account_blocks
    with r.store.transaction() as c:
        account_blocks.record_block(c, account_id=r.store.account_id, reason_type=account_blocks.REASON_EXIT_UNRESOLVED,
                                    reference="1", detail="x")
    assert "account_blocks" in {c.name for c in gate(tmp_path, db=r.db).failed}
    con = sqlite3.connect(r.db)
    con.execute("UPDATE portfolio SET cash = cash - 500")                                       # break the cash equation
    con.commit(); con.close()
    assert "startup_reconciliation" in {c.name for c in gate(tmp_path, db=r.db).failed}


def test_release_mode_can_never_sit_on_the_stale_csv_default(tmp_path):
    with pytest.raises(ValueError):
        V2Service(config=V2Config(db_path=str(tmp_path / "x.db")), bar_dirs=[tmp_path], pricing_mode="csv",
                  corporate_actions=CorporateActionGuard(StaticCorporateActionSource([])), release_mode=True)
    with pytest.raises(ValueError):
        V2Service(config=V2Config(db_path=str(tmp_path / "y.db")), bar_dirs=[tmp_path], pricing_mode="sip", release_mode=True)
    assert rg.resolve_pricing_mode(None, release=True) == "sip" and rg.resolve_pricing_mode(None, release=False) == "csv"
    for bad in ("csv", "composite-yf", "composite-iex"):
        with pytest.raises(ValueError):
            rg.resolve_pricing_mode(bad, release=True)
    # research / replay defaults are NOT silently changed to SIP
    assert rg.resolve_pricing_mode("composite-yf", release=False) == "composite-yf"


def test_release_entry_points_refuse_csv_and_unready_configuration(tmp_path, monkeypatch):
    from talonx_v2 import run
    with pytest.raises(SystemExit) as ei:
        run.main(["--mode", "live", "--release", "--pricing-mode", "csv", "--db", str(tmp_path / "r.db")])
    assert "requires pricing mode 'sip'" in str(ei.value)
    with pytest.raises(SystemExit) as ei:
        run.main(["--mode", "replay", "--release", "--db", str(tmp_path / "r.db")])
    assert "only valid with --mode live" in str(ei.value)
    monkeypatch.setenv("APCA_API_KEY_ID", "k")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "s")
    monkeypatch.setattr(rg, "evaluate_release_readiness", lambda **kw: _NotReady())
    with pytest.raises(SystemExit) as ei:
        run.main(["--mode", "live", "--release", "--db", str(tmp_path / "r2.db"), "--deliver", "--transport", "telegram"])
    assert "NOT_READY" in str(ei.value) and "lab_off" in str(ei.value)
    from talonx_ops.prospective import proc
    with pytest.raises(ValueError):
        proc.start_stack(tmp_path, env={}, release=True, deliver=False)                          # release requires Signal delivery
    from talonx_ops.prospective.__main__ import main as pm
    assert callable(pm)


class _NotReady:
    status = "NOT_READY"
    failed = [rg.Check("lab_off", "FAIL", "Lab enabled")]
    checks = failed

    def to_dict(self):
        return {}


def test_operator_launcher_exposes_sip_and_release_and_keeps_the_csv_default_for_non_release():
    from talonx_ops.prospective import __main__ as m
    import argparse
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert '"sip"' in src and '"--release"' in src and "default=None" in src
    assert rg.RELEASE_PROFILE.launch_argv[:5] == ("python", "-m", "talonx_ops.prospective", "start", "--release")
    assert "--pricing-mode" not in rg.RELEASE_PROFILE.launch_argv                                # release implies SIP explicitly


# =========================================================================== #
# notification routing / Lab OFF / paper independence of Telegram / no secrets
# =========================================================================== #
def test_notification_routing_signal_for_trades_sentinel_for_operations_lab_off(tmp_path):
    from talonx_ops.notify import RESEARCH, resolve_destination_config, telegram_client_for
    bars = history() + [sipbar(ENTRY_MON, 101.0, 102.0)]                     # no exit bar -> EXIT_UNRESOLVED (an operational event)
    r = Rig(tmp_path, bars=bars)
    r.tick(ACT_FRI); r.tick(ENTRY_MON)
    for k in range(0, 6):
        r.tick(v2cal.add_sessions(EXIT_10TD, k))
    assert r.store.all_positions()[0]["status"] == "EXIT_UNRESOLVED"
    assert {x["destination"] for x in r.store.all_outbox()} == {TRADE_EVENT}                    # BUY/SELL lifecycle -> Signal
    ops = r.ops_rows(None)
    assert ops and {x["destination"] for x in ops} == {OPERATIONS}                              # operational/safety -> Sentinel ONLY
    assert not any(x["destination"] == "RESEARCH" for x in ops)
    assert not resolve_destination_config(RESEARCH).enabled and telegram_client_for(RESEARCH) is None   # Lab OFF, no fallback
    # each row has exactly one owner destination (no duplicate delivery owner)
    ids = [x["event_id"] for x in ops]
    assert len(ids) == len(set(ids))


def test_no_real_telegram_client_is_reachable_in_the_acceptance_environment():
    from talonx_ops.notify import DESTINATIONS, resolve_destination_config, telegram_client_for
    assert all(not resolve_destination_config(d).enabled for d in DESTINATIONS)
    assert all(telegram_client_for(d) is None for d in DESTINATIONS)


# =========================================================================== #
# /ping path (Signal / primary listener): reads the release state honestly
# =========================================================================== #
def _listener():
    from unittest.mock import AsyncMock, MagicMock
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.telegram_listener import TelegramReplyListener
    client = AsyncMock()
    client.is_configured = True
    return TelegramReplyListener(store=MagicMock(), config=DispatchConfig(telegram_bot_token="T", telegram_chat_id="1"),
                                 telegram_client=client)


def _ping_text(tmp_path, monkeypatch, status: dict | None):
    from talonx_dispatch.telegram_listener import TelegramReplyListener as L
    p = tmp_path / "st.json"
    if status is not None:
        p.write_text(json.dumps(status))
    monkeypatch.setattr(L, "_v2_status_path", staticmethod(lambda: p))
    monkeypatch.setattr(L, "_intel_heartbeat_path", staticmethod(lambda: tmp_path / "no_hb.json"))
    monkeypatch.setattr(L, "_intel_progress_path", staticmethod(lambda: tmp_path / "no_pr.json"))
    monkeypatch.setattr(L, "_intel_ledger_path", staticmethod(lambda: tmp_path / "no.db"))
    return "\n".join(_listener()._discovery_v2_section())


def test_ping_shows_release_provider_contract_campaign_blocks_and_unresolved_from_the_real_status_file(tmp_path, monkeypatch):
    r = entered_rig(tmp_path)
    status = json.loads((tmp_path / "v_s.json").read_text())
    text = _ping_text(tmp_path, monkeypatch, status)
    assert "Release mode: ON" in text
    assert "alpaca SIP adjustment=split | V2_RELEASE_PRICE_CONTRACT@1 (ac5e51aa3599d6c9) | fallback=NONE" in text
    assert "Campaign: V2-PAPER-RC1 (PAPER)" in text and "Account blocks: none" in text and "EXIT_UNRESOLVED: 0" in text
    assert "Open positions: 1" in text and "Market-data health:" in text


def test_ping_never_presents_stale_csv_as_the_release_provider(tmp_path, monkeypatch):
    csv_status = {"release_mode": False, "price_provider_contract": {"mode": "csv", "release_contract_active": False},
                  "campaign_id": "V2", "execution_mode": "PAPER", "cash": 1.0, "account_blocks_active": ["EXIT_UNRESOLVED"],
                  "exit_unresolved": [{"symbol": "X"}]}
    text = _ping_text(tmp_path, monkeypatch, csv_status)
    assert "Release mode: OFF" in text and "NOT the release contract (pricing mode csv) -- not release-grade" in text
    assert "V2_RELEASE_PRICE_CONTRACT" not in text and "Account blocks: EXIT_UNRESOLVED" in text and "EXIT_UNRESOLVED: 1" in text
    (tmp_path / "st.json").unlink()
    unknown = _ping_text(tmp_path, monkeypatch, None)
    assert "unknown" in unknown and "Release mode" not in unknown                                   # unavailable is 'unknown', never a claim
    import asyncio
    lst = _listener()
    assert callable(lst._handle_ping)


# =========================================================================== #
# operator / dashboard read-only + intraday isolation + claims
# =========================================================================== #
def test_operator_view_is_read_only_and_reports_campaign_capital_provenance_and_dividends(tmp_path):
    r = entered_rig(tmp_path)
    r.tick(EXIT_10TD)
    import hashlib
    h = lambda: hashlib.md5(Path(r.db).read_bytes()).hexdigest()   # noqa: E731
    before = h()
    from talonx_ops.operator_read import operator_snapshot
    snap = operator_snapshot(Path(r.db), status=json.loads((tmp_path / "v_s.json").read_text()))
    assert h() == before                                                                             # reading mutated nothing
    acct = snap["account"]
    assert acct["starting_capital"] == 100_000.0 and acct["settled_cash"] == pytest.approx(100_000.0 + 891.0)
    assert len(snap["positions"]["CLOSED"]) == 1 and len(snap["positions"]["EXIT_UNRESOLVED"]) == 0
    assert snap["reconciliation"]["state"] == "HEALTHY" and snap["blocks"] == []
    assert snap["campaign"]["strategy_version"] == "INSIDER_BUY_CLUSTER_V2@1" and snap["campaign"]["execution_mode"] == "PAPER"
    assert h() == before


def test_intraday_stays_research_only_and_outside_v2_campaign_totals(tmp_path, monkeypatch):
    r = entered_rig(tmp_path)
    con = sqlite3.connect(r.db)
    tables = {x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert not any(t.startswith(("paper_", "orders", "long_term", "experimental")) for t in tables)   # V2 ledger holds no intraday state
    from talonx_ops.notify import RESEARCH, telegram_client_for
    assert telegram_client_for(RESEARCH) is None                                                     # Original's uninjected push has no route
    st = json.loads((tmp_path / "v_s.json").read_text())
    assert st["real_capital"] is False and st["shorts"] is False and st["eod_forced_flatten"] is False
    assert V2Config().allow_real_capital is False


def test_release_documentation_makes_no_profitability_or_official_open_claims():
    root = Path(__file__).resolve().parents[1]
    docs = [root / "docs" / "product" / n for n in ("PRODUCT_DEFINITION.md", "DECISION_LOG.md", "REQUIREMENTS_TRACKER.md")]
    docs += list((root / "docs" / "research" / "evidence" / "v2_final_release_acceptance").glob("*.md"))
    bad = ("v2 is profitable", "proven positive expectancy", "economically validated", "profitability is proven",
           "official opening-auction price is used", "entry open is the official opening")
    for d in docs:
        t = d.read_text(encoding="utf-8").lower()
        for phrase in bad:
            assert phrase not in t, (d.name, phrase)
    ev = root / "docs" / "research" / "evidence" / "v2_final_release_acceptance" / "README.md"
    if ev.exists():
        t = ev.read_text(encoding="utf-8")
        assert "UNPROVEN" in t and "not the official opening-auction print" in t.lower().replace("**", "")


def test_release_fingerprints_and_thresholds_unchanged():
    assert pc.RELEASE_CONTRACT.fingerprint() == rg.RELEASE_PROFILE.contract_fingerprint == "ac5e51aa3599d6c9"
    assert rg._strategy_fingerprint() == rg.RELEASE_PROFILE.strategy_fingerprint == "e2acf6454789217e"
    cfg = base.V2Config()
    assert (cfg.min_distinct_owners, cfg.hold_trading_days, cfg.entry_offset_sessions, cfg.liquidity_lookback_sessions,
            cfg.liquidity_min_median_dollar_volume, cfg.liquidity_min_close, cfg.exit_fallforward_max_sessions,
            cfg.max_entry_staleness_sessions, cfg.max_concurrent_positions) == (2, 10, 1, 20, 5_000_000.0, 5.0, 5, 3, 20)
    assert (cfg.starting_cash_usd, cfg.per_position_allocation_usd) == (100_000.0, 10_000.0) or os.environ.get("TALONX_V2_STARTING_CASH_USD")


def test_gate_discloses_intelligence_card_delivery_as_a_warning_not_a_blocker(tmp_path):
    env, vp = good_env(tmp_path)
    on = gate(tmp_path, env=dict(env, TALONX_INTEL_DELIVER_CARDS="1"), vpath=vp)
    c = {x.name: x for x in on.checks}["intelligence_card_delivery"]
    assert c.status == "WARN" and "OPS-011" in c.detail and on.status == "READY"
    # Session 03 A1: with no explicit key, `--deliver --transport telegram` makes the launcher inject
    # TALONX_INTEL_DELIVER_CARDS=1, so the EFFECTIVE state is ON even though the pre-start env says OFF.
    implicit = {x.name: x for x in gate(tmp_path, env=env, vpath=vp).checks}["intelligence_card_delivery"]
    assert implicit.status == "WARN" and "configured=OFF" in implicit.detail
    assert "runtime_requested_by_start=ON" in implicit.detail and "effective=ON" in implicit.detail
    off = {x.name: x for x in gate(tmp_path, env=dict(env, TALONX_INTEL_DELIVER_CARDS="0"),
                                   vpath=vp).checks}["intelligence_card_delivery"]
    assert off.status == "PASS" and "effective=OFF" in off.detail
    dry = {x.name: x for x in gate(tmp_path, env=env, vpath=vp, transport="dryrun").checks}
    assert "effective=OFF" in dry["intelligence_card_delivery"].detail


# =========================================================================== #
# RELEASE FREEZE + PREFLIGHT: new clean campaign, frozen SHA, isolated paths
# =========================================================================== #
def _release_env_ok(tmp_path):
    env, vp = good_env(tmp_path)
    return env, vp


def test_freeze_new_campaign_is_created_once_clean_and_never_inherits_state(tmp_path):
    db = tmp_path / rg.RELEASE_PROFILE.campaign_db_filename
    st = rg.init_release_campaign(db)
    assert rg.clean_campaign_problems(st) == []
    assert st["settled_cash"] == 100_000.0 and st["reserved_capital"] == 0 and st["open_positions"] == 0
    assert st["exit_unresolved"] == 0 and st["pending_entry_intents"] == 0 and st["active_account_blocks"] == 0
    assert st["realized_pnl"] == 0 and st["dividend_receivables"] == 0 and st["v2_alert_outbox_rows"] == 0
    c = st["campaign"]
    assert (c["campaign_id"], c["strategy"], c["strategy_version"], c["execution_mode"], c["provenance"]) == (
        "V2-PAPER-RC1", "INSIDER_BUY_CLUSTER_V2", "INSIDER_BUY_CLUSTER_V2@1", "PAPER", "SEEDED_AT_CREATION")
    assert c["starting_cash_usd"] == 100_000.0 and c["per_position_allocation_usd"] == 10_000.0
    assert c["config_fingerprint"] == "e2acf6454789217e"
    with pytest.raises(RuntimeError):                                        # a campaign is created exactly once
        rg.init_release_campaign(db)
    with pytest.raises(RuntimeError):                                        # the legacy ledger is never a target
        rg.init_release_campaign(tmp_path / "v2_lane.db")
    assert not (tmp_path / "v2_lane.db").exists()


def test_freeze_clean_check_detects_any_inherited_state(tmp_path):
    db = tmp_path / "c.db"
    rg.init_release_campaign(db)
    con = sqlite3.connect(db)
    con.execute("UPDATE portfolio SET cash = 99000")
    con.commit(); con.close()
    assert any("settled cash" in p for p in rg.clean_campaign_problems(rg.campaign_state(db)))
    assert rg.clean_campaign_problems({"exists": False}) == ["ledger does not exist"]


def test_freeze_gate_is_ready_on_the_fresh_release_campaign_and_refuses_legacy_identities(tmp_path):
    db = tmp_path / "v2_release_rc1.db"
    rg.init_release_campaign(db)
    env, vp = good_env(tmp_path)
    ok = gate(tmp_path, env=env, vpath=vp, db=db)
    assert ok.status == "READY", [f"{c.name}: {c.detail}" for c in ok.failed]
    by = {c.name: c for c in ok.checks}
    assert by["release_campaign_config"].status == "PASS" and by["campaign_identity"].status == "PASS"
    # no ledger yet -> WARN (prepared for creation), still no FAIL
    pre = gate(tmp_path, env=env, vpath=vp, db=tmp_path / "not_yet.db")
    assert pre.status == "READY" and {c.name: c for c in pre.checks}["campaign_identity"].status == "WARN"
    for bad_key, bad_val in (("TALONX_V2_CAMPAIGN_ID", "V2"), ("TALONX_V2_STARTING_CASH_USD", "300000"),
                             ("TALONX_V2_ALLOCATION_USD", "25000"), ("TALONX_V2_EXECUTION_MODE", "LIVE")):
        rep = gate(tmp_path, env=dict(env, **{bad_key: bad_val}), vpath=vp, db=db)
        assert "release_campaign_config" in {c.name for c in rep.failed}, bad_key
    rep = gate(tmp_path, env=env, vpath=vp, db=tmp_path / "v2_lane.db")                     # legacy ledger file name
    assert "release_campaign_config" in {c.name for c in rep.failed}
    # a ledger seeded under another identity / cash is refused even with the right env
    other = tmp_path / "other.db"
    V2Store(str(other), starting_cash=300_000.0)                                            # default identity "V2"
    assert "campaign_identity" in {c.name for c in gate(tmp_path, env=env, vpath=vp, db=other).failed}


def test_freeze_campaign_ledger_selection_is_env_driven_and_default_unchanged(tmp_path, monkeypatch):
    import importlib
    from talonx_ops.prospective import paths
    try:
        monkeypatch.delenv("TALONX_V2_DB_PATH", raising=False)
        monkeypatch.delenv("TALONX_V2_STATUS_PATH", raising=False)
        importlib.reload(paths)
        assert paths.V2_DB_PATH == paths.REPO_ROOT / "v2_lane.db"                           # default: the legacy path, unchanged
        assert paths.V2_STATUS_PATH == paths.REPO_ROOT / "v2_service_status.json"
        monkeypatch.setenv("TALONX_V2_DB_PATH", "v2_release_rc1.db")
        monkeypatch.setenv("TALONX_V2_STATUS_PATH", "v2_release_rc1_status.json")
        importlib.reload(paths)
        assert paths.V2_DB_PATH == paths.REPO_ROOT / "v2_release_rc1.db"
        assert paths.V2_STATUS_PATH == paths.REPO_ROOT / "v2_release_rc1_status.json"
    finally:
        monkeypatch.undo()
        importlib.reload(paths)


def test_freeze_launch_env_block_names_the_release_campaign_and_no_secret():
    blk = rg.release_env_block()
    for frag in ("V2-PAPER-RC1", "v2_release_rc1.db", "100000", "10000", "PAPER"):
        assert frag in blk
    assert "TOKEN" not in blk and "SECRET" not in blk


def _mk_repo(tmp_path):
    import subprocess
    def g(*a):
        return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()
    g("init", "-q")
    (tmp_path / "talonx_v2").mkdir(); (tmp_path / "docs").mkdir(); (tmp_path / "tests").mkdir()
    (tmp_path / "talonx_v2" / "core.py").write_text("x=1\n")
    g("add", "-A"); g("commit", "-q", "-m", "frozen")
    return g


def test_freeze_pin_accepts_the_frozen_sha_and_descendants_that_only_touch_docs_tests_and_the_pin(tmp_path):
    from talonx_ops.prospective.preflight import frozen_release_ok
    g = _mk_repo(tmp_path)
    frozen = g("rev-parse", "HEAD")
    assert frozen_release_ok(frozen, frozen[:7], repo=tmp_path)[0]                           # exact
    (tmp_path / "docs" / "n.md").write_text("n")
    (tmp_path / "tests" / "t.py").write_text("t")
    (tmp_path / "talonx_ops" / "prospective").mkdir(parents=True)
    (tmp_path / "talonx_ops" / "prospective" / "__init__.py").write_text("RELEASE_SHA_EXPECTED='x'")
    g("add", "-A"); g("commit", "-q", "-m", "docs+pin")
    ok, why = frozen_release_ok(g("rev-parse", "HEAD"), frozen[:7], repo=tmp_path)
    assert ok, why


def test_freeze_pin_refuses_a_runtime_change_after_the_freeze_and_unrelated_history(tmp_path):
    from talonx_ops.prospective.preflight import frozen_release_ok
    g = _mk_repo(tmp_path)
    frozen = g("rev-parse", "HEAD")
    (tmp_path / "talonx_v2" / "core.py").write_text("x=2\n")                                 # runtime drift
    g("add", "-A"); g("commit", "-q", "-m", "drift")
    ok, why = frozen_release_ok(g("rev-parse", "HEAD"), frozen[:7], repo=tmp_path)
    assert not ok and "runtime files changed" in why
    assert not frozen_release_ok(g("rev-parse", "HEAD"), "deadbeef", repo=tmp_path)[0]       # unknown / non-ancestor SHA


def test_freeze_operator_reads_the_fresh_release_campaign_read_only(tmp_path):
    import hashlib
    db = tmp_path / "v2_release_rc1.db"
    rg.init_release_campaign(db)
    h = lambda: hashlib.md5(Path(db).read_bytes()).hexdigest()   # noqa: E731
    before = h()
    from talonx_ops.operator_read import operator_snapshot
    snap = operator_snapshot(Path(db), status={})
    assert h() == before                                                                     # the read mutated nothing
    a = snap["account"]
    assert a["starting_capital"] == 100_000.0 and a["settled_cash"] == 100_000.0
    assert snap["campaign"]["campaign_id"] == "V2-PAPER-RC1" and snap["campaign"]["execution_mode"] == "PAPER"
    assert snap["campaign"]["strategy_version"] == "INSIDER_BUY_CLUSTER_V2@1"
    assert snap["blocks"] == [] and snap["reconciliation"]["state"] == "HEALTHY"
    assert all(len(v) == 0 for v in snap["positions"].values())
    from talonx_ops.prospective.ledger_guard import check_ledger_continuity
    lc = check_ledger_continuity(db)
    assert lc.ok and lc.cash == 100_000.0 and lc.n_open == 0 and lc.n_trades == 0                # restart-continuity guard accepts it
