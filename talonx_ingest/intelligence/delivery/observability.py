"""
talonx_ingest.intelligence.delivery.observability
=================================================
Delivery counters for the event-intelligence Telegram path.

Kept deliberately SEPARATE from the quant-signal counters in
``talonx_dispatch`` / ``talonx_quant`` — this is product observability, not
trading-signal observability. Plain in-process counters; a caller that
wants persistence can snapshot ``as_dict()`` wherever it likes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeliveryMetrics:
    cards_rendered: int = 0
    queued_immediate: int = 0
    queued_digest: int = 0
    delivered: int = 0
    updates_sent: int = 0
    retries: int = 0
    failures: int = 0
    dedup_suppressed: int = 0
    noop_suppressed: int = 0
    size_truncations: int = 0
    claim_safety_rejections: int = 0
    dry_run_renders: int = 0

    _by_band: dict[str, int] = field(default_factory=dict)

    def record_render(self, band: str | None, *, truncated: bool) -> None:
        self.cards_rendered += 1
        if truncated:
            self.size_truncations += 1
        key = band or "NONE"
        self._by_band[key] = self._by_band.get(key, 0) + 1

    def record_enqueue(self, route: str, disposition: str) -> None:
        if route == "IMMEDIATE":
            self.queued_immediate += 1
        else:
            self.queued_digest += 1
        if disposition == "UPDATE":
            self.updates_sent += 0  # counted on actual send, not enqueue

    def record_suppressed(self, decision: str) -> None:
        if decision in ("SUPPRESS_DUPLICATE",):
            self.dedup_suppressed += 1
        elif decision in ("SUPPRESS_NOOP",):
            self.noop_suppressed += 1
        else:
            self.dedup_suppressed += 1

    def record_delivered(self, *, is_update: bool) -> None:
        self.delivered += 1
        if is_update:
            self.updates_sent += 1

    def record_retry(self) -> None:
        self.retries += 1

    def record_failure(self) -> None:
        self.failures += 1

    def record_claim_safety_rejection(self) -> None:
        self.claim_safety_rejections += 1

    def as_dict(self) -> dict:
        return {
            "cards_rendered": self.cards_rendered,
            "queued_immediate": self.queued_immediate,
            "queued_digest": self.queued_digest,
            "delivered": self.delivered,
            "updates_sent": self.updates_sent,
            "retries": self.retries,
            "failures": self.failures,
            "dedup_suppressed": self.dedup_suppressed,
            "noop_suppressed": self.noop_suppressed,
            "size_truncations": self.size_truncations,
            "claim_safety_rejections": self.claim_safety_rejections,
            "dry_run_renders": self.dry_run_renders,
            "by_band": dict(self._by_band),
        }
