"""Task 78I Stage 3 -- Gemini enrichment, additive-only, decision_id-keyed.

Wraps `talonx_brain.llm`'s `_BaseResearchChain` interface
(`generate(signal, citations) -> _LLMFindings`-shaped object, `async`) via
duck typing -- reused, not reimplemented. Production wiring constructs the
REAL `GeminiResearchChain`/`OllamaResearchChain`; every test/rehearsal
injects a fake chain instead (`request`/`dispatch_pending` never construct
a chain themselves).

`talonx_brain.store.BrainStatsStore` has no `decision_id` concept at all
(keys only by `(date, ticker, category, horizon)` -- see that module) and
its `ResearchReport` schema is tied to `talonx:reports:brain`'s own
Redis-channel-driven flow, not to a PIV `Decision`. Rather than repurpose
an incompatible store, this module keeps its own durable, restart-safe,
decision_id-keyed outbox -- the SAME `_load`/`_save` full-file-JSON-rewrite
pattern every other ledger in this package already uses.

**HARD BOUNDARY** (see `gemini_authority_boundary.md` for the full
write-up): enrichment output is treated as UNTRUSTED, purely-additive
content from end to end.
  - `_LLMFindings`'s own schema (`talonx_brain/llm.py`) carries only
    `verdict`/`confidence`/`summary`/`key_findings`/`risk_factors` --
    genuinely informational fields, none of which is a symbol, price,
    quantity, or approval flag.
  - This module extracts ONLY those five named fields from whatever the
    chain returns -- any OTHER attribute a malformed/malicious response
    object might carry (an injected `action`/`price`/`approved` field, for
    instance) is silently discarded by construction (never even read, since
    extraction is by explicit named-field access, not `**vars(result)` or
    similar).
  - Nothing in this module, or any of its callers, EVER passes an
    `EnrichmentRecord` field into `decide()`, `order_intent()`, or any
    other decision/execution-altering code path. `EnrichmentRecord` is
    consumed only by `observability.py`'s read-only status projection.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Protocol

STATUS_NOT_REQUESTED = "NOT_REQUESTED"
STATUS_PENDING = "PENDING"
STATUS_COMPLETED = "COMPLETED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_MALFORMED = "MALFORMED"
STATUS_UNAVAILABLE = "UNAVAILABLE"

_ENRICHMENT_FIELDS = ("verdict", "confidence", "summary", "key_findings", "risk_factors")


class ResearchChain(Protocol):
    """Structural contract matching `talonx_brain.llm._BaseResearchChain`
    -- duck-typed on purpose so a real chain (production) and a fake chain
    (every test/rehearsal) are interchangeable without either depending on
    the other's module."""

    async def generate(self, signal: Any, citations: list) -> Any: ...


@dataclass
class EnrichmentRecord:
    decision_id: str
    ticker: str
    status: str = STATUS_PENDING
    attempts: int = 0
    max_attempts: int = 2
    verdict: str | None = None
    confidence: float | None = None
    summary: str | None = None
    key_findings: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    model_used: str | None = None
    error_detail: str | None = None
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    # The signal is stored (serialized) so dispatch_pending can call
    # chain.generate(signal, ...) independently/asynchronously, decoupled
    # from the moment request() was called -- "initial deterministic alert
    # does not wait for Gemini" is what this decoupling is FOR.
    _signal_json: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GeminiEnrichmentOutbox:
    def __init__(self, state_path: Path | None) -> None:
        self.state_path = state_path
        self.records: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.records, sort_keys=True, indent=2), encoding="utf-8")

    def request(self, decision_id: str, ticker: str, signal: Any) -> dict[str, Any]:
        """Idempotent per decision_id -- a duplicate/restarted call for the
        same decision returns the existing record unchanged. Never calls
        the chain itself (see module docstring) -- purely durable
        bookkeeping, always fast."""
        existing = self.records.get(decision_id)
        if existing is not None:
            return existing
        record = EnrichmentRecord(decision_id=decision_id, ticker=ticker, _signal_json=signal.model_dump_json())
        self.records[decision_id] = record.to_dict()
        self._save()
        return self.records[decision_id]

    def get(self, decision_id: str) -> dict[str, Any] | None:
        return self.records.get(decision_id)

    async def dispatch_pending(self, chain: ResearchChain | None, *, timeout_seconds: float = 10.0) -> dict[str, int]:
        """Independent async dispatch step -- never called from request()
        itself. `chain=None` (no Gemini configured at all) resolves every
        pending record to UNAVAILABLE, honestly, never fabricated as
        COMPLETED."""
        counts = {"completed": 0, "timeout": 0, "malformed": 0, "unavailable": 0}
        for decision_id, record in list(self.records.items()):
            if record["status"] != STATUS_PENDING:
                continue
            if record["attempts"] >= record["max_attempts"]:
                record["status"] = STATUS_UNAVAILABLE
                record["error_detail"] = "max_attempts exhausted"
                counts["unavailable"] += 1
                continue
            record["attempts"] += 1
            if chain is None:
                record["status"] = STATUS_UNAVAILABLE
                record["error_detail"] = "no enrichment adapter configured"
                counts["unavailable"] += 1
                continue
            from talonx_quant.schemas import QuantSignal
            signal = QuantSignal.model_validate_json(record["_signal_json"])
            try:
                result = await asyncio.wait_for(chain.generate(signal, []), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                record["status"] = STATUS_TIMEOUT
                record["error_detail"] = f"timed out after {timeout_seconds}s"
                counts["timeout"] += 1
                continue
            except Exception as exc:  # noqa: BLE001 -- the chain's own bounded retry (talonx_brain.llm) has
                # already exhausted itself by the time this raises; any exception here means the
                # provider is genuinely unavailable this attempt.
                record["status"] = STATUS_UNAVAILABLE
                record["error_detail"] = f"{type(exc).__name__}: {exc}"
                counts["unavailable"] += 1
                continue

            # Extraction is by EXPLICIT named-field access only -- see the
            # module docstring's HARD BOUNDARY. Any other attribute on
            # `result` (an injected action/price/approval field, for
            # instance) is never read, never stored, never acted on.
            missing = [f for f in _ENRICHMENT_FIELDS if not hasattr(result, f)]
            if missing:
                record["status"] = STATUS_MALFORMED
                record["error_detail"] = f"response missing expected field(s): {missing}"
                counts["malformed"] += 1
                continue
            record.update(
                status=STATUS_COMPLETED,
                verdict=str(getattr(result, "verdict")),
                confidence=float(getattr(result, "confidence")),
                summary=str(getattr(result, "summary")),
                key_findings=[str(x) for x in (getattr(result, "key_findings") or [])],
                risk_factors=[str(x) for x in (getattr(result, "risk_factors") or [])],
                model_used=getattr(chain, "model_used", None),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            counts["completed"] += 1
        self._save()
        return counts
