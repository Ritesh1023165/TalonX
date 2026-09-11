"""
scripts/task25_live_shadow_capture.py
------------------------------------------
Task 25-LIVE-CAPTURE -- a read-only, observational Redis subscriber +
periodic talonx_paper SQLite poller. Writes machine-readable flight-
recorder rows for later deterministic replay comparison against the
corrected (Task 25A) backtest engine.

Does NOT modify any production module, trading logic, or config. Only
subscribes to Redis channels every module already publishes to, and
performs read-only SELECT queries against talonx_paper's existing
SQLite store. Never writes to production state.

Scope: filtered to the 8 core research symbols confirmed present in the
live watchlist (AAPL, MSFT, NVDA, AMD, TSLA, GOOGL, PYPL, STX) -- AMZN
and META are NOT in the current production watchlist and are therefore
never observed (not fabricated, not backfilled -- see
live_data_quality.json for this exact gap).
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import redis.asyncio as redis
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env", override=False)

_ET = ZoneInfo("America/New_York")
_OUT_DIR = _REPO_ROOT / "results" / "task25_live_shadow_2026-08-20"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

_TARGET_SYMBOLS = {"AAPL", "MSFT", "NVDA", "AMD", "TSLA", "GOOGL", "PYPL", "STX"}
_REQUESTED_NOT_PRESENT = {"AMZN", "META"}  # requested but absent from the live watchlist -- never captured

_REDIS_URL = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
_PAPER_DB = os.environ.get("TALONX_PAPER_DB", str(Path.home() / ".talonx" / "paper_trading.db"))

_CHANNELS = [
    "talonx:market:stream",
    "talonx:signals:quant",
    "talonx:quant:rejected",
    "talonx:alerts:dispatch",
    "talonx:paper:trades",
    "talonx:ingest:ws_heartbeat",
]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _et(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_ET).isoformat()


class _CsvWriter:
    def __init__(self, path: Path, fieldnames: list[str]):
        self.path = path
        self.fieldnames = fieldnames
        new = not self.path.exists()
        self._file = open(self.path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.fieldnames, extrasaction="ignore")
        if new:
            self._writer.writeheader()
            self._file.flush()

    def write(self, row: dict) -> None:
        self._writer.writerow(row)
        self._file.flush()


bars_w = _CsvWriter(_OUT_DIR / "live_bars.csv", [
    "capture_ts_utc", "timestamp_utc", "timestamp_et", "symbol", "provider", "event_type",
    "session", "open", "high", "low", "close", "volume",
])
candidates_w = _CsvWriter(_OUT_DIR / "live_candidate_trace.csv", [
    "capture_ts_utc", "bar_timestamp_utc", "bar_timestamp_et", "symbol", "signal_type", "direction",
    "price", "rsi", "macd", "macd_signal_line", "sma_fast", "sma_slow", "volume_surge_ratio", "atr",
    "confluence_score", "risk_reward_ratio", "stop_price", "target_price", "pivot_resistance",
    "pivot_support", "trend_aligned", "session", "signal_age_ms", "published",
])
gates_w = _CsvWriter(_OUT_DIR / "live_gate_trace.csv", [
    "capture_ts_utc", "symbol", "gate", "reason", "signal_type", "direction", "price",
    "confluence_score", "risk_reward_ratio", "session", "count", "rejected_at_utc",
])
quant_outputs_w = _CsvWriter(_OUT_DIR / "live_quant_outputs.csv", [
    "capture_ts_utc", "symbol", "result", "reason_or_signal_type", "direction",
])
paper_state_w = _CsvWriter(_OUT_DIR / "live_paper_state_transitions.csv", [
    "capture_ts_utc", "source", "ticker", "action_or_reason", "decision", "order_type",
    "reference_price", "fill_price", "stop_price", "target_price", "shares", "realized_pnl_usd",
    "position_after_shares", "raw_json",
])
runtime_events_w = _CsvWriter(_OUT_DIR / "live_runtime_events.csv", [
    "capture_ts_utc", "event_type", "detail",
])

_special_events: list[dict] = []
_last_bar_seen: dict[str, datetime] = {}
_last_action: dict[str, str] = {}  # ticker -> last known AlertAction, for flag B/C/D detection
_last_position_state: dict[str, bool] = {}  # ticker -> has_open, from paper store polling


def _flag(kind: str, detail: dict) -> None:
    row = {"capture_ts_utc": _now_utc().isoformat(), "kind": kind, **detail}
    _special_events.append(row)
    runtime_events_w.write({"capture_ts_utc": row["capture_ts_utc"], "event_type": f"SPECIAL:{kind}", "detail": json.dumps(detail)})


def _closing_blackout(ts: datetime) -> bool:
    local = ts.astimezone(_ET).time()
    return (15, 30) <= (local.hour, local.minute) < (16, 0)


async def _handle_market(payload: dict) -> None:
    symbol = payload.get("symbol", "").upper()
    if symbol not in _TARGET_SYMBOLS:
        return
    ts_raw = payload.get("timestamp")
    try:
        ts = datetime.fromisoformat(ts_raw) if ts_raw else _now_utc()
    except ValueError:
        ts = _now_utc()
    prior = _last_bar_seen.get(symbol)
    if prior is not None:
        gap = (ts - prior).total_seconds()
        if gap < 0:
            runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "OUT_OF_ORDER_BAR", "detail": f"{symbol} ts={ts_raw} prior={prior.isoformat()}"})
        elif gap > 90:
            runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "MISSING_MINUTE_GAP", "detail": f"{symbol} gap_seconds={gap:.0f}"})
        elif gap == 0:
            runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "DUPLICATE_BAR", "detail": f"{symbol} ts={ts_raw}"})
    _last_bar_seen[symbol] = ts

    bars_w.write({
        "capture_ts_utc": _now_utc().isoformat(), "timestamp_utc": ts.isoformat(), "timestamp_et": _et(ts),
        "symbol": symbol, "provider": payload.get("source"), "event_type": payload.get("event_type"),
        "session": payload.get("session"), "open": payload.get("open"), "high": payload.get("high"),
        "low": payload.get("low"), "close": payload.get("close"), "volume": payload.get("volume"),
    })


async def _handle_quant_signal(payload: dict) -> None:
    symbol = payload.get("ticker", "").upper()
    if symbol not in _TARGET_SYMBOLS:
        return
    bar_ts_raw = payload.get("bar_timestamp")
    try:
        bar_ts = datetime.fromisoformat(bar_ts_raw) if bar_ts_raw else _now_utc()
    except ValueError:
        bar_ts = _now_utc()
    direction = payload.get("direction")

    candidates_w.write({
        "capture_ts_utc": _now_utc().isoformat(), "bar_timestamp_utc": bar_ts.isoformat(), "bar_timestamp_et": _et(bar_ts),
        "symbol": symbol, "signal_type": payload.get("signal_type"), "direction": direction,
        "price": payload.get("price"), "rsi": payload.get("rsi"), "macd": payload.get("macd"),
        "macd_signal_line": payload.get("macd_signal_line"), "sma_fast": payload.get("sma_fast"),
        "sma_slow": payload.get("sma_slow"), "volume_surge_ratio": payload.get("volume_surge_ratio"),
        "atr": payload.get("atr"), "confluence_score": payload.get("confluence_score"),
        "risk_reward_ratio": payload.get("risk_reward_ratio"), "stop_price": payload.get("stop_price"),
        "target_price": payload.get("target_price"), "pivot_resistance": payload.get("pivot_resistance"),
        "pivot_support": payload.get("pivot_support"), "trend_aligned": payload.get("trend_aligned"),
        "session": payload.get("session"), "signal_age_ms": payload.get("signal_age_ms"), "published": True,
    })
    quant_outputs_w.write({
        "capture_ts_utc": _now_utc().isoformat(), "symbol": symbol, "result": "PUBLISHED",
        "reason_or_signal_type": payload.get("signal_type"), "direction": direction,
    })

    if _closing_blackout(bar_ts):
        if direction == "bullish":
            _flag("UNEXPECTED_BULLISH_PUBLISHED_DURING_CLOSING_BLACKOUT", {"symbol": symbol, "bar_ts": bar_ts.isoformat()})
        elif direction == "bearish":
            _flag("BEARISH_DURING_CLOSING_BLACKOUT_PUBLISHED", {"symbol": symbol, "bar_ts": bar_ts.isoformat(), "note": "expected -- may act as an exit"})


async def _handle_rejected(payload: dict) -> None:
    symbol = payload.get("ticker", "").upper()
    if symbol not in _TARGET_SYMBOLS:
        return
    gates_w.write({
        "capture_ts_utc": _now_utc().isoformat(), "symbol": symbol, "gate": payload.get("gate"),
        "reason": payload.get("reason"), "signal_type": payload.get("signal_type"),
        "direction": payload.get("direction"), "price": payload.get("price"),
        "confluence_score": payload.get("confluence_score"), "risk_reward_ratio": payload.get("risk_reward_ratio"),
        "session": payload.get("session"), "count": payload.get("count"), "rejected_at_utc": payload.get("rejected_at"),
    })
    quant_outputs_w.write({
        "capture_ts_utc": _now_utc().isoformat(), "symbol": symbol, "result": "REJECTED",
        "reason_or_signal_type": payload.get("reason"), "direction": payload.get("direction"),
    })
    if payload.get("reason") == "CLOSING_BLACKOUT" and payload.get("direction") == "bullish":
        _flag("BULLISH_BLOCKED_BY_CLOSING_BLACKOUT", {"symbol": symbol})


async def _handle_alert(payload: dict) -> None:
    symbol = payload.get("ticker", "").upper()
    if symbol not in _TARGET_SYMBOLS:
        return
    action = payload.get("action")
    prior_action = _last_action.get(symbol)
    _last_action[symbol] = action
    paper_state_w.write({
        "capture_ts_utc": _now_utc().isoformat(), "source": "talonx:alerts:dispatch", "ticker": symbol,
        "action_or_reason": action, "decision": None, "order_type": None, "reference_price": None,
        "fill_price": None, "stop_price": None, "target_price": None, "shares": None,
        "realized_pnl_usd": None, "position_after_shares": None, "raw_json": json.dumps(payload)[:2000],
    })
    if action == "confirmed_bearish" and not _last_position_state.get(symbol, False):
        _flag("BEARISH_WHILE_FLAT", {"symbol": symbol, "expected": "NO_ACTIVE_POSITION/ignored"})
    elif action == "confirmed_bearish" and _last_position_state.get(symbol, False):
        _flag("BEARISH_WHILE_LONG", {"symbol": symbol, "expected": "exit existing long"})


async def _handle_paper_trade(payload: dict) -> None:
    symbol = payload.get("ticker", "").upper()
    if symbol not in _TARGET_SYMBOLS:
        return
    order_type = payload.get("order_type")
    entry_price = payload.get("entry_price")
    exec_price = payload.get("execution_price")
    stop_price = None
    target_price = None
    paper_state_w.write({
        "capture_ts_utc": _now_utc().isoformat(), "source": "talonx:paper:trades", "ticker": symbol,
        "action_or_reason": payload.get("triggering_action"), "decision": order_type, "order_type": order_type,
        "reference_price": entry_price, "fill_price": exec_price, "stop_price": stop_price,
        "target_price": target_price, "shares": payload.get("shares"),
        "realized_pnl_usd": payload.get("realized_pnl_usd"), "position_after_shares": None,
        "raw_json": json.dumps(payload)[:2000],
    })
    if order_type == "BUY":
        _last_position_state[symbol] = True
    elif order_type == "SELL":
        _last_position_state[symbol] = False
        if payload.get("triggering_action") == "eod_flat_liquidation":
            _flag("EOD_FLATTEN_CLOSE", {"symbol": symbol, "exec_price": exec_price})


async def _consume(pubsub) -> None:
    async for message in pubsub.listen():
        if message is None or message.get("type") != "message":
            continue
        channel = message["channel"]
        if isinstance(channel, bytes):
            channel = channel.decode()
        try:
            payload = json.loads(message["data"])
        except (TypeError, ValueError, json.JSONDecodeError):
            runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "UNPARSEABLE_MESSAGE", "detail": channel})
            continue
        try:
            if channel == "talonx:market:stream":
                await _handle_market(payload)
            elif channel == "talonx:signals:quant":
                await _handle_quant_signal(payload)
            elif channel == "talonx:quant:rejected":
                await _handle_rejected(payload)
            elif channel == "talonx:alerts:dispatch":
                await _handle_alert(payload)
            elif channel == "talonx:paper:trades":
                await _handle_paper_trade(payload)
            elif channel == "talonx:ingest:ws_heartbeat":
                runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "WS_HEARTBEAT", "detail": json.dumps(payload)[:500]})
        except Exception as exc:  # noqa: BLE001 -- observational only, never let one bad message kill the capture
            runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "HANDLER_ERROR", "detail": f"{channel}: {exc!r}"})


_last_ignored_id = 0


def _poll_paper_store() -> None:
    """Read-only poll of talonx_paper's SQLite store for ignored_decisions
    (never published to Redis) and current position snapshot -- new rows
    since the last poll only."""
    global _last_ignored_id
    try:
        conn = sqlite3.connect(f"file:{_PAPER_DB}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, ticker, reason, triggering_action, price, timestamp FROM ignored_decisions "
            "WHERE id > ? AND horizon = 'intraday' ORDER BY id",
            (_last_ignored_id,),
        )
        rows = cur.fetchall()
        for row in rows:
            _last_ignored_id = max(_last_ignored_id, row["id"])
            ticker = row["ticker"].upper()
            if ticker not in _TARGET_SYMBOLS:
                continue
            paper_state_w.write({
                "capture_ts_utc": _now_utc().isoformat(), "source": "paper_store.ignored_decisions",
                "ticker": ticker, "action_or_reason": row["triggering_action"], "decision": "IGNORED",
                "order_type": None, "reference_price": row["price"], "fill_price": None,
                "stop_price": None, "target_price": None, "shares": None, "realized_pnl_usd": None,
                "position_after_shares": None, "raw_json": json.dumps(dict(row)),
            })
            if row["reason"] == "NO_ACTIVE_POSITION" and row["triggering_action"] == "confirmed_bearish":
                _flag("BEARISH_WHILE_FLAT_IGNORED_CONFIRMED", {"symbol": ticker, "reason": row["reason"]})
        for symbol in _TARGET_SYMBOLS:
            pos = conn.execute("SELECT shares FROM positions WHERE ticker = ?", (symbol,)).fetchone()
            _last_position_state[symbol] = pos is not None and pos["shares"] not in (None, 0)
        conn.close()
    except Exception as exc:  # noqa: BLE001
        runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "PAPER_STORE_POLL_ERROR", "detail": repr(exc)})


async def _poll_loop() -> None:
    while True:
        _poll_paper_store()
        await asyncio.sleep(15)


async def main() -> None:
    runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "CAPTURE_STARTED", "detail": f"symbols={sorted(_TARGET_SYMBOLS)}"})
    backoff = 1.0
    while True:
        try:
            client = redis.from_url(_REDIS_URL, decode_responses=True)
            await client.ping()
            pubsub = client.pubsub()
            await pubsub.subscribe(*_CHANNELS)
            runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "REDIS_CONNECTED", "detail": _REDIS_URL})
            backoff = 1.0
            await asyncio.gather(_consume(pubsub), _poll_loop())
        except (redis.ConnectionError, redis.TimeoutError, OSError) as exc:
            runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "REDIS_DISCONNECT", "detail": repr(exc)})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        runtime_events_w.write({"capture_ts_utc": _now_utc().isoformat(), "event_type": "CAPTURE_STOPPED", "detail": "KeyboardInterrupt"})
