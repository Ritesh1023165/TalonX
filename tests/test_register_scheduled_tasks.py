"""
tests/test_register_scheduled_tasks.py
-------------------------------------------
Static regression checks for scripts/register_scheduled_tasks.ps1
(2026-08-16 quant audit, round 6). NOT an integration test -- this
project's automated test suite is pytest/Python, and actually invoking
Register-ScheduledTask would create/mutate REAL Windows Scheduled Tasks
on whatever machine runs the suite, which is inappropriate for an
unattended test run (and requires an interactive Windows session besides).

Instead, these parse the script's own source text for the two specific
properties this round fixed:
  - a WEEKLY trigger scoped to Monday-Friday via -DaysOfWeek, NOT
    -Daily (which would also fire on Saturday/Sunday -- TalonX has no
    trading session those days, see talonx_quant/session.py's
    is_operating_window_open, the actual trading-permission gate this
    scheduler is paired with).
  - the corrected 08:00 default start time (was 10:00), matching the
    actual trading-session open; 22:00 default stop was already correct.

Cheap, and catches the exact regression this round fixed (reverting to
-Daily, or the wrong default) even without a live Task Scheduler.
"""
from __future__ import annotations

from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "register_scheduled_tasks.ps1"


def _script_text() -> str:
    return _SCRIPT_PATH.read_text(encoding="utf-8")


def _trigger_assignment() -> str:
    """The actual `$trigger = New-ScheduledTaskTrigger ...` code line(s)
    -- deliberately isolated from the rest of the file, since the
    script's own explanatory COMMENTS legitimately mention "-Daily"/
    "Saturday"/"Sunday" in prose (explaining what this trigger is NOT
    and WHY) without that being a regression in the actual trigger
    itself."""
    text = _script_text()
    start = text.index("$trigger = New-ScheduledTaskTrigger")
    end = text.index("\n\n", start)
    return text[start:end]


def test_script_exists():
    assert _SCRIPT_PATH.is_file()


def test_trigger_is_weekly_not_daily():
    trigger = _trigger_assignment()
    assert "New-ScheduledTaskTrigger -Weekly" in trigger
    assert "-Daily" not in trigger


def test_trigger_is_scoped_to_monday_through_friday():
    trigger = _trigger_assignment()
    assert "-DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday" in trigger


def test_trigger_does_not_reference_weekend_days():
    trigger = _trigger_assignment()
    assert "Saturday" not in trigger
    assert "Sunday" not in trigger


def test_default_start_time_is_0800():
    text = _script_text()
    assert '[string]$StartTime = "08:00"' in text


def test_default_stop_time_is_2200():
    text = _script_text()
    assert '[string]$StopTime = "22:00"' in text
