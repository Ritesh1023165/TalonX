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

from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    LongTermActionableAlert,
    LongTermOrderType,
    LongTermTradeExecution,
    OrderType,
    PaperTradeExecution,
)

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

_EXIT_REASON_LABEL = {
    AlertAction.CONFIRMED_BEARISH: "reversal signal",
    AlertAction.CONTRADICTED: "reversal signal",
    AlertAction.STOP_LOSS_EXIT: "stop-loss",
    AlertAction.TAKE_PROFIT_EXIT: "take-profit",
}

_LONG_TERM_ACTION_EMOJI = {
    AlertAction.HIGH_CONVICTION_BUY: "\U0001F7E2",  # green circle
    AlertAction.HOLD_QUALITY: "\U0001F535",  # blue circle
    AlertAction.TAKE_PROFIT_REBALANCE: "\U0001F7E1",  # yellow circle
    AlertAction.UNDER_PERFORM_REBALANCE: "\U0001F534",  # red circle
}

_LONG_TERM_ACTION_LABEL = {
    AlertAction.HIGH_CONVICTION_BUY: "HIGH CONVICTION BUY",
    AlertAction.HOLD_QUALITY: "HOLD (QUALITY)",
    AlertAction.TAKE_PROFIT_REBALANCE: "TAKE PROFIT / REBALANCE",
    AlertAction.UNDER_PERFORM_REBALANCE: "UNDERPERFORM — FUNDAMENTAL STOP",
}

_LONG_TERM_EXIT_REASON_LABEL = {
    AlertAction.TAKE_PROFIT_REBALANCE: "take-profit rebalance",
    AlertAction.UNDER_PERFORM_REBALANCE: "fundamental stop",
}

# Matches talonx_core's default valuation_premium_pct (20% above fair
# value triggers TAKE_PROFIT_REBALANCE) -- a fixed display constant, not
# read from config (formatter.py is deliberately I/O- and config-free);
# if the real threshold is ever tuned away from the default, this line
# is cosmetic/approximate only, not authoritative -- the alert itself
# already fired using the real configured value.
_VALUATION_EXIT_PREMIUM = 1.20
_HOLDING_HORIZON_TEXT = "6-24 months, quarterly review"


def escape_markdown(text: str) -> str:
    """Escapes the 4 characters Telegram's legacy Markdown mode treats as special."""
    for ch in _MARKDOWN_SPECIAL_CHARS:
        text = text.replace(ch, "\\" + ch)
    return text


