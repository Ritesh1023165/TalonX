"""
talonx_v2.quant_bridge -- V2 Quant-stage representation (Phase 7)
==============================================================
Builds the smallest compatible Quant-stage signal for a detected
cluster episode.  It does NOT fabricate ATR / confluence / R:R -- those
are V1 semantics and do not belong to this phenomenon.  V2 carries
insider-cluster provenance instead.

The signal is published to ``talonx:v2:signal`` (its own channel) so it
enters the normal Quant -> Brain -> decision -> paper sequence without
touching the frozen ``talonx_quant`` scanner or its schema.
"""
from __future__ import annotations

from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.config import V2Config, V2_VERSION
from talonx_v2.liquidity import LiquidityResult
from talonx_v2.schemas import V2Direction, V2QuantSignal


def build_signal(
    episode: ClusterEpisode,
    liquidity: LiquidityResult,
    *,
    config: V2Config | None = None,
) -> V2QuantSignal:
    cfg = config or V2Config()
    reason = (
        f"{episode.n_distinct_owners} distinct insiders made open-market purchases "
        f"(SEC code {cfg.transaction_code}) in {episode.symbol} within "
        f"{cfg.cluster_window_trading_days} trading days; cluster became public on "
        f"{episode.activation_filing_date.isoformat()}."
    )
    return V2QuantSignal(
        signal_id=f"v2sig-{episode.episode_id}",
        strategy_version=V2_VERSION,
        symbol=episode.symbol,
        issuer_cik=episode.issuer_cik,
        direction=V2Direction.BULLISH,
        horizon_trading_days=cfg.hold_trading_days,
        paper_eligible=True,
        episode_id=episode.episode_id,
        distinct_owner_ciks=episode.distinct_owner_ciks,
        n_distinct_owners=episode.n_distinct_owners,
        aggregate_purchase_value=episode.aggregate_purchase_value,
        any_officer=episode.any_officer,
        any_director=episode.any_director,
        any_ten_percent=episode.any_ten_percent,
        causal_event_ts=episode.causal_event_ts,
        eligible_entry_session=episode.eligible_entry_session,
        reason=reason,
        liquidity_ok=liquidity.ok,
        liquidity_median_dollar_volume=liquidity.median_dollar_volume,
        liquidity_last_close=liquidity.last_close,
    )
