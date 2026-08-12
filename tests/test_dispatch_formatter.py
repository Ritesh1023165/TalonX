"""
tests/test_dispatch_formatter.py
-------------------------------------
Tests talonx_dispatch.formatter's two Telegram Markdown formatters:

  - format_telegram_summary(alert, alert_id): the actual push -- built
    from a live ActionableAlert, must stay SHORT (no research writeup)
    and must include the alert ID + reply hint.
  - format_telegram_details(row): the full writeup sent back on a reply,
    built from an audit ROW DICT (not a Pydantic object) -- same content
    the old single format() used to always send.

No I/O, no bot token needed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_dispatch.formatter import (
    escape_markdown,
    format_telegram_details,
    format_telegram_long_term_alert,
    format_telegram_long_term_details,
    format_telegram_long_term_trade_execution,
    format_telegram_summary,
    format_telegram_trade_execution,
)
from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    LongTermActionableAlert,
    LongTermOrderType,
    LongTermTradeExecution,
    MoatRating,
    OrderType,
    PaperTradeExecution,
    ResearchVerdict,
    SignalDirection,
    TriggeringSignalRef,
)

NOW = datetime(2026, 8, 7, 14, 23, 0, tzinfo=timezone.utc)


def _alert(
    action: AlertAction = AlertAction.CONFIRMED_BULLISH,
    severity: AlertSeverity = AlertSeverity.WARNING,
    message: str = "RSI 24.3 oversold with 2.8x volume surge",
) -> ActionableAlert:
    return ActionableAlert(
        ticker="AAPL",
        action=action,
        severity=severity,
        rationale="rationale text",
        quant_direction=SignalDirection.BULLISH,
        research_verdict=ResearchVerdict.BULLISH,
        research_confidence=0.85,
        triggering_signal=TriggeringSignalRef(
            ticker="AAPL",
            signal_type="rsi_oversold_volume_surge",
            direction=SignalDirection.BULLISH,
            message=message,
            price=312.41,
            bar_timestamp=NOW,
        ),
        research_summary="Fundamentals support the move.",
        model_used="gemini-flash-latest",
        signal_received_at=NOW,
        report_received_at=NOW,
        correlated_at=NOW,
        published_at=NOW,
    )


def _row(
    alert_id: int = 47,
    action: AlertAction = AlertAction.CONFIRMED_BULLISH,
    severity: AlertSeverity = AlertSeverity.WARNING,
    rationale: str = "Quant signal (bullish): RSI oversold. Research verdict agrees: bullish at 85% confidence -- Fundamentals support the move.",
    key_findings: list[str] | None = None,
    risk_factors: list[str] | None = None,
) -> dict:
    """Matches AuditStore.get_by_id()'s return shape (talonx_dispatch/store.py's
    _row_to_dict) -- a plain dict with string action/severity/verdict, not enums."""
    return {
        "id": alert_id,
        "ticker": "AAPL",
        "action": action.value,
        "severity": severity.value,
        "rationale": rationale,
        "quant_direction": "bullish",
        "research_verdict": "bullish",
        "research_confidence": 0.85,
        "signal_type": "rsi_oversold_volume_surge",
        "price": 312.41,
        "research_summary": "Fundamentals support the move.",
        "key_findings": key_findings or [],
        "risk_factors": risk_factors or [],
        "model_used": "gemini-flash-latest",
        "correlated_at": NOW.isoformat(),
        "received_at": NOW.isoformat(),
        "telegram_sent": False,
        "telegram_sent_at": None,
        "telegram_error": None,
    }


def test_escape_markdown_escapes_the_four_special_characters():
    assert escape_markdown("under_score *star* `tick` [bracket]") == (
        "under\\_score \\*star\\* \\`tick\\` \\[bracket]"
    )


def test_escape_markdown_leaves_plain_text_untouched():
    assert escape_markdown("plain text 123") == "plain text 123"


# --- format_telegram_summary (the actual push) ----------------------------

def test_summary_includes_ticker_price_confidence_and_id():
    text = format_telegram_summary(_alert(), alert_id=47)
    assert "AAPL" in text
    assert "312.41" in text
    assert "85%" in text
    assert "#47" in text
    assert "Reply with 47" in text


def test_summary_includes_the_one_line_quant_trigger():
    text = format_telegram_summary(_alert(message="MACD crossed above signal line"), alert_id=47)
    assert "MACD crossed above signal line" in text


def test_summary_stays_short_and_omits_the_research_writeup():
    text = format_telegram_summary(_alert(), alert_id=47)
    # The full research summary/findings/risks never appear in the short push.
    assert "Fundamentals support the move." not in text
    assert "Key findings" not in text
    assert "Risks" not in text
    assert len(text) < 400


def test_summary_confirmed_bullish_uses_green_circle():
    text = format_telegram_summary(_alert(action=AlertAction.CONFIRMED_BULLISH), alert_id=1)
    assert "\U0001F7E2" in text
    assert "CONFIRMED BULLISH" in text


def test_summary_degraded_quant_alert_does_not_raise():
    text = format_telegram_summary(_alert(action=AlertAction.DEGRADED_QUANT_ALERT), alert_id=1)
    assert "DEGRADED" in text


def test_summary_critical_severity_adds_fire_prefix():
    text = format_telegram_summary(_alert(severity=AlertSeverity.CRITICAL), alert_id=1)
    assert text.startswith("\U0001F525")


def test_summary_includes_the_triggered_timestamp():
    text = format_telegram_summary(_alert(), alert_id=47)
    assert "2026-08-07 14:23 UTC" in text


def test_summary_includes_company_name_when_given():
    text = format_telegram_summary(_alert(), alert_id=47, company_name="Apple Inc.")
    assert "`AAPL` (Apple Inc.)" in text


def test_summary_omits_company_name_when_not_given():
    text = format_telegram_summary(_alert(), alert_id=47)
    assert "(" not in text.split("•")[0]


def test_summary_escapes_special_characters_in_company_name():
    text = format_telegram_summary(_alert(), alert_id=47, company_name="Foo_Bar*Corp")
    assert "Foo\\_Bar\\*Corp" in text


# --- format_telegram_details (sent back on a reply) ------------------------

def test_details_includes_ticker_price_verdict_and_id():
    text = format_telegram_details(_row(alert_id=47))
    assert "AAPL" in text
    assert "312.41" in text
    assert "bullish" in text
    assert "85%" in text
    assert "#47" in text


def test_details_confirmed_bearish_uses_red_circle():
    text = format_telegram_details(_row(action=AlertAction.CONFIRMED_BEARISH))
    assert "\U0001F534" in text
    assert "CONFIRMED BEARISH" in text


def test_details_contradicted_uses_warning_label():
    text = format_telegram_details(_row(action=AlertAction.CONTRADICTED))
    assert "CONTRADICTED" in text


def test_details_degraded_quant_alert_does_not_raise():
    # Regression coverage: _ACTION_EMOJI/_ACTION_LABEL are plain dict
    # lookups with no default -- adding a new AlertAction without adding
    # it to both would raise KeyError here and silently break Telegram
    # delivery for every degraded alert.
    text = format_telegram_details(_row(action=AlertAction.DEGRADED_QUANT_ALERT))
    assert "DEGRADED" in text


def test_details_critical_severity_adds_fire_prefix():
    text = format_telegram_details(_row(severity=AlertSeverity.CRITICAL))
    assert text.startswith("\U0001F525")


def test_details_non_critical_severity_has_no_fire_prefix():
    text = format_telegram_details(_row(severity=AlertSeverity.WARNING))
    assert not text.startswith("\U0001F525")


def test_details_includes_key_findings_and_risk_factors_as_bullets():
    text = format_telegram_details(_row(key_findings=["Finding one"], risk_factors=["Risk one"]))
    assert "Key findings:" in text
    assert "• Finding one" in text
    assert "Risks:" in text
    assert "• Risk one" in text


def test_details_omits_sections_when_lists_empty():
    text = format_telegram_details(_row(key_findings=[], risk_factors=[]))
    assert "Key findings:" not in text
    assert "Risks:" not in text


def test_details_escapes_special_characters_in_dynamic_text():
    text = format_telegram_details(_row(rationale="Growth in *services* and R_D spend"))
    assert "\\*services\\*" in text
    assert "R\\_D" in text


def test_details_truncates_very_long_rationale():
    text = format_telegram_details(_row(rationale="x" * 2000))
    assert "…" in text
    assert len(text) < 2000 + 500  # generous bound; just proving truncation happened


def test_details_formats_the_correlated_at_timestamp():
    text = format_telegram_details(_row())
    assert "2026-08-07 14:23 UTC" in text


# --- format_telegram_trade_execution (paper trading, decoupled push) -------

def _execution(
    order_type: OrderType = OrderType.SELL,
    entry_price: float | None = 135.00,
    execution_price: float = 135.60,
    realized_pnl_usd: float | None = 44.81,
    realized_pnl_pct: float | None = 0.45,
    session_realized_pnl_usd: float = 177.68,
    session_realized_pnl_pct: float = 1.78,
    portfolio_cash_after: float = 10177.68,
) -> PaperTradeExecution:
    return PaperTradeExecution(
        trade_id=12, ticker="SPCX", order_type=order_type,
        execution_price=execution_price, shares=18.5185, position_cost=2500.0,
        entry_price=entry_price, realized_pnl_usd=realized_pnl_usd, realized_pnl_pct=realized_pnl_pct,
        portfolio_cash_after=portfolio_cash_after, triggering_action=AlertAction.CONTRADICTED,
        session_realized_pnl_usd=session_realized_pnl_usd, session_realized_pnl_pct=session_realized_pnl_pct,
        timestamp=NOW,
    )


def test_trade_execution_sell_includes_entry_exit_and_pnl():
    text = format_telegram_trade_execution(_execution())
    assert "SPCX" in text
    assert "SELL EXECUTED" in text
    assert "135.00" in text
    assert "135.60" in text
    assert "+$44.81" in text
    assert "+0.45%" in text
    assert "10,177.68" in text


def test_trade_execution_sell_shows_negative_pnl_without_a_plus_sign():
    text = format_telegram_trade_execution(
        _execution(realized_pnl_usd=-50.0, realized_pnl_pct=-2.0, session_realized_pnl_usd=-10.0, session_realized_pnl_pct=-0.1)
    )
    assert "$-50.00" in text
    assert "+$" not in text.split("\n")[3]  # the Trade PnL line specifically (after ticker + timestamp + entry/exit)


def test_trade_execution_sell_shows_reversal_signal_reason():
    text = format_telegram_trade_execution(_execution())  # default triggering_action=CONTRADICTED
    assert "(reversal signal)" in text


def test_trade_execution_sell_shows_stop_loss_reason():
    text = format_telegram_trade_execution(
        PaperTradeExecution(
            trade_id=12, ticker="SPCX", order_type=OrderType.SELL, execution_price=134.50,
            shares=18.5185, position_cost=2500.0, entry_price=135.00,
            realized_pnl_usd=-9.26, realized_pnl_pct=-0.37, portfolio_cash_after=10000.0,
            triggering_action=AlertAction.STOP_LOSS_EXIT,
            session_realized_pnl_usd=0.0, session_realized_pnl_pct=0.0, timestamp=NOW,
        )
    )
    assert "(stop-loss)" in text


def test_trade_execution_includes_the_timestamp():
    text = format_telegram_trade_execution(_execution())
    assert "2026-08-07 14:23 UTC" in text


def test_trade_execution_includes_company_name_when_given():
    text = format_telegram_trade_execution(_execution(), company_name="SpaceX Holdings")
    assert "`SPCX` (SpaceX Holdings)" in text


def test_trade_execution_buy_includes_company_name_and_timestamp():
    execution = PaperTradeExecution(
        trade_id=5, ticker="NVDA", order_type=OrderType.BUY, execution_price=131.50,
        shares=19.011, position_cost=2500.0, portfolio_cash_after=7500.0,
        triggering_action=AlertAction.CONFIRMED_BULLISH,
        session_realized_pnl_usd=0.0, session_realized_pnl_pct=0.0, timestamp=NOW,
    )
    text = format_telegram_trade_execution(execution, company_name="NVIDIA Corporation")
    assert "`NVDA` (NVIDIA Corporation)" in text
    assert "2026-08-07 14:23 UTC" in text


def test_trade_execution_sell_shows_take_profit_reason():
    text = format_telegram_trade_execution(
        PaperTradeExecution(
            trade_id=12, ticker="SPCX", order_type=OrderType.SELL, execution_price=136.35,
            shares=18.5185, position_cost=2500.0, entry_price=135.00,
            realized_pnl_usd=25.0, realized_pnl_pct=1.0, portfolio_cash_after=10025.0,
            triggering_action=AlertAction.TAKE_PROFIT_EXIT,
            session_realized_pnl_usd=0.0, session_realized_pnl_pct=0.0, timestamp=NOW,
        )
    )
    assert "(take-profit)" in text


def test_trade_execution_buy_shows_shares_price_and_cash():
    execution = PaperTradeExecution(
        trade_id=5, ticker="NVDA", order_type=OrderType.BUY, execution_price=131.50,
        shares=19.011, position_cost=2500.0, portfolio_cash_after=7500.0,
        triggering_action=AlertAction.CONFIRMED_BULLISH,
        session_realized_pnl_usd=0.0, session_realized_pnl_pct=0.0, timestamp=NOW,
    )
    text = format_telegram_trade_execution(execution)
    assert "NVDA" in text
    assert "BUY EXECUTED" in text
    assert "131.50" in text
    assert "7,500.00" in text


# ==========================================================================
# Phase 2 LONG_TERM path
# ==========================================================================

def _long_term_alert(action: AlertAction = AlertAction.HIGH_CONVICTION_BUY, severity: AlertSeverity = AlertSeverity.CRITICAL) -> LongTermActionableAlert:
    return LongTermActionableAlert(
        ticker="AAPL", action=action, severity=severity,
        rationale="FY2025 fundamentals clear thresholds -- quality score 8/10, wide moat.",
        quality_score=8, moat_rating=MoatRating.WIDE, market_price=75.0,
        intrinsic_fair_value=100.0, margin_of_safety_pct=0.25,
        capital_allocation_assessment="Disciplined buybacks.",
        key_findings=["Strong recurring revenue"], risk_factors=["Regulatory scrutiny"],
        model_used="gemini-flash-latest", correlated_at=NOW, published_at=NOW,
    )


def test_long_term_alert_includes_ticker_price_fair_value_and_id():
    text = format_telegram_long_term_alert(_long_term_alert(), alert_id=12)
    assert "AAPL" in text
    assert "75.00" in text
    assert "100.00" in text
    # "LT" prefix distinguishes this ID space from the intraday alerts
    # table's -- both start their own AUTOINCREMENT sequence at 1, so a
    # bare "#12" would be ambiguous between the two.
    assert "#LT12" in text
    assert "Reply with LT12" in text


def test_long_term_alert_high_conviction_buy_uses_green_circle():
    text = format_telegram_long_term_alert(_long_term_alert(AlertAction.HIGH_CONVICTION_BUY), alert_id=1)
    assert "\U0001F7E2" in text
    assert "HIGH CONVICTION BUY" in text


def test_long_term_alert_under_perform_rebalance_uses_red_circle():
    text = format_telegram_long_term_alert(_long_term_alert(AlertAction.UNDER_PERFORM_REBALANCE), alert_id=1)
    assert "\U0001F534" in text
    assert "FUNDAMENTAL STOP" in text


def test_long_term_alert_shows_margin_of_safety_quality_and_moat():
    text = format_telegram_long_term_alert(_long_term_alert(), alert_id=1)
    assert "+25.0%" in text
    assert "8/10" in text
    assert "WIDE" in text


def test_long_term_alert_shows_valuation_exit_target():
    text = format_telegram_long_term_alert(_long_term_alert(), alert_id=1)
    assert "120.00" in text  # 1.20 * fair_value(100.00)


def test_long_term_alert_shows_holding_horizon():
    text = format_telegram_long_term_alert(_long_term_alert(), alert_id=1)
    assert "6-24 months" in text


def test_long_term_alert_negative_margin_of_safety_has_no_plus_sign():
    alert = _long_term_alert(AlertAction.TAKE_PROFIT_REBALANCE)
    alert = alert.model_copy(update={"margin_of_safety_pct": -0.15})
    text = format_telegram_long_term_alert(alert, alert_id=1)
    assert "-15.0%" in text
    assert "+-15.0%" not in text


def test_long_term_alert_unknown_action_does_not_raise():
    """Regression coverage for the exact KeyError class DEGRADED_QUANT_ALERT
    hit earlier this project -- .get() with a default must hold for any
    future new long-term action value too."""
    text = format_telegram_long_term_alert(_long_term_alert(AlertAction.HOLD_QUALITY), alert_id=1)
    assert "HOLD (QUALITY)" in text


def test_long_term_alert_includes_company_name_when_given():
    text = format_telegram_long_term_alert(_long_term_alert(), alert_id=1, company_name="Apple Inc.")
    assert "`AAPL` (Apple Inc.)" in text


def _long_term_row(
    alert_id: int = 47, action: str = "high_conviction_buy",
    key_findings: list[str] | None = None, risk_factors: list[str] | None = None,
) -> dict:
    """Matches AuditStore.get_long_term_by_id()'s return shape."""
    return {
        "id": alert_id, "ticker": "AAPL", "action": action, "severity": "critical",
        "rationale": "FY2025 fundamentals clear thresholds -- quality score 8/10, wide moat.",
        "quality_score": 8, "moat_rating": "wide", "market_price": 75.0,
        "intrinsic_fair_value": 100.0, "margin_of_safety_pct": 0.25,
        "capital_allocation_assessment": "Disciplined buybacks and reinvestment.",
        "key_findings": key_findings or [], "risk_factors": risk_factors or [],
        "model_used": "gemini-flash-latest", "correlated_at": NOW.isoformat(),
        "received_at": NOW.isoformat(), "telegram_sent": False,
        "telegram_sent_at": None, "telegram_error": None,
    }


