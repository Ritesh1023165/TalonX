"""
talonx_ingest.intelligence.delivery.render_model
================================================
``TelegramIntelligenceMessage`` — the renderer's output contract.

It is a **view model derived from a Task 96A ``AlertCard``**, not a second
event DTO. It carries only presentation state (rendered text, parse mode,
tier, routing, truncation bookkeeping, content hash for update detection).
No predictive / directional field — ``extra="forbid"`` rejects any.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from talonx_ingest.intelligence.delivery.config import (
    DISABLE_WEB_PAGE_PREVIEW,
    PARSE_MODE,
    RENDER_VERSION,
)
from talonx_ingest.intelligence.domain import SignificanceBand

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class TelegramIntelligenceMessage(BaseModel):
    model_config = _FROZEN

    card_id: str                      # logical dedup key (== AlertCard.alert_id)
    event_id: str
    symbol: str

    band: SignificanceBand | None
    tier: str                         # COMPACT | EXPANDED | DIGEST
    route: str                        # IMMEDIATE | DIGEST

    text: str
    parse_mode: str = PARSE_MODE
    disable_web_page_preview: bool = DISABLE_WEB_PAGE_PREVIEW

    render_version: str = RENDER_VERSION
    content_hash: str

    char_len: int
    truncated: bool = False
    dropped_sections: tuple[str, ...] = ()
    evidence_urls: tuple[str, ...] = ()
    disclaimer_present: bool = True

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()
