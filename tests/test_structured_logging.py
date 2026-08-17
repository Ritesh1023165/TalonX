"""
tests/test_structured_logging.py
-------------------------------------
Tests talonx_ingest.common.structured_logging -- JsonFormatter's output
shape directly, and log_structured()'s child-logger routing contract
(see its own docstring for why: several Phase 2 callers share ONE module
logger between pre-existing intraday code and new long-term code, so
log_structured must never touch that shared logger's own handlers).
Uses plain logging.Logger + io.StringIO capture rather than mocking the
logging module itself (same "exercise the real thing" preference as the
rest of this project's tests).
"""
from __future__ import annotations

import io
import json
import logging

import pytest

from talonx_ingest.common.structured_logging import (
    JsonFormatter,
    attach_json_handler,
    log_structured,
)


@pytest.fixture
def formatter_logger():
    """A logger with JsonFormatter attached directly -- for testing the
    formatter's own output shape, independent of log_structured's
    child-logger routing."""
    logger = logging.getLogger("test.formatter_direct")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    yield logger, stream

    logger.handlers.clear()


def test_formatter_emits_expected_schema(formatter_logger):
    logger, stream = formatter_logger
    logger.info(
        "FACTOR_CALCULATED",
        extra={
            "talonx_ticker": "AAPL", "talonx_horizon": "long_term",
            "talonx_event_type": "FACTOR_CALCULATED", "talonx_payload": {"roic": 0.18, "f_score": 8},
        },
    )

    entry = json.loads(stream.getvalue().strip())
    assert entry["module"] == "test.formatter_direct"
    assert entry["horizon"] == "long_term"
    assert entry["level"] == "INFO"
    assert entry["ticker"] == "AAPL"
    assert entry["event_type"] == "FACTOR_CALCULATED"
    assert entry["payload"] == {"roic": 0.18, "f_score": 8}
    assert "timestamp" in entry


def test_plain_log_call_still_works_through_json_formatter(formatter_logger):
    """A logger with JsonFormatter attached must not raise on an ordinary
    logger.info() call with no talonx_* extra fields."""
    logger, stream = formatter_logger

    logger.info("plain unstructured message")

    entry = json.loads(stream.getvalue().strip())
    assert entry["event_type"] is None
    assert entry["ticker"] is None
    assert entry["payload"] == {"message": "plain unstructured message"}


def test_exception_info_is_included_when_present(formatter_logger):
    logger, stream = formatter_logger

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("unused message")

    entry = json.loads(stream.getvalue().strip())
    assert "exception" in entry
    assert "ValueError: boom" in entry["exception"]


def test_attach_json_handler_adds_a_handler_and_disables_propagation():
    logger = logging.getLogger("test.attach_json_handler")
    logger.handlers.clear()
    logger.propagate = True

    attach_json_handler(logger, level=logging.DEBUG)

    assert logger.propagate is False
    assert any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers)
    assert logger.level == logging.DEBUG

    logger.handlers.clear()


# --- log_structured() child-logger routing ----------------------------------

@pytest.fixture
def routed_logger():
    """A base logger (simulating a shared intraday+long-term module logger
    like talonx_core.consumer's) plus a manually pre-attached handler on
    its `.structured` child, so log_structured() finds handlers already
    present and doesn't call attach_json_handler() itself -- letting the
    test capture the exact stream log_structured writes to."""
    base = logging.getLogger("test.routed_logger")
    base.handlers.clear()
    base.setLevel(logging.DEBUG)
    base_stream = io.StringIO()
    base_handler = logging.StreamHandler(base_stream)
    base_handler.setFormatter(logging.Formatter("%(message)s"))
    base.addHandler(base_handler)
    base.propagate = False

    child = logging.getLogger("test.routed_logger.structured")
    child.handlers.clear()
    child.setLevel(logging.DEBUG)
    child_stream = io.StringIO()
    child_handler = logging.StreamHandler(child_stream)
    child_handler.setFormatter(JsonFormatter())
    child.addHandler(child_handler)
    child.propagate = False

    yield base, base_stream, child_stream

    base.handlers.clear()
    child.handlers.clear()


def test_log_structured_emits_expected_schema(routed_logger):
    base, _base_stream, child_stream = routed_logger

    log_structured(base, "FACTOR_CALCULATED", ticker="AAPL", horizon="long_term", roic=0.18, f_score=8)

    entry = json.loads(child_stream.getvalue().strip())
    assert entry["horizon"] == "long_term"
    assert entry["level"] == "INFO"
    assert entry["ticker"] == "AAPL"
    assert entry["event_type"] == "FACTOR_CALCULATED"
    assert entry["payload"] == {"roic": 0.18, "f_score": 8}
    assert "timestamp" in entry


def test_log_structured_defaults_horizon_to_long_term(routed_logger):
    base, _base_stream, child_stream = routed_logger

    log_structured(base, "MOAT_EVALUATED", ticker="MSFT")

    entry = json.loads(child_stream.getvalue().strip())
    assert entry["horizon"] == "long_term"
    assert entry["payload"] == {}


def test_log_structured_respects_explicit_level(routed_logger):
    base, _base_stream, child_stream = routed_logger

    log_structured(base, "FUNDAMENTAL_STOP_TRIGGERED", ticker="XOM", level=logging.WARNING)

    entry = json.loads(child_stream.getvalue().strip())
    assert entry["level"] == "WARNING"


def test_log_structured_never_touches_the_base_logger(routed_logger):
    """The core isolation guarantee: several Phase 2 callers share ONE
    module logger between existing intraday code and new long-term code
    (talonx_brain.consumer, talonx_core.consumer, talonx_paper.consumer).
    log_structured() must never write to, or attach a handler on, that
    shared base logger -- only its dedicated `.structured` child."""
    base, base_stream, _child_stream = routed_logger

    log_structured(base, "TRADE_EXECUTED", ticker="AAPL", order_type="BUY")

    assert base_stream.getvalue() == ""
    assert not any(isinstance(h.formatter, JsonFormatter) for h in base.handlers)


def test_plain_calls_on_the_shared_base_logger_are_unaffected(routed_logger):
    """The other half of the isolation guarantee: a plain logger.info()
    call on the shared base logger must keep using ITS OWN (plain-text)
    handler/formatter, not get pulled into the child's JSON output."""
    base, base_stream, child_stream = routed_logger

    base.info("Connected to Redis at redis://localhost:6379/0")
    log_structured(base, "FACTOR_CALCULATED", ticker="AAPL", roic=0.18)

    assert base_stream.getvalue().strip() == "Connected to Redis at redis://localhost:6379/0"
    assert child_stream.getvalue().strip()  # the structured line landed on the child instead


def test_log_structured_auto_attaches_a_handler_when_child_has_none():
    """Without any pre-attached handler (the real-world call pattern --
    every actual call site just imports log_structured and calls it),
    log_structured must still work by lazily attaching a JsonFormatter
    handler to the child logger itself."""
    base = logging.getLogger("test.auto_attach_base")
    child = logging.getLogger("test.auto_attach_base.structured")
    base.handlers.clear()
    child.handlers.clear()

    try:
        log_structured(base, "FACTOR_CALCULATED", ticker="AAPL", roic=0.18)

        assert len(child.handlers) == 1
        assert isinstance(child.handlers[0].formatter, JsonFormatter)
        assert child.propagate is False
    finally:
        base.handlers.clear()
        child.handlers.clear()
