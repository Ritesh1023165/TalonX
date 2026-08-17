"""
talonx_ingest.common.structured_logging
-------------------------------------------
Phase 2's structured JSON logging foundation -- a logging.Formatter
subclass emitting one JSON object per line with the schema:
    {timestamp, module, horizon, level, ticker, event_type, payload}

Applied to every NEW long-term code path (talonx_quant.fundamental_consumer,
talonx_brain's long-term handler, talonx_core's long-term consumer,
talonx_paper.consumer.LongTermPaperEngine) as the working foundation for
this requirement -- each emits at least one structured line per key event
(FACTOR_CALCULATED, MOAT_EVALUATED, VALUATION_DERIVED, TRADE_EXECUTED,
etc.). Retrofitting the ~15 pre-existing intraday log call sites to this
format is a deliberately separate, purely mechanical follow-up -- this
file's job is to make the format available and easy to opt into, not to
migrate everything at once.

Shared here (not duplicated per-module) for the same reason
talonx_ingest.common.backoff already is: it's pure, dependency-free infra
with no coupling to any one module's domain objects -- ticker, horizon,
event_type, and payload are all caller-supplied strings/dicts, and the
`extra={"talonx_*": ...}` keys below are the one contract every caller
follows.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emits one JSON object per line. Falls back to sane defaults for
    any talonx_* `extra` field a caller didn't pass -- log_structured()
    below always passes all of them, but a plain `logger.info("msg")`
    call on a logger with this formatter attached still works (with less
    detail in the emitted line) rather than raising."""

    def format(self, record: logging.LogRecord) -> str:
        event_type = getattr(record, "talonx_event_type", None)
        payload: dict[str, Any] = dict(getattr(record, "talonx_payload", None) or {})
        if not event_type:
            # A plain, non-structured log call through this formatter --
            # fold the rendered message into payload rather than dropping it.
            payload.setdefault("message", record.getMessage())

        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "module": record.name,
            "horizon": getattr(record, "talonx_horizon", "long_term"),
            "level": record.levelname,
            "ticker": getattr(record, "talonx_ticker", None),
            "event_type": event_type,
            "payload": payload,
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def log_structured(
    logger: logging.Logger,
    event_type: str,
    ticker: str | None = None,
    horizon: str = "long_term",
    level: int = logging.INFO,
    **payload: Any,
) -> None:
    """log_structured(logger, "FACTOR_CALCULATED", ticker="AAPL",
    roic=0.18, f_score=8) emits one JSON line.

    Routes through a `<logger.name>.structured` CHILD logger (auto-created
    and given its own JsonFormatter handler on first use, memoized by
    Python's own logging registry -- `logging.getLogger` already returns
    the same instance for a repeated name, so no extra caching needed
    here) rather than logging directly on `logger`. This matters because
    several of Phase 2's callers -- talonx_brain.consumer, talonx_core.consumer,
    talonx_paper.consumer -- use ONE module logger for BOTH their
    pre-existing intraday code and this new long-term code (per the Phase
    2 plan, those 3 modules handle both horizons in the same class/task).
    Attaching a JSON handler to `logger` directly would silently reformat
    every existing plain-text intraday log line too -- exactly the
    full-codebase retrofit the Phase 2 plan deliberately deferred. Routing
    through a dedicated child logger keeps this call's JSON output fully
    isolated from whatever handler `logger` itself has (plain-text or
    otherwise), in either direction."""
    structured_logger = logging.getLogger(f"{logger.name}.structured")
    if not structured_logger.handlers:
        attach_json_handler(structured_logger, level=logging.DEBUG)
    structured_logger.log(
        level, event_type,
        extra={
            "talonx_ticker": ticker, "talonx_horizon": horizon,
            "talonx_event_type": event_type, "talonx_payload": payload,
        },
    )


def attach_json_handler(logger: logging.Logger, level: int = logging.INFO) -> None:
    """Adds a StreamHandler(JsonFormatter()) to `logger` -- does NOT touch
    the root logger or any other logger's handlers, so a module opts in
    explicitly rather than silently changing every existing log line's
    format process-wide (that global retrofit is the deferred follow-up
    mentioned in this file's docstring). `propagate = False` so lines
    aren't ALSO emitted in the plain-text format by the root handler
    every module's logging.basicConfig() already installs."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
