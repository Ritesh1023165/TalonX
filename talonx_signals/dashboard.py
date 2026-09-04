"""Task 99A S6 -- experimental-signal telemetry dashboard.

A SEPARATE, read-only aiohttp app (binds 127.0.0.1, GET/HEAD only). It does
NOT touch the qualified 96G intelligence dashboard -- it reads only the
isolated talonx_signals SQLite files plus a caller-supplied system-health
dict. Server-rendered HTML, one inline stylesheet, no JS framework / npm /
CDN. There is deliberately no control on this page that could place, modify,
or cancel an order.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any, Callable

from talonx_signals.alert_store import ExperimentalAlertStore
from talonx_signals.telemetry import ForwardOutcomeStore

_STYLE = """
body{font-family:system-ui,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header{padding:14px 20px;background:#161a21;border-bottom:1px solid #2a2f3a}
h1{font-size:16px;margin:0}
main{padding:16px 20px;display:grid;gap:18px;max-width:1200px}
section{background:#161a21;border:1px solid #2a2f3a;border-radius:8px;padding:12px 14px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:#9aa4b2;margin:0 0 8px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid #232833;white-space:nowrap}
th{color:#9aa4b2;font-weight:600}
.pill{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;border:1px solid #3a4150}
.ok{color:#7ee787;border-color:#2ea043}.warn{color:#f0c674;border-color:#9e6a03}.bad{color:#ff7b72;border-color:#da3633}
.bull{color:#7ee787}.bear{color:#ff7b72}
.muted{color:#7b8494}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.empty{color:#7b8494;font-style:italic;padding:8px 0}
footer{padding:10px 20px;color:#7b8494;font-size:11px}
"""

_PROFILE_CONTROL = "FROZEN_CONTROL"
_PROFILE_EXPERIMENTAL = "EXPERIMENTAL_RELAXED_V1"


class _Raw(str):
    """Marks a string as already-safe HTML -- `_table` will not escape it.
    Everything not wrapped in `_Raw` is escaped, so untrusted text that happens
    to start with '<' can never slip through."""


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _span(cls: str, text: Any) -> _Raw:
    return _Raw(f'<span class="{cls}">{_e(text)}</span>')


def _num(v: Any, digits: int = 2) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "&mdash;"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '<div class="empty">no rows</div>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c if isinstance(c, _Raw) else _e(c)}</td>" for c in r) + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


class ExperimentalDashboard:
    """Pure render helper -- unit-testable without a running server."""

    def __init__(
        self,
        alert_store: ExperimentalAlertStore,
        outcome_store: ForwardOutcomeStore,
        *,
        health_provider: Callable[[], dict[str, Any]] | None = None,
        premarket_provider: Callable[[], Any] | None = None,
    ):
        self.alert_store = alert_store
        self.outcome_store = outcome_store
        self.health_provider = health_provider or (lambda: {})
        self.premarket_provider = premarket_provider or (lambda: None)

    # ------------------------------------------------------------------
    def render(self) -> str:
        parts = [
            self._system_health(),
            self._premarket(),
            f'<div class="grid2">{self._earnings_radar()}{self._intelligence_events()}</div>',
            f'<div class="grid2">{self._latest_directional("BULLISH")}{self._latest_directional("BEARISH")}</div>',
            self._experimental_trades(),
            self._control_vs_experimental(),
            self._forward_outcomes(),
        ]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return (
            "<!doctype html><meta charset=utf-8><title>TalonX Experimental Signals</title>"
            f"<style>{_STYLE}</style>"
            "<header><h1>TalonX &mdash; Experimental Signal Telemetry "
            '<span class="muted">(EXPERIMENTAL_RELAXED_V1 &middot; paper-only &middot; observational)</span></h1></header>'
            f"<main>{''.join(parts)}</main>"
            f'<footer>rendered {now} &middot; read-only &middot; no execution controls on this page</footer>'
        )

    # ------------------------------------------------------------------
    def _system_health(self) -> str:
        h = self.health_provider() or {}
        rows = []
        for key in ("market_feed", "control_strategy", "experimental_strategy",
                    "intelligence_service", "dispatcher", "paper_engine", "telegram"):
            v = h.get(key, {})
            status = (v.get("status") if isinstance(v, dict) else v) or "unknown"
            cls = {"up": "ok", "healthy": "ok", "fresh": "ok", "degraded": "warn",
                   "stale": "warn", "down": "bad", "error": "bad"}.get(str(status).lower(), "muted")
            detail = v.get("detail", "") if isinstance(v, dict) else ""
            rows.append([key, _span(f"pill {cls}", status), detail])
        extra = []
        if h.get("last_event_at"):
            extra.append(f'last event: {_e(h["last_event_at"])}')
        if h.get("coverage"):
            extra.append(f'coverage: {_e(h["coverage"])}')
        note = f'<div class="muted">{" &middot; ".join(extra)}</div>' if extra else ""
        return f"<section><h2>System Health</h2>{_table(['component','status','detail'], rows)}{note}</section>"

    def _premarket(self) -> str:
        b = self.premarket_provider()
        if b is None:
            return '<section><h2>Pre-market</h2><div class="empty">no pre-market scan yet</div></section>'
        d = b if isinstance(b, dict) else b.model_dump(mode="json")

        def _rows(items):
            return [[w["symbol"], w.get("kind"), _num(w.get("gap_pct")), w.get("detail")]
                    for w in (items or [])]

        blocks = []
        for label, key in (("Earnings RADAR", "radar"), ("Gap up", "gap_up"), ("Gap down", "gap_down"),
                           ("Abnormal volume", "abnormal_volume"), ("Bullish watch", "bullish_watch"),
                           ("Bearish watch", "bearish_watch"), ("Event context", "event_context")):
            blocks.append(f"<h2 style='margin-top:10px'>{label}</h2>"
                          + _table(["symbol", "kind", "gap%", "detail"], _rows(d.get(key))))
        cov = f'<div class="muted">watchlist {d.get("watchlist_covered")}/{d.get("watchlist_active")} covered</div>'
        return f"<section><h2>Pre-market</h2>{cov}{''.join(blocks)}</section>"

    def _earnings_radar(self) -> str:
        with self.alert_store._lock:  # noqa: SLF001
            rows = [dict(r) for r in self.alert_store._conn.execute(
                "SELECT * FROM radar_alerts ORDER BY reporting_when LIMIT 60"
            ).fetchall()]
        tbl = _table(
            ["symbol", "expected report", "price", "status", "context"],
            [[r["symbol"], r.get("reporting_when"), _num(r.get("current_price")),
              r.get("holding_status") or "-", r.get("context")] for r in rows],
        )
        return (f"<section><h2>Earnings Radar "
                f'<span class="muted">(watchlist calendar, yfinance / free)</span></h2>{tbl}</section>')

    def _intelligence_events(self) -> str:
        with self.alert_store._lock:  # noqa: SLF001
            rows = [dict(r) for r in self.alert_store._conn.execute(
                "SELECT * FROM event_updates ORDER BY accepted_at DESC LIMIT 60"
            ).fetchall()]
        def _band(b):
            cls = {"CRITICAL": "bad", "HIGH": "warn", "MEDIUM": "muted", "LOW": "muted"}.get(str(b), "muted")
            return _span(f"pill {cls}", b or "-")
        tbl = _table(
            ["accepted", "symbol", "event", "significance", "evidence"],
            [[r.get("accepted_at"), r["symbol"], r.get("event_type"), _band(r.get("significance_band")),
              _Raw(f'<a href="http://127.0.0.1:8760/evidence/event/{_e(r.get("source_event_id") or "")}">96G</a>')
              if r.get("source_event_id") else "-"] for r in rows],
        )
        return (f"<section><h2>Live Intelligence Events "
                f'<span class="muted">(SEC 8-K 2.02 / 10-Q / 10-K -- descriptive, not a forecast)</span>'
                f"</h2>{tbl}</section>")

    def _latest_directional(self, direction: str) -> str:
        rows = [
            r for r in self.alert_store.pending("directional_alerts") + self._sent_directional()
            if str(r["direction"]).upper().endswith(direction)
        ]
        rows = sorted(rows, key=lambda r: r.get("bar_timestamp") or "", reverse=True)[:15]
        cls = "bull" if direction == "BULLISH" else "bear"
        table = _table(
            ["time", "symbol", "price", "setup", "score", "profile", "gate"],
            [[
                r.get("bar_timestamp"), _span(cls, r["symbol"]),
                _num(r.get("price")), r.get("setup_type"), r.get("setup_score"),
                r.get("profile"), r.get("trade_gate_status"),
            ] for r in rows],
        )
        return f"<section><h2>Latest {direction} setups</h2>{table}</section>"

    def _sent_directional(self) -> list[dict]:
        # everything, including already-sent -- pending() only returns unsent
        with self.alert_store._lock:  # noqa: SLF001 - same module family, read-only
            cur = self.alert_store._conn.execute(
                "SELECT * FROM directional_alerts ORDER BY bar_timestamp DESC LIMIT 200"
            )
            return [dict(r) for r in cur.fetchall()]

    def _experimental_trades(self) -> str:
        with self.alert_store._lock:  # noqa: SLF001
            cur = self.alert_store._conn.execute(
                "SELECT * FROM experimental_trades ORDER BY created_at DESC LIMIT 100"
            )
            trades = [dict(r) for r in cur.fetchall()]
        buys = [t for t in trades if str(t["side"]).upper() == "BUY"]
        exits = [t for t in trades if str(t["side"]).upper() == "SELL"]
        open_syms = {t["symbol"] for t in buys} - {t["symbol"] for t in exits}
        buy_tbl = _table(
            ["opened", "symbol", "entry", "stop", "target", "qty", "admitted_by", "open?"],
            [[t.get("opened_at"), t["symbol"], _num(t.get("entry")), _num(t.get("stop")),
              _num(t.get("target")), t.get("quantity"), t.get("admitted_by"),
              "yes" if t["symbol"] in open_syms else "closed"] for t in buys],
        )
        exit_tbl = _table(
            ["closed", "symbol", "exit", "reason", "net P&L", "R"],
            [[t.get("closed_at"), t["symbol"], _num(t.get("exit")), t.get("exit_reason"),
              _num(t.get("net_pnl")), _num(t.get("r_multiple"))] for t in exits],
        )
        return (f"<section><h2>Experimental Trades (paper)</h2>"
                f"<h2 style='margin-top:8px'>Buys / open</h2>{buy_tbl}"
                f"<h2 style='margin-top:8px'>Exits</h2>{exit_tbl}</section>")

    def _control_vs_experimental(self) -> str:
        all_dir = self._sent_directional()

        def _c(profile):
            d = [r for r in all_dir if r["profile"] == profile]
            bull = sum(1 for r in d if str(r["direction"]).upper().endswith("BULLISH"))
            bear = sum(1 for r in d if str(r["direction"]).upper().endswith("BEARISH"))
            rejects: dict[str, int] = {}
            for r in d:
                rr = r.get("trade_gate_reject_reason")
                if rr:
                    rejects[rr] = rejects.get(rr, 0) + 1
            return len(d), bull, bear, rejects

        c_n, c_b, c_r, c_rej = _c(_PROFILE_CONTROL)
        e_n, e_b, e_r, e_rej = _c(_PROFILE_EXPERIMENTAL)
        with self.alert_store._lock:  # noqa: SLF001
            e_trades = self.alert_store._conn.execute(
                "SELECT COUNT(*) FROM experimental_trades WHERE side='BUY'"
            ).fetchone()[0]
        rows = [
            ["directional alerts", c_n, e_n],
            ["  bullish", c_b, e_b],
            ["  bearish", c_r, e_r],
            ["experimental BUYs", "&mdash;", e_trades],
        ]
        rej_rows = sorted(set(c_rej) | set(e_rej))
        for reason in rej_rows:
            rows.append([f"reject: {reason}", c_rej.get(reason, 0), e_rej.get(reason, 0)])
        return (f"<section><h2>Control vs Experimental_relaxed_v1</h2>"
                f"{_table(['metric', 'FROZEN_CONTROL', 'EXPERIMENTAL_RELAXED_V1'], rows)}</section>")

    def _forward_outcomes(self) -> str:
        rows = self.outcome_store.all_rows()
        pending = sum(1 for r in rows if r["status"] != "COMPLETE")
        tbl = _table(
            ["time", "symbol", "dir", "profile", "setup", "+30m", "+60m", "EOD", "+1D", "MFE", "MAE", "status"],
            [[
                r.get("alert_ts"), r["symbol"],
                _span("bull" if r["direction"] == "BULLISH" else "bear", r["direction"]),
                r.get("profile"), r.get("setup"),
                _num(r.get("r_30m")), _num(r.get("r_60m")), _num(r.get("r_eod")), _num(r.get("r_1d")),
                _num(r.get("mfe")), _num(r.get("mae")), r.get("status"),
            ] for r in sorted(rows, key=lambda r: r.get("alert_ts") or "", reverse=True)[:60]],
        )
        return (f"<section><h2>Forward Outcomes "
                f'<span class="muted">({pending} pending / {len(rows)} total &middot; +1D fills next session)</span>'
                f"</h2>{tbl}</section>")


# ---------------------------------------------------------------------------
# aiohttp app
# ---------------------------------------------------------------------------

def make_app(
    *,
    alert_db: str,
    outcome_db: str,
    health_provider: Callable[[], dict[str, Any]] | None = None,
    premarket_provider: Callable[[], Any] | None = None,
):
    from aiohttp import web

    alert_store = ExperimentalAlertStore(alert_db)
    outcome_store = ForwardOutcomeStore(outcome_db)
    board = ExperimentalDashboard(
        alert_store, outcome_store,
        health_provider=health_provider, premarket_provider=premarket_provider,
    )

    async def _index(request):  # noqa: ANN001
        return web.Response(text=board.render(), content_type="text/html")

    async def _health(request):  # noqa: ANN001
        return web.json_response({"ok": True, "counts": alert_store.counts()})

    async def _reject(request):  # noqa: ANN001
        if request.method not in ("GET", "HEAD"):
            return web.Response(status=405, text="GET/HEAD only")
        return web.Response(status=404, text="not found")

    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/__health", _health)
    app.router.add_route("*", "/{tail:.*}", _reject)
    return app


def main() -> None:  # pragma: no cover
    import argparse
    from pathlib import Path
    from aiohttp import web

    from talonx_signals.config import ExperimentalConfig

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    args = ap.parse_args()
    cfg = ExperimentalConfig()
    app = make_app(alert_db=str(cfg.state_dir / "exp_alerts.db"),
                   outcome_db=str(cfg.telemetry_db_path))
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
