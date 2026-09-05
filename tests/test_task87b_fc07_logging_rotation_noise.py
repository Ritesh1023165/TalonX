"""Task 87B FC_07 -- bounded logging + noise reduction.

Proves the file handler actually rotates at the configured size with a
bounded backup count, that ERROR/WARNING and lifecycle/EOD lines always
survive, and that the high-volume per-symbol regime_shadow INFO stream is
collapsed to a periodic summary (but kept verbatim when
TALONX_LOG_VERBOSE=1).

TEST_FIXTURE_ONLY.
"""
from __future__ import annotations

import logging
import logging.handlers

import pytest

from talonx_ops.logging_setup import RegimeShadowThrottleFilter, configure_logging


@pytest.fixture(autouse=True)
def _clean_root():
    root = logging.getLogger()
    saved_handlers, saved_level, saved_filters = root.handlers[:], root.level, root.filters[:]
    root.handlers.clear()
    root.filters.clear()
    yield
    root.handlers[:] = saved_handlers
    root.filters[:] = saved_filters
    root.setLevel(saved_level)


def test_rotating_file_handler_installed_with_bounds(tmp_path):
    fh = configure_logging(log_dir=tmp_path, max_bytes=2048, backup_count=3)
    assert isinstance(fh, logging.handlers.RotatingFileHandler)
    assert fh.maxBytes == 2048 and fh.backupCount == 3


def test_logs_actually_rotate_and_backup_count_is_bounded(tmp_path):
    configure_logging(log_dir=tmp_path, max_bytes=1024, backup_count=2)
    log = logging.getLogger("talonx_test.rotation")
    for i in range(400):
        log.warning("rotation probe line %04d -- padding padding padding padding", i)
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler):
            h.flush()
    produced = sorted(p.name for p in tmp_path.glob("talonx.log*"))
    assert "talonx.log" in produced
    # base + at most `backupCount` rotated files -> <= 3 total
    assert len(produced) <= 3
    assert any(name.endswith(".1") for name in produced)  # it really rotated


def test_error_and_warning_always_pass_the_shadow_filter():
    f = RegimeShadowThrottleFilter(window_seconds=9999)
    rec = logging.LogRecord("talonx_quant.consumer", logging.ERROR, __file__, 1,
                            "regime_shadow symbol=AAPL disagreement=OLD_FAIL_NEW_PASS", None, None)
    assert f.filter(rec) is True  # ERROR is never dropped even though it matches the prefix


def test_lifecycle_and_eod_lines_are_not_filtered():
    f = RegimeShadowThrottleFilter(window_seconds=9999)
    for msg in ("EOD reconciliation PASSED", "Mandatory flatten invoked", "Recorded long-term alert #LT7"):
        rec = logging.LogRecord("talonx_dispatch.consumer", logging.INFO, __file__, 1, msg, None, None)
        assert f.filter(rec) is True


def test_regime_shadow_per_symbol_lines_are_suppressed_then_summarised(caplog):
    f = RegimeShadowThrottleFilter(window_seconds=0.0)  # every call closes the window
    summary_logger = "talonx_quant.regime_shadow_summary"
    with caplog.at_level(logging.INFO, logger=summary_logger):
        results = [
            f.filter(logging.LogRecord("talonx_quant.consumer", logging.INFO, __file__, 1,
                                       f"regime_shadow symbol=S{i} current_pass=False disagreement=OLD_FAIL_NEW_PASS",
                                       None, None))
            for i in range(5)
        ]
    assert results == [False] * 5  # each per-symbol line dropped
    assert any("regime_shadow:" in r.message and "evaluation(s)" in r.message for r in caplog.records)


def test_verbose_env_keeps_every_regime_shadow_line(monkeypatch):
    monkeypatch.setenv("TALONX_LOG_VERBOSE", "1")
    f = RegimeShadowThrottleFilter(window_seconds=9999)
    rec = logging.LogRecord("talonx_quant.consumer", logging.INFO, __file__, 1,
                            "regime_shadow symbol=AAPL disagreement=BOTH_PASS", None, None)
    assert f.filter(rec) is True


def test_third_party_loggers_raised_to_warning(tmp_path):
    configure_logging(log_dir=tmp_path)
    for name in ("httpx", "yfinance", "urllib3"):
        assert logging.getLogger(name).level == logging.WARNING
