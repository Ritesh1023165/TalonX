"""
OUTCOME_TRACKING component -- HINDSIGHT / EVALUATION ONLY, single writer of outcomes.db. Never feeds detection.

Unlike V1 (which measured only delivered candidates), EVERY persisted candidate is measured -- surfacing to
Telegram is irrelevant to evaluation. Two models, both direction-adjusted (a fall is favourable for BEARISH):

* first seen BEFORE the regular open -> ``talonx_premarket.outcomes.measure`` (the frozen V1 rule, unchanged):
  reference = the price at first sighting; OPEN, +30M, +1H, CLOSE, MFE/MAE over the session.
* first seen DURING the regular session -> ``SINCE_FIRST_SEEN_V1``: reference = price at first sighting (data
  as-of), +30M / +1H after the first-sighting data time, the regular CLOSE, MFE/MAE from first sighting to close.
  Status: OUTCOME_PENDING until +30M exists; INVALIDATED if the move fully reverted through the previous close within
  30 min; CONFIRMED if +30M is on the setup's side of the reference; else FAILED_CONFIRMATION.
* first seen at/after the regular close (AFTER_HOURS) -> NOT_APPLICABLE_SAME_DAY (no same-day regular session
  remains). OVERNIGHT precedes the open, so it would use the pre-open model (overnight discovery is fail-closed).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from talonx_opportunity.db import connect, iso, root_dir, utcnow
from talonx_opportunity.phases import trading_window
from talonx_opportunity.store import OpportunityStore, opportunity_db
from talonx_premarket.alpaca_data import data_as_of, parse_ts
from talonx_premarket.outcomes import CONFIRMED, FAILED_CONFIRMATION, INVALIDATED, OUTCOME_PENDING, measure

NOT_APPLICABLE = "NOT_APPLICABLE_SAME_DAY"
SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    candidate_id TEXT PRIMARY KEY, window_id TEXT, symbol TEXT, family TEXT, model TEXT, first_seen_phase TEXT,
    ref_price REAL, ref_time_utc TEXT, status TEXT, open_px REAL, px_30m REAL, px_1h REAL, close_px REAL,
    open_ret_pct REAL, ret_30m_pct REAL, ret_1h_pct REAL, close_ret_pct REAL, mfe_pct REAL, mae_pct REAL,
    session_complete INTEGER, updated_utc TEXT);
"""


def outcomes_db(root=None) -> Path:
    return root_dir(root) / "outcomes.db"


def _ret(px, ref, sign):
    return None if px is None else round(sign * (px / ref - 1.0) * 100.0, 3)


def since_first_seen(*, family: str, ref_price: float, ref_time: datetime, prev_close: float, bars: list[dict],
                     close_utc: datetime, confirm_min: int = 30) -> dict:
    sign = 1 if family == "GAP_UP" else -1
    after = sorted((b for b in bars if parse_ts(b["t"]) >= ref_time and parse_ts(b["t"]) < close_utc),
                   key=lambda b: b["t"])
    if not after:
        return {"status": OUTCOME_PENDING}
    t30, t60 = ref_time + timedelta(minutes=confirm_min), ref_time + timedelta(minutes=60)

    def close_at(end):
        px = None
        for b in after:
            if parse_ts(b["t"]) + timedelta(minutes=1) <= end:
                px = float(b["c"])
        return px
    last_end = parse_ts(after[-1]["t"]) + timedelta(minutes=1)
    px30 = close_at(t30) if last_end >= t30 else None
    px60 = close_at(t60) if last_end >= t60 else None
    done = last_end >= close_utc
    close_px = float(after[-1]["c"]) if done else None
    hi, lo = max(float(b["h"]) for b in after), min(float(b["l"]) for b in after)
    fav, adv = (hi, lo) if sign > 0 else (lo, hi)
    first30 = [b for b in after if parse_ts(b["t"]) < t30]
    if px30 is None:
        status = OUTCOME_PENDING
    elif ((min(float(b["l"]) for b in first30) <= prev_close) if sign > 0
          else (max(float(b["h"]) for b in first30) >= prev_close)):
        status = INVALIDATED
    else:
        status = CONFIRMED if sign * (px30 - ref_price) >= 0 else FAILED_CONFIRMATION
    return {"status": status, "open_px": None, "px_30m": px30, "px_1h": px60, "close_px": close_px,
            "open_ret_pct": None, "ret_30m_pct": _ret(px30, ref_price, sign), "ret_1h_pct": _ret(px60, ref_price, sign),
            "close_ret_pct": _ret(close_px, ref_price, sign), "mfe_pct": _ret(fav, ref_price, sign),
            "mae_pct": _ret(adv, ref_price, sign), "session_complete": done}


