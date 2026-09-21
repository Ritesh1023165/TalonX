"""
talonx_v2.brain_bridge -- V2 Brain-stage contextualisation (Phase 8, 9)
====================================================================
Descriptive, deterministic contextualisation of a V2 Quant signal.

IMPORTANT: this does NOT reapply V1's ATR / confluence / R:R gates -- those
are irrelevant to the insider-cluster phenomenon (Task 110 Phase 7/8).
It also does NOT introduce predictive AI -- there is no LLM call here.

It maps a V2 signal to a BULLISH / BUY (or HOLD when the eligibility gate
already failed) and states the official-alert eligibility per the V2
contract (V2 is an OFFICIAL family, not Experimental).
"""
from __future__ import annotations

from talonx_v2.config import V2_STATUS, V2_VERSION
from talonx_v2.schemas import V2Action, V2Decision, V2Direction, V2QuantSignal

#: The V2 official-alert family name (allow-listed in
#: talonx_signals.external_boundary.EXTERNAL_ELIGIBLE_FAMILIES).
V2_OFFICIAL_FAMILY = "insider_buy_cluster_v2"


def contextualize(signal: V2QuantSignal) -> V2Decision:
    notes: list[str] = [
        f"strategy={V2_VERSION} status={V2_STATUS}",
        f"insiders={signal.n_distinct_owners} "
        f"(officer={signal.any_officer} director={signal.any_director} "
        f"ten_pct={signal.any_ten_percent})",
    ]
    if signal.aggregate_purchase_value:
        notes.append(f"aggregate open-market purchase ~${signal.aggregate_purchase_value:,.0f}")

    if not signal.liquidity_ok:
        return V2Decision(
            signal_id=signal.signal_id,
            episode_id=signal.episode_id,
            symbol=signal.symbol,
            strategy_version=V2_VERSION,
            direction=V2Direction.BULLISH,
            action=V2Action.HOLD,
            official_eligible=False,
            rationale=(
                "Insider buy-cluster observed, but the issuer fails the frozen "
                "liquidity / index-membership eligibility gate -- informational only, "
                "no paper entry."
            ),
            context_notes=tuple(notes + [
                f"liquidity: median$vol={signal.liquidity_median_dollar_volume}, "
                f"last_close={signal.liquidity_last_close} -> BLOCKED"
            ]),
            eligible_entry_session=signal.eligible_entry_session,
        )

    return V2Decision(
        signal_id=signal.signal_id,
        episode_id=signal.episode_id,
        symbol=signal.symbol,
        strategy_version=V2_VERSION,
        direction=V2Direction.BULLISH,
        action=V2Action.BUY,
        official_eligible=True,
        rationale=(
            f"{signal.n_distinct_owners} distinct insiders bought {signal.symbol} on the "
            f"open market within {signal.horizon_trading_days} trading days and the issuer "
            f"passes the frozen liquidity gate. Paper-entry eligible at the open of "
            f"{signal.eligible_entry_session.isoformat()}; planned {signal.horizon_trading_days}-"
            f"trading-day hold. PAPER CANDIDATE -- descriptive, not a profit claim."
        ),
        context_notes=tuple(notes),
        eligible_entry_session=signal.eligible_entry_session,
    )
