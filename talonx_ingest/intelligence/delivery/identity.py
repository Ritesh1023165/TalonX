"""
talonx_ingest.intelligence.delivery.identity
============================================
Deterministic delivery identity.

``delivery_id = "{channel}:{card_id}:{render_version}"``
    Restart-safe. The same logical alert card, rendered by the same layout
    version, targeting the same channel, is one delivery. A render-version
    bump changes the id (so the new layout is a distinct delivery) but must
    NOT auto-resend old alerts — that is enforced by the outbox / update
    policy, not by the id alone.

``content_hash``
    sha256 of the rendered text. Two renders of the same card with byte-
    identical text collide; a genuine change to the surfaced facts changes
    it, which is what the update policy keys on.
"""
from __future__ import annotations

from talonx_ingest.intelligence.delivery.config import DELIVERY_CHANNEL, RENDER_VERSION
from talonx_ingest.intelligence.identity import source_hash


def delivery_id(
    card_id: str,
    *,
    channel: str = DELIVERY_CHANNEL,
    render_version: str = RENDER_VERSION,
) -> str:
    return f"{channel}:{card_id}:{render_version}"


def content_hash(text: str) -> str:
    return source_hash("telegram_intel_render@v1", text)
