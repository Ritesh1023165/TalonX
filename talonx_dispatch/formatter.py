"""
talonx_dispatch.formatter
------------------------------
Pure function: ActionableAlert -> Telegram Markdown text. No I/O, no
Redis, no Telegram client -- kept separate from telegram_client.py so the
formatting logic is trivially unit-testable without a bot token.

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

from talonx_dispatch.schemas import ActionableAlert, AlertAction, AlertSeverity

_ACTION_EMOJI = {
    AlertAction.CONFIRMED_BULLISH: "\U0001F7E2",  # green circle
    AlertAction.CONFIRMED_BEARISH: "\U0001F534",  # red circle
    AlertAction.CONTRADICTED: "⚠️",  # warning sign
}

_ACTION_LABEL = {
    AlertAction.CONFIRMED_BULLISH: "CONFIRMED BULLISH",
    AlertAction.CONFIRMED_BEARISH: "CONFIRMED BEARISH",
    AlertAction.CONTRADICTED: "CONTRADICTED",
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


def format_telegram_message(alert: ActionableAlert) -> str:
    emoji = _ACTION_EMOJI[alert.action]
    label = _ACTION_LABEL[alert.action]
    severity_prefix = _SEVERITY_PREFIX[alert.severity]

    lines = [
        f"{severity_prefix}{emoji} *{label}* — `{alert.ticker}`",
        "",
        f"Price: ${alert.triggering_signal.price:,.2f}",
        f"Quant: {escape_markdown(alert.triggering_signal.message)}",
        f"Research: {alert.research_verdict.value} ({alert.research_confidence:.0%} confidence)",
        "",
        escape_markdown(_truncate(alert.research_summary, 500)),
    ]

    if alert.key_findings:
        lines.append("")
        lines.append("*Key findings:*")
        lines.extend(f"• {escape_markdown(f)}" for f in alert.key_findings[:5])

    if alert.risk_factors:
        lines.append("")
        lines.append("*Risks:*")
        lines.extend(f"• {escape_markdown(r)}" for r in alert.risk_factors[:5])

    lines.append("")
    lines.append(
        f"_{escape_markdown(alert.model_used)} · "
        f"{alert.correlated_at.strftime('%Y-%m-%d %H:%M UTC')}_"
    )

    return "\n".join(lines)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
