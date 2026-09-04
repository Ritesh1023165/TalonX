"""Task 99A S4 -- pure Telegram render functions for the restored alert
families. No I/O. Telegram LEGACY "Markdown" parse mode (escape only
``_ * ` [``). Every function ends with a ``Reply <ID> for details`` line whose
ID is the row's deterministic public id.

Wording rule (S4.2): the numeric strength signal is ALWAYS labelled
``Setup Score`` / ``Confluence`` -- never "confidence", "probability",
"win rate", or "N% chance". ``assert_no_predictive_language`` enforces it and
is called by the dispatcher before any send.
"""

from __future__ import annotations

import re
from typing import Any

_MD_ESCAPE = re.compile(r"([_*`\[])")

# Case-insensitive phrases that must never appear in a rendered card.
_BANNED = (
    r"\bwin\s*rate\b",
    r"\bprobability\s+of\s+profit\b",
    r"\bchance\s+of\s+profit\b",
    r"\b\d{1,3}\s*%\s*(?:chance|probability|confidence|win)\b",
    r"\bconfidence\s*[:=]\s*\d",
    r"\bexpected\s+return\b",
    r"\bguaranteed\b",
    r"\bprofit\s+probability\b",
    r"\bcalibrated\s+confidence\b",
)
_BANNED_RE = re.compile("|".join(_BANNED), re.IGNORECASE)


class PredictiveLanguageError(ValueError):
    pass


def assert_no_predictive_language(text: str) -> None:
    m = _BANNED_RE.search(text)
    if m:
        raise PredictiveLanguageError(f"predictive/probability wording in rendered card: {m.group(0)!r}")


def _raw(value: Any) -> str:
    """Controlled values (our own enum members / identifiers / hashtags) --
    per docs/modules/dispatch.md these are from our schemas and never need
    Markdown escaping. Also unwraps ``Enum`` -> its ``.value``."""
    if hasattr(value, "value"):
        value = value.value
    return str(value)


def _esc(value: Any) -> str:
    """Free text that may contain Markdown control chars (LLM output, company
    names, filing snippets)."""
    if hasattr(value, "value"):
        value = value.value
    return _MD_ESCAPE.sub(r"\\\1", str(value))