def test_long_term_details_includes_ticker_price_and_id():
    text = format_telegram_long_term_details(_long_term_row())
    assert "AAPL" in text
    assert "75.00" in text
    assert "100.00" in text
    assert "#LT47" in text


def test_long_term_details_includes_capital_allocation_assessment():
    text = format_telegram_long_term_details(_long_term_row())
    assert "Disciplined buybacks and reinvestment." in text


def test_long_term_details_includes_key_findings_and_risks_as_bullets():
    text = format_telegram_long_term_details(
        _long_term_row(key_findings=["Finding one"], risk_factors=["Risk one"])
    )
    assert "Key findings:" in text
    assert "• Finding one" in text
    assert "Risks:" in text
    assert "• Risk one" in text


def test_long_term_details_omits_sections_when_lists_empty():
    text = format_telegram_long_term_details(_long_term_row(key_findings=[], risk_factors=[]))
    assert "Key findings:" not in text
    assert "Risks:" not in text


def test_long_term_details_under_perform_rebalance_does_not_raise():
    text = format_telegram_long_term_details(_long_term_row(action="under_perform_rebalance"))
    assert "FUNDAMENTAL STOP" in text


def test_long_term_details_formats_the_correlated_at_timestamp():
    text = format_telegram_long_term_details(_long_term_row())
    assert "2026-08-07 14:23 UTC" in text


