"""
talonx_ingest.intelligence.dashboard.observability
==================================================
Dashboard request metrics. Deliberately SEPARATE from the quant-signal
counters in ``talonx_dispatch`` / ``talonx_quant`` — this is product
observability. Plain in-process counters; snapshot ``as_dict()`` anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DashboardMetrics:
    page_requests: int = 0
    api_requests: int = 0
    errors: int = 0
    not_found: int = 0
    empty_results: int = 0
    stale_source_views: int = 0
    deep_link_hits: int = 0
    claim_safety_rejections: int = 0

    _latency_ms: list[float] = field(default_factory=list)
    _by_route: dict[str, int] = field(default_factory=dict)

    def record_request(self, route: str, *, api: bool, latency_ms: float, status: int) -> None:
        if api:
            self.api_requests += 1
        else:
            self.page_requests += 1
        self._by_route[route] = self._by_route.get(route, 0) + 1
        self._latency_ms.append(round(latency_ms, 2))
        if len(self._latency_ms) > 2000:
            self._latency_ms = self._latency_ms[-2000:]
        if status == 404:
            self.not_found += 1
        elif status >= 500:
            self.errors += 1

    def record_empty(self) -> None:
        self.empty_results += 1

    def record_stale_view(self) -> None:
        self.stale_source_views += 1

    def record_deep_link(self) -> None:
        self.deep_link_hits += 1

    def record_claim_safety_rejection(self) -> None:
        self.claim_safety_rejections += 1
        self.errors += 1

    def _pctl(self, p: float) -> float:
        if not self._latency_ms:
            return 0.0
        s = sorted(self._latency_ms)
        return s[min(len(s) - 1, int(len(s) * p))]

    def as_dict(self) -> dict:
        return {
            "page_requests": self.page_requests,
            "api_requests": self.api_requests,
            "errors": self.errors,
            "not_found": self.not_found,
            "empty_results": self.empty_results,
            "stale_source_views": self.stale_source_views,
            "deep_link_hits": self.deep_link_hits,
            "claim_safety_rejections": self.claim_safety_rejections,
            "latency_ms_p50": self._pctl(0.50),
            "latency_ms_p95": self._pctl(0.95),
            "latency_ms_max": max(self._latency_ms) if self._latency_ms else 0.0,
            "by_route": dict(self._by_route),
        }