def _price(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(v: Any, digits: int = 2) -> str:
    try:
        return f"{float(v):+.{digits}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _company_suffix(company: str | None) -> str:
    return f" ({_esc(company)})" if company else ""


def _finish(lines: list[str], public_id: str) -> str:
    lines.append("")
    lines.append(f"Reply `{public_id}` for details")
    text = "\n".join(lines)
    assert_no_predictive_language(text)
    return text


# ---------------------------------------------------------------------------
# Directional setup cards
# ---------------------------------------------------------------------------

_DIR_HEAD = {
    "BULLISH": "\U0001F7E2 ⚡ BULLISH SETUP",
    "BEARISH": "\U0001F534 ⚡ BEARISH SETUP",
}


def render_directional_setup(alert: Any, *, company: str | None = None) -> str:
    d = alert if isinstance(alert, dict) else alert.model_dump()
    direction = _raw(d["direction"])
    lines = [
        f"{_DIR_HEAD.get(direction, direction)} | `{_raw(d['symbol'])}`{_company_suffix(company)}",
        "─" * 22,
        f"Price: {_price(d['price'])}  |  Session: {_raw(d['session'])}",
        f"Setup: {_raw(d['setup_type'])}",
    ]
    score = d.get("setup_score")
    if score is not None:
        lines.append(f"Setup Score: {int(score)}/3  (confluence -- not a probability)")
    if d.get("message"):
        lines.append(f"Reason: {_esc(d['message'])}")
    gate = _raw(d.get("trade_gate_status"))
    if gate and gate != "NOT_EVALUATED":
        rr = d.get("trade_gate_reject_reason")
        lines.append(f"Trade gate: {gate}" + (f" ({_raw(rr)})" if rr else ""))
    prof = _raw(d.get("profile"))
    if prof and prof != "FROZEN_CONTROL":
        lines.append(f"Profile: {prof} (experimental, informational)")
    lines.append("#SETUP")
    return _finish(lines, d["alert_id"])


def render_directional_details(row: dict) -> str:
    ev = row.get("evidence") or {}
    if isinstance(ev, str):
        import json
        try:
            ev = json.loads(ev)
        except ValueError:
            ev = {}
    lines = [
        f"{_DIR_HEAD.get(_raw(row['direction']), _raw(row['direction']))} -- FULL DETAIL",
        f"`{_raw(row['symbol'])}`  |  {_raw(row.get('profile', ''))}  |  horizon {_raw(row.get('horizon', 'INTRADAY_SHORT'))}",
        "─" * 22,
        f"Price at trigger: {_price(row['price'])}",
        f"Setup: {_raw(row['setup_type'])}   Setup Score: {row.get('setup_score')}/3",
        "",
        "Indicators:",
        f"  RSI {ev.get('rsi')}   MACD {ev.get('macd')} / signal {ev.get('macd_signal_line')}"
        + (f"   ({ev.get('macd_cross')} cross)" if ev.get("macd_cross") else ""),
        f"  Volume surge x {ev.get('volume_surge_ratio')}   ATR {ev.get('atr')} ({_pct(ev.get('atr_pct'))} of price)",
        f"  15m-200SMA {ev.get('htf_sma_200')}   trend_aligned={ev.get('trend_aligned')}"
        + (f"   price vs SMA {_pct(ev.get('price_vs_htf_sma_200_pct'))}" if ev.get('price_vs_htf_sma_200_pct') is not None else ""),
        f"  Pivots  R1 {ev.get('pivot_resistance')}  S1 {ev.get('pivot_support')}",
    ]
    if ev.get("nearby_catalyst"):
        lines.append(f"  Catalyst context: {_esc(ev['nearby_catalyst'])}")
    lines += [
        "",
        "Trade geometry (informational):",
        f"  stop {row.get('stop_price')}   target {row.get('target_price')}   R:R {row.get('risk_reward_ratio')}   path {_raw(row.get('geometry_path'))}",
        "",
        f"Trade gate: {_raw(row.get('trade_gate_status'))}"
        + (f" ({_raw(row.get('trade_gate_reject_reason'))})" if row.get("trade_gate_reject_reason") else ""),
        "",
        "Provenance:",
        f"  bar_timestamp {_raw(row.get('bar_timestamp'))}   generated_at {_raw(row.get('generated_at'))}",
        f"  source: talonx_signals.DirectionalAlertEngine <- talonx_quant.strategy.evaluate_signals",
        f"  alert_id {_raw(row['alert_id'])}",
    ]
    text = "\n".join(lines)
    assert_no_predictive_language(text)
    return text


# ---------------------------------------------------------------------------
# Experimental paper trade cards
# ---------------------------------------------------------------------------

def render_experimental_trade(trade: dict, *, company: str | None = None) -> str:
    side = _raw(trade["side"]).upper()
    head = "\U0001F9EA EXPERIMENTAL BUY (paper)" if side == "BUY" else "\U0001F9EA EXPERIMENTAL SELL / EXIT (paper)"
    lines = [
        f"{head} | `{_raw(trade['symbol'])}`{_company_suffix(company)}",
        "─" * 22,
        f"Profile: {_raw(trade.get('profile', 'EXPERIMENTAL_RELAXED_V1'))}  (paper-only, no real capital)",
    ]
    if side == "BUY":
        lines += [
            f"Entry: {_price(trade.get('entry'))}   Qty: {trade.get('quantity')}",
            f"Stop: {trade.get('stop')}   Target: {trade.get('target')}",
        ]
        if trade.get("admitted_by"):
            lines.append(f"Admitted by: {_raw(trade['admitted_by'])} (frozen control would have rejected)")
    else:
        lines += [
            f"Exit: {_price(trade.get('exit'))}   ({_raw(trade.get('exit_reason', 'signal_exit'))})",
            f"Entry was: {_price(trade.get('entry'))}   Qty: {trade.get('quantity')}",
        ]
        for label, key in (("Gross P&L", "gross_pnl"), ("Est. costs", "est_costs"),
                           ("Net P&L", "net_pnl"), ("R multiple", "r_multiple"),
                           ("MFE", "mfe"), ("MAE", "mae")):
            if trade.get(key) is not None:
                lines.append(f"{label}: {trade[key]}")
        lines.append("Closes an existing experimental LONG only -- never a short.")
    lines.append("#XP")
    return _finish(lines, trade["trade_id"])


# ---------------------------------------------------------------------------
# Intelligence-family cards (RADAR / event update) -- no fabricated valuation
# ---------------------------------------------------------------------------

def render_radar(row: dict) -> str:
    lines = [
        f"\U0001F4C5 UPCOMING EARNINGS RADAR | `{_esc(row['symbol'])}`{_company_suffix(row.get('company'))}",
        "─" * 22,
        f"Reports: {_esc(row.get('reporting_when', 'date TBC'))}",
    ]
    if row.get("current_price") is not None:
        lines.append(f"Current price: {_price(row['current_price'])} (reference only)")
    if row.get("holding_status"):
        lines.append(f"Watch/holding status: {_esc(row['holding_status'])}")
    if row.get("context"):
        lines.append(f"Context: {_esc(row['context'])}")
    lines.append("#RADAR")
    return _finish(lines, row["radar_id"])


def render_event_update(row: dict) -> str:
    lines = [
        f"\U0001F3DB️ POST-EARNINGS / FUNDAMENTAL UPDATE | `{_esc(row['symbol'])}`{_company_suffix(row.get('company'))}",
        "─" * 22,
        f"Event: {_esc(row.get('event_type', 'filing'))}",
        f"Filed: {_esc(row.get('accepted_at', 'n/a'))} (SEC acceptance timestamp)",
    ]
    if row.get("current_price") is not None:
        lines.append(f"Latest price: {_price(row['current_price'])} (reference only)")
    for line in (row.get("material_changes") or [])[:6]:
        lines.append(f"  - {_esc(line)}")
    if row.get("insider_context"):
        lines.append(f"Insider (open-market P/S): {_esc(row['insider_context'])}")
    if row.get("significance_band"):
        lines.append(f"Information significance: {_raw(row['significance_band'])} (attention priority, not a forecast)")
    lines.append("Source: SEC EDGAR + deterministic 96C/96D/96E engines. No fair-value / moat / direction estimate.")
    lines.append("#EVENT")
    return _finish(lines, row["event_id"])


def render_event_update_details(row: dict) -> str:
    """Fuller reply-for-details view for an `E…` id."""
    lines = [
        f"\U0001F3DB️ POST-EARNINGS / FUNDAMENTAL UPDATE -- FULL DETAIL",
        f"`{_esc(row['symbol'])}`{_company_suffix(row.get('company'))}",
        "─" * 22,
        f"Event / item: {_esc(row.get('event_type'))}",
        f"Accession: {_raw(row.get('accession', 'n/a'))}",
        f"SEC acceptance: {_esc(row.get('accepted_at', 'n/a'))}"
        + (f"  ({_raw(row.get('session_bucket'))})" if row.get("session_bucket") else ""),
    ]
    mc = row.get("material_changes") or []
    if mc:
        lines.append("")
        lines.append("What changed (deterministic 96C):")
        for line in mc:
            lines.append(f"  - {_esc(line)}")
    if row.get("insider_context"):
        lines.append("")
        lines.append(f"Insider context (96D): {_esc(row['insider_context'])}")
    reasons = row.get("significance_reasons") or []
    if row.get("significance_band") or reasons:
        lines.append("")
        lines.append(f"Information significance (96E): {_raw(row.get('significance_band', 'n/a'))} "
                     "-- attention priority, NOT a forecast / direction / return")
        for r in reasons:
            lines.append(f"  - {_esc(r)}")
    lines += [
        "",
        "Provenance:",
        f"  source: SEC EDGAR via talonx_ingest.intelligence (96A/96B); read via IntelligenceReadAPI",
        f"  filing: {_raw(row.get('evidence_url', 'n/a'))}",
        f"  96A event_id: {_raw(row.get('source_event_id', 'n/a'))}",
        f"  dashboard evidence: http://127.0.0.1:8760/evidence/event/{_raw(row.get('source_event_id', ''))}",
        f"  card id: {_raw(row['event_id'])}",
        "",
        "No fair value / moat / margin-of-safety (no valid free point-in-time source). Descriptive only.",
    ]
    text = "\n".join(lines)
    assert_no_predictive_language(text)
    return text


def render_radar_details(row: dict) -> str:
    """Fuller reply-for-details view for an `R…` id."""
    lines = [
        f"\U0001F4C5 UPCOMING EARNINGS RADAR -- FULL DETAIL",
        f"`{_esc(row['symbol'])}`{_company_suffix(row.get('company'))}",
        "─" * 22,
        f"Expected report: {_esc(row.get('reporting_when', 'date TBC'))}",
        f"Context: {_esc(row.get('context', ''))}",
    ]
    if row.get("current_price") is not None:
        lines.append(f"Current price: {_price(row['current_price'])} (reference only)")
    if row.get("holding_status"):
        lines.append(f"Watch / holding status: {_esc(row['holding_status'])}")
    lines += [
        "",
        "Provenance:",
        "  source: talonx_watchlist.upcoming_earnings (yfinance `.calendar`, free / £0)",
        "  synced by: run_talonx periodic earnings-calendar sync loop",
        "  note: date is an ESTIMATE; session (BMO/AMC) usually UNSPECIFIED from Yahoo",
        f"  card id: {_raw(row['radar_id'])}",
        "",
        "No fair value / moat / margin-of-safety shown (no valid free source).",
    ]
    text = "\n".join(lines)
    assert_no_predictive_language(text)
    return text
