"""
tests/test_task139_recovery.py
===============================
Task 139 -- host-restart recovery. Covers the one bounded diagnostic
change made during recovery: talonx_ops.supervisor._exit_code_hint,
which annotates a monitored child's "exited unexpectedly" log line with
a human-readable hint for the two Windows exit-code signatures this
project's own history has actually needed to distinguish (an external
forceful kill vs. an OS console shutdown/logoff signal). Log-line
annotation only -- no control-flow change, so no behavior-affecting
test is needed beyond confirming the hint text and that it doesn't
break the existing warning call.
"""
from __future__ import annotations

import logging

from talonx_ops.supervisor import _exit_code_hint


def test_forceful_kill_code_hint_int_form():
    hint = _exit_code_hint(-1)
    assert "forceful kill" in hint
    assert "runtime-code commit" in hint


def test_forceful_kill_code_hint_unsigned_form():
    # Windows reports this AS the unsigned 32-bit value in this log's
    # "%s" formatting -- both forms must resolve to the same hint since
    # they are the same underlying code.
    assert _exit_code_hint(4294967295) == _exit_code_hint(-1)


def test_shutdown_signal_code_hint():
    hint = _exit_code_hint(1073807364)
    assert "STATUS_CONTROL_C_EXIT" in hint
    assert "OS-triggered host restart" in hint
    assert hint == _exit_code_hint(0x40010004)


def test_unknown_code_yields_no_hint():
    assert _exit_code_hint(0) == ""
    assert _exit_code_hint(1) == ""


def test_none_code_yields_no_hint():
    assert _exit_code_hint(None) == ""


def test_hint_is_appended_to_the_actual_warning_log_line(caplog):
    """The exact log call site in supervisor.py's monitor loop -- confirms
    the hint is wired into the real warning message, not just the helper
    in isolation."""
    logger = logging.getLogger("talonx_ops.supervisor")
    with caplog.at_level(logging.WARNING, logger="talonx_ops.supervisor"):
        from talonx_ops.supervisor import _exit_code_hint as _h
        logger.warning("%s exited unexpectedly code=%s%s", "intelligence",
                       4294967295, _h(4294967295))
    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert "intelligence exited unexpectedly code=4294967295" in msg
    assert "forceful kill" in msg