def _long_term_execution(order_type: LongTermOrderType = LongTermOrderType.BUY, **overrides) -> LongTermTradeExecution:
    defaults = dict(
        trade_id=7, ticker="AAPL", order_type=order_type, execution_price=100.0,
        shares=20.0, contribution_cost=2000.0, avg_cost_basis_after=100.0, total_shares_after=20.0,
        portfolio_cash_after=18000.0, triggering_action=AlertAction.HIGH_CONVICTION_BUY, timestamp=NOW,
    )
    defaults.update(overrides)
    return LongTermTradeExecution(**defaults)


def test_long_term_trade_execution_buy_shows_position_opened():
    text = format_telegram_long_term_trade_execution(_long_term_execution(LongTermOrderType.BUY))
    assert "POSITION OPENED" in text
    assert "AAPL" in text
    assert "20.0000 shares" in text
    assert "18,000.00" in text


def test_long_term_trade_execution_dca_shows_new_avg_cost():
    execution = _long_term_execution(
        LongTermOrderType.DCA_CONTRIBUTION, shares=4.5, contribution_cost=500.0,
        avg_cost_basis_after=110.0, total_shares_after=24.5, triggering_action=AlertAction.DCA_CONTRIBUTION,
    )
    text = format_telegram_long_term_trade_execution(execution)
    assert "DCA CONTRIBUTION" in text
    assert "110.00" in text
    assert "24.5000" in text