def format_telegram_summary(alert: ActionableAlert, alert_id: int, company_name: str | None = None) -> str:
    emoji = _ACTION_EMOJI[alert.action]
    label = _ACTION_LABEL[alert.action]
    severity_prefix = _SEVERITY_PREFIX[alert.severity]
    ticker_suffix = f" ({escape_markdown(company_name)})" if company_name else ""

    lines = [
        f"{severity_prefix}{emoji} *{label}* — `{alert.ticker}`{ticker_suffix}  •  #{alert_id}",
        f"Price: ${alert.triggering_signal.price:,.2f}  |  Confidence: {alert.research_confidence:.0%}",
        f"\U0001F550 {_format_timestamp(alert.correlated_at)}",
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


def format_telegram_trade_execution(execution: PaperTradeExecution, company_name: str | None = None) -> str:
    """
    The paper-trading notification -- SEPARATE from and decoupled from
    format_telegram_summary's alert push (not appended to it), so a
    trade execution doesn't reinstate a long combined message. Short by
    design, same as every other push this module sends.
    """
    ticker_suffix = f" ({escape_markdown(company_name)})" if company_name else ""
    timestamp_line = f"\U0001F550 {_format_timestamp(execution.timestamp)}"

    if execution.order_type == OrderType.BUY:
        lines = [
            f"\U0001F4B0 *BUY EXECUTED* — `{execution.ticker}`{ticker_suffix}",
            timestamp_line,
            f"{execution.shares:.4f} shares @ ${execution.execution_price:,.2f} "
            f"(${execution.position_cost:,.2f})",
            f"Cash: ${execution.portfolio_cash_after:,.2f}",
        ]
    else:
        pnl_sign = "+" if (execution.realized_pnl_usd or 0) >= 0 else ""
        session_sign = "+" if execution.session_realized_pnl_usd >= 0 else ""
        # .get() with a default, never a bare index -- a future new
        # triggering_action value must not be able to KeyError this push
        # (see DEGRADED_QUANT_ALERT's earlier history in this project).
        reason = _EXIT_REASON_LABEL.get(execution.triggering_action, "")
        reason_suffix = f" ({reason})" if reason else ""
        lines = [
            f"\U0001F4B0 *SELL EXECUTED* — `{execution.ticker}`{ticker_suffix}{reason_suffix}",
            timestamp_line,
            f"Entry ${execution.entry_price:,.2f} → Exit ${execution.execution_price:,.2f}",
            f"Trade PnL: {pnl_sign}${execution.realized_pnl_usd:,.2f} "
            f"({pnl_sign}{execution.realized_pnl_pct:.2f}%)",
            f"Session PnL: {session_sign}${execution.session_realized_pnl_usd:,.2f} "
            f"({session_sign}{execution.session_realized_pnl_pct:.2f}%) | "
            f"Cash: ${execution.portfolio_cash_after:,.2f}",
        ]
    return "\n".join(lines)


def format_telegram_long_term_alert(
    alert: LongTermActionableAlert, alert_id: int, company_name: str | None = None,
) -> str:
    """The LONG_TERM push -- per the spec's Module 5B: current price vs.
    fair value, margin of safety, quality/moat, the take-profit exit
    target, and expected holding horizon. `.get()` with a default (never
    a bare index) for the action maps -- same defensive posture the
    intraday formatter uses, since a future new long-term action value
    must not be able to KeyError this push."""
    emoji = _LONG_TERM_ACTION_EMOJI.get(alert.action, "ℹ️")
    label = _LONG_TERM_ACTION_LABEL.get(alert.action, alert.action.value.upper())
    severity_prefix = _SEVERITY_PREFIX[alert.severity]
    ticker_suffix = f" ({escape_markdown(company_name)})" if company_name else ""
    margin_sign = "+" if alert.margin_of_safety_pct >= 0 else ""
    exit_target = alert.intrinsic_fair_value * _VALUATION_EXIT_PREMIUM

    lines = [
        f"{severity_prefix}{emoji} *{label}* — `{alert.ticker}`{ticker_suffix}  •  #LT{alert_id}",
        f"\U0001F550 {_format_timestamp(alert.correlated_at)}",
        f"Price: ${alert.market_price:,.2f}  vs  Fair Value: ${alert.intrinsic_fair_value:,.2f}",
        f"Margin of Safety: {margin_sign}{alert.margin_of_safety_pct:.1%}",
        f"Quality: {alert.quality_score}/10  |  Moat: {alert.moat_rating.value.upper()}",
        f"Valuation exit target: ${exit_target:,.2f} (take-profit trim level)",
        f"Expected holding horizon: {_HOLDING_HORIZON_TEXT}",
        escape_markdown(_truncate(alert.rationale, 300)),
        "",
        f"_Reply with LT{alert_id} for full details_",
    ]
    return "\n".join(lines)


def format_telegram_long_term_details(row: dict) -> str:
    """The FULL long-term writeup, sent back when someone replies with
    "LT<id>" -- same "short push + full detail on demand" split the
    intraday format_telegram_details provides, built from a
    AuditStore.get_long_term_by_id()-shaped row dict (action/moat_rating
    come back as plain strings from sqlite, converted to the real enums
    here to reuse the same lookup dicts the push formatter uses)."""
    action = AlertAction(row["action"])
    emoji = _LONG_TERM_ACTION_EMOJI.get(action, "ℹ️")
    label = _LONG_TERM_ACTION_LABEL.get(action, action.value.upper())
    severity = AlertSeverity(row["severity"])
    severity_prefix = _SEVERITY_PREFIX[severity]
    margin_sign = "+" if row["margin_of_safety_pct"] >= 0 else ""
    exit_target = row["intrinsic_fair_value"] * _VALUATION_EXIT_PREMIUM

    lines = [
        f"{severity_prefix}{emoji} *{label}* — `{row['ticker']}`  •  #LT{row['id']}",
        "",
        f"Price: ${row['market_price']:,.2f}  vs  Fair Value: ${row['intrinsic_fair_value']:,.2f}",
        f"Margin of Safety: {margin_sign}{row['margin_of_safety_pct']:.1%}",
        f"Quality: {row['quality_score']}/10  |  Moat: {row['moat_rating'].upper()}",
        f"Valuation exit target: ${exit_target:,.2f}",
        f"Expected holding horizon: {_HOLDING_HORIZON_TEXT}",
        "",
        escape_markdown(_truncate(row["rationale"], 800)),
        "",
        f"*Capital allocation:* {escape_markdown(row['capital_allocation_assessment'])}",
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


def format_telegram_long_term_trade_execution(
    execution: LongTermTradeExecution, company_name: str | None = None,
) -> str:
    """The LONG_TERM paper-trading notification -- three distinct shapes
    (position opened, DCA contribution, partial/full exit), each SHORT
    by design, same as every other push this module sends."""
    ticker_suffix = f" ({escape_markdown(company_name)})" if company_name else ""
    timestamp_line = f"\U0001F550 {_format_timestamp(execution.timestamp)}"

    if execution.order_type == LongTermOrderType.BUY:
        lines = [
            f"\U0001F48E *POSITION OPENED* — `{execution.ticker}`{ticker_suffix}",
            timestamp_line,
            f"{execution.shares:.4f} shares @ ${execution.execution_price:,.2f} "
            f"(${execution.contribution_cost:,.2f})",
            f"Cash: ${execution.portfolio_cash_after:,.2f}",
        ]
    elif execution.order_type == LongTermOrderType.DCA_CONTRIBUTION:
        lines = [
            f"\U0001F504 *DCA CONTRIBUTION* — `{execution.ticker}`{ticker_suffix}",
            timestamp_line,
            f"+{execution.shares:.4f} shares @ ${execution.execution_price:,.2f} "
            f"(${execution.contribution_cost:,.2f})",
            f"New avg cost: ${execution.avg_cost_basis_after:,.2f}  |  "
            f"Total shares: {execution.total_shares_after:.4f}",
            f"Cash: ${execution.portfolio_cash_after:,.2f}",
        ]
    else:  # SELL -- partial trim or full exit
        pnl_sign = "+" if (execution.realized_pnl_usd or 0) >= 0 else ""
        reason = _LONG_TERM_EXIT_REASON_LABEL.get(execution.triggering_action, "")
        reason_suffix = f" ({reason})" if reason else ""
        full_exit = not execution.total_shares_after or execution.total_shares_after <= 0
        trim_label = "FULL EXIT" if full_exit else "PARTIAL TRIM"
        lines = [
            f"\U0001F4B0 *{trim_label}* — `{execution.ticker}`{ticker_suffix}{reason_suffix}",
            timestamp_line,
            f"{execution.shares:.4f} shares @ ${execution.execution_price:,.2f}",
            f"Realized PnL: {pnl_sign}${execution.realized_pnl_usd:,.2f} "
            f"({pnl_sign}{execution.realized_pnl_pct:.2f}%)",
        ]
        if execution.holding_period_days is not None:
            lines.append(f"Held {execution.holding_period_days} day(s)")
        if not full_exit:
            lines.append(
                f"Remaining: {execution.total_shares_after:.4f} shares @ "
                f"avg ${execution.avg_cost_basis_after:,.2f}"
            )
        lines.append(f"Cash: ${execution.portfolio_cash_after:,.2f}")
    return "\n".join(lines)


def _format_timestamp(value: datetime | str) -> str:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(value)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
