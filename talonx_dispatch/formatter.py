"""
talonx_dispatch.formatter
------------------------------
Two Telegram Markdown formatters, both pure functions -- no I/O, no
Redis, no Telegram client -- kept separate from telegram_client.py so the
formatting logic is trivially unit-testable without a bot token:

  - format_telegram_summary(alert, alert_id): the actual PUSH -- ticker,
    action, price, confidence, and the one-line quant trigger, plus the
    alert's ID and a reply-with-it-for-details hint. Deliberately short
    enough to read at a glance during a live session -- the full research
    writeup used to go out in every push, which is what this replaced it
    for. Takes the live ActionableAlert object (available at dispatch
    time in consumer.py).
  - format_telegram_details(row): the FULL writeup (rationale, key
    findings, risks, model/timestamp footer) -- what used to be the only
    format. Sent back by telegram_listener.py when someone replies to a
    push with its ID. Takes an AUDIT ROW DICT (AuditStore.get_by_id()'s
    return shape), not a live ActionableAlert -- by reply time the
    original in-memory object is long gone, but every field this needs
    is already a stored column. `action`/`severity` come back from
    sqlite as plain strings, so this converts them to the real enums
    first to reuse the same _ACTION_EMOJI/_ACTION_LABEL/_SEVERITY_PREFIX
    lookups as the summary formatter.

Uses Telegram's LEGACY "Markdown" parse mode, not "MarkdownV2" --
MarkdownV2 requires escaping a long list of characters
(_*[]()~`>#+-=|{}.!) that would routinely show up in Gemini-generated
research text, making it a much larger surface for a broken/garbled
message than this is worth. Legacy Markdown only requires escaping four
characters (_*`[), which _escape() below handles for any dynamic
(LLM-or-upstream-generated) text -- tickers/enums are from our own
schemas and never need escaping.
"""
from __future__ import annotations

from datetime import datetime

from talonx_dispatch.schemas import ActionableAlert, AlertAction, AlertSeverity

_ACTION_EMOJI = {
    AlertAction.CONFIRMED_BULLISH: "\U0001F7E2",  # green circle
    AlertAction.CONFIRMED_BEARISH: "\U0001F534",  # red circle
    AlertAction.CONTRADICTED: "⚠️",  # warning sign
    AlertAction.DEGRADED_QUANT_ALERT: "\U0001F6A7",  # construction sign -- quant-only, no research backing it
}

_ACTION_LABEL = {
    AlertAction.CONFIRMED_BULLISH: "CONFIRMED BULLISH",
    AlertAction.CONFIRMED_BEARISH: "CONFIRMED BEARISH",
    AlertAction.CONTRADICTED: "CONTRADICTED",
    AlertAction.DEGRADED_QUANT_ALERT: "DEGRADED (QUANT-ONLY)",
}

_SEVERITY_PREFIX = {
    AlertSeverity.CRITICAL: "\U0001F525 ",  # fire, for emphasis
    AlertSeverity.WARNING: "",
    AlertSeverity.INFO: "",
}

_MARKDOWN_SPECIAL_CHARS = ("_", "*", "`", "[")


def escape_markdown(text: str) -> str:
    """Escapes the 4 characters Telegram's legacy Markdown mode treats as special."""
    for ch in _MARKDOWN_SPECIAL_CHARS:
        text = text.replace(ch, "\\" + ch)
    return text


def format_telegram_summary(alert: ActionableAlert, alert_id: int) -> str:
    emoji = _ACTION_EMOJI[alert.action]
    label = _ACTION_LABEL[alert.action]
    severity_prefix = _SEVERITY_PREFIX[alert.severity]

    lines = [
        f"{severity_prefix}{emoji} *{label}* — `{alert.ticker}`  •  #{alert_id}",
        f"Price: ${alert.triggering_signal.price:,.2f}  |  Confidence: {alert.research_confidence:.0%}",
        escape_markdown(_truncate(alert.triggering_signal.message, 200)),
        "",
        f"_Reply with {alert_id} for full details_",
    ]
    return "\n".join(lines)


def format_telegram_details(row: dict) -> str:
    action = AlertAction(row["action"])
    severity = AlertSeverity(row["severity"])
    emoji = _ACTION_EMOJI[action]
    label = _ACTION_LABEL[action]
    severity_prefix = _SEVERITY_PREFIX[severity]

    lines = [
        f"{severity_prefix}{emoji} *{label}* — `{row['ticker']}`  •  #{row['id']}",
        "",
        f"Price: ${row['price']:,.2f}",
        f"Research: {row['research_verdict']} ({row['research_confidence']:.0%} confidence)",
        "",
        escape_markdown(_truncate(row["rationale"], 800)),
    ]

    if row["key_findings"]:
        lines.append("")
        lines.append("*Key findings:*")
        lines.extend(f"• {escape_markdown(f)}" for f in row["key_findings"][:5])

    if row["risk_factors"]:
        lines.append("")
        lines.append("*Risks:*")
        lines.extend(f"• {escape_markdown(r)}" for r in row["risk_factors"][:5])

    lines.append("")
    lines.append(f"_{escape_markdown(row['model_used'])} · {_format_timestamp(row['correlated_at'])}_")

    return "\n".join(lines)


def _format_timestamp(iso_string: str) -> str:
    try:
        return datetime.fromisoformat(iso_string).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso_string


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