def test_long_term_trade_execution_full_exit_shows_holding_period():
    execution = _long_term_execution(
        LongTermOrderType.SELL, shares=20.0, avg_cost_basis_after=None, total_shares_after=None,
        realized_pnl_usd=200.0, realized_pnl_pct=10.0, holding_period_days=200,
        triggering_action=AlertAction.UNDER_PERFORM_REBALANCE,
    )
    text = format_telegram_long_term_trade_execution(execution)
    assert "FULL EXIT" in text
    assert "fundamental stop" in text
    assert "Held 200 day(s)" in text
    assert "+$200.00" in text
    assert "Remaining" not in text


def test_long_term_trade_execution_partial_trim_shows_remaining_shares():
    execution = _long_term_execution(
        LongTermOrderType.SELL, shares=9.9, avg_cost_basis_after=100.0, total_shares_after=20.1,
        realized_pnl_usd=198.0, realized_pnl_pct=20.0, holding_period_days=90,
        triggering_action=AlertAction.TAKE_PROFIT_REBALANCE,
    )
    text = format_telegram_long_term_trade_execution(execution)
    assert "PARTIAL TRIM" in text
    assert "take-profit rebalance" in text
    assert "Remaining: 20.1000 shares" in text


def test_long_term_trade_execution_negative_pnl_has_no_plus_sign():
    execution = _long_term_execution(
        LongTermOrderType.SELL, shares=10.0, avg_cost_basis_after=None, total_shares_after=None,
        realized_pnl_usd=-50.0, realized_pnl_pct=-5.0, holding_period_days=30,
        triggering_action=AlertAction.UNDER_PERFORM_REBALANCE,
    )
    text = format_telegram_long_term_trade_execution(execution)
    assert "$-50.00" in text
    assert "+$-50.00" not in text


def test_long_term_trade_execution_includes_company_name():
    text = format_telegram_long_term_trade_execution(_long_term_execution(), company_name="Apple Inc.")
    assert "`AAPL` (Apple Inc.)" in text