class OutcomeTracker:
    def __init__(self, *, root=None, data=None, clock=None, interval_s: float = 600.0):
        self.root = root
        self.con = connect(outcomes_db(root), schema=SCHEMA)
        self._data = data
        self.clock = clock or utcnow
        self.interval_s = interval_s
        self.last: dict = {}

    @property
    def data(self):
        if self._data is None:
            from talonx_premarket import __main__ as M
            from talonx_premarket.alpaca_data import AlpacaData, RateLimiter
            M._env()
            base = M._data()
            self._data = AlpacaData(key_id=base._headers["APCA-API-KEY-ID"],
                                    secret=base._headers["APCA-API-SECRET-KEY"], limiter=RateLimiter(40))
        return self._data

    def _final(self, cid: str) -> bool:
        r = self.con.execute("SELECT status, session_complete FROM outcomes WHERE candidate_id=?", (cid,)).fetchone()
        return bool(r and (r["session_complete"] or r["status"] == NOT_APPLICABLE))

    def tick(self) -> float:
        if not opportunity_db(self.root).exists():
            return self.interval_s
        now = self.clock()
        as_of = data_as_of(now)
        opp = OpportunityStore(self.root, readonly=True)
        try:
            cands = [c for c in opp.candidates() if not self._final(c["candidate_id"])]
        finally:
            opp.close()
        by_window: dict[str, list[dict]] = {}
        for c in cands:
            by_window.setdefault(c["window_id"], []).append(c)
        measured = 0
        for wid, cs in by_window.items():
            w = trading_window(date.fromisoformat(wid))
            post = [c for c in cs if datetime.fromisoformat(c["first_seen_utc"]) >= w.close_utc]
            for c in post:
                self._upsert(c, "N/A", {"status": NOT_APPLICABLE, "session_complete": True}, None)
            live = [c for c in cs if c not in post]
            if not live or as_of <= w.open_utc:
                continue
            end = min(as_of, w.close_utc)
            res = self.data.bars_ex(sorted({c["symbol"] for c in live}), timeframe="1Min", start=w.open_utc,
                                    end=end - timedelta(seconds=1))
            for c in live:
                if c["symbol"] in res.failed:
                    continue                          # provider failure: keep the last outcome, retry next tick
                bars = res.bars.get(c["symbol"], [])
                first = datetime.fromisoformat(c["first_seen_utc"])
                if first < w.open_utc:
                    m = measure(family=c["family"], ref_price=c["ref_price"], prev_close=c["prev_close"],
                                rth_bars=bars, open_utc=w.open_utc, close_utc=w.close_utc)
                    model = "PREMARKET_RESEARCH_V1.measure"
                    ref_t = c["first_data_as_of_utc"]
                else:
                    ref_t = c["first_data_as_of_utc"] or c["first_seen_utc"]
                    m = since_first_seen(family=c["family"], ref_price=c["ref_price"],
                                         ref_time=datetime.fromisoformat(ref_t), prev_close=c["prev_close"],
                                         bars=bars, close_utc=w.close_utc)
                    model = "SINCE_FIRST_SEEN_V1"
                self._upsert(c, model, m, ref_t)
                measured += 1
        self.last = {"pending_candidates": len(cands), "measured": measured}
        return self.interval_s

    def _upsert(self, c, model, m, ref_t) -> None:
        self.con.execute("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (c["candidate_id"], c["window_id"], c["symbol"], c["family"], model, c["first_seen_phase"],
                          c["ref_price"], ref_t, m.get("status"), m.get("open_px"), m.get("px_30m"), m.get("px_1h"),
                          m.get("close_px"), m.get("open_ret_pct"), m.get("ret_30m_pct"), m.get("ret_1h_pct"),
                          m.get("close_ret_pct"), m.get("mfe_pct"), m.get("mae_pct"),
                          int(bool(m.get("session_complete"))), iso()))
        self.con.commit()

    def detail(self) -> dict:
        return dict(self.last)


def main(argv=None) -> int:
    from talonx_opportunity.runtime import run_component
    root = os.environ.get("TALONX_OPP_ROOT")
    t = OutcomeTracker(root=root)
    run_component("outcomes", tick=t.tick, root=root, detail=t.detail,
                  config_fps={"models": "PREMARKET_RESEARCH_V1.measure+SINCE_FIRST_SEEN_V1"})
    return 0
