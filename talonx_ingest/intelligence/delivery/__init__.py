"""
talonx_ingest.intelligence.delivery
===================================
Telegram delivery for the Risk & Event Intelligence product.

This package **renders and delivers** the already-computed deterministic
intelligence — the Task 96A ``AlertCard`` plus the Task 96E
``InformationSignificance`` band + reasons, with the Task 96C
``what_changed`` and Task 96D ``InsiderActivity`` facts. It creates **no
new intelligence**: no recompute, no market-data fetch, no significance
logic, no direction, no AI, £0.

Isolation: nothing here imports ``talonx_quant``, ``talonx_core.decision``,
``talonx_paper``, ``talonx_piv``, ``redis``, or the quant-coupled
``talonx_dispatch`` modules (``consumer`` / ``app`` / ``formatter`` /
``schemas``). Only ``talonx_dispatch.telegram_client`` +
``talonx_dispatch.config`` are used, and only from the ``pipeline``
transport adapter.
"""
from talonx_ingest.intelligence.delivery.config import (
    DELIVERY_CHANNEL,
    RENDER_VERSION,
)
from talonx_ingest.intelligence.delivery.render_model import TelegramIntelligenceMessage
from talonx_ingest.intelligence.delivery.renderer import (
    render_compact,
    render_digest,
    render_expanded,
)

__all__ = [
    "RENDER_VERSION",
    "DELIVERY_CHANNEL",
    "TelegramIntelligenceMessage",
    "render_compact",
    "render_expanded",
    "render_digest",
]
