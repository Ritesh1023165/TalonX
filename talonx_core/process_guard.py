"""Fail-closed detection of competing TalonX application processes.

This is an operational safety gate, not the execution-ownership lock.  The
per-account OS lock remains the authoritative last line of defence around
broker mutations; this check prevents two full application pipelines from
being started accidentally before either reaches that boundary.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable


def _process_query(current_pid: int) -> str:
    # Snapshot once, then walk the current process's ancestry inside that
    # same snapshot. Tooling/terminal launchers can be Python processes whose
    # command line embeds the child command; ancestors are invocation
    # machinery, not peer TalonX pipelines.
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$all = @(Get-CimInstance Win32_Process -ErrorAction Stop); "
        f"$cursor = {current_pid}; $excluded = @(); "
        "while ($cursor -gt 0) { "
        "if ($excluded -contains $cursor) { break }; "
        "$excluded += $cursor; "
        "$node = $all | Where-Object { $_.ProcessId -eq $cursor } | Select-Object -First 1; "
        "if ($null -eq $node) { break }; $cursor = [int]$node.ParentProcessId }; "
        "$all | Where-Object { $_.Name -match '^python(?:w)?(?:\\.exe)?$' -and "
        "$_.CommandLine -match 'run_talonx\\.py|talonx_piv\\.cli' -and "
        "$_.ProcessId -notin $excluded } | Select-Object -ExpandProperty ProcessId"
    )


def no_competing_talonx_process(
    *,
    exclude_pid: int | None = None,
    check_output: Callable[..., str] = subprocess.check_output,
) -> tuple[bool, str]:
    """Return success only after complete enumeration proves no competitor.

    Only Python application processes are candidates. The current process and
    its verified ancestor chain are excluded because terminal/tool launchers
    can embed the child's command text without being a second TalonX pipeline.
    Windows process enumeration can report access failures as non-terminating
    PowerShell errors.  ``-ErrorAction Stop`` plus ``$ErrorActionPreference``
    makes those failures observable to the caller.  Every exception and every
    malformed result blocks startup; uncertainty is never treated as proof
    that the process list is empty.
    """

    current_pid = os.getpid() if exclude_pid is None else exclude_pid
    try:
        output = check_output(
            ["powershell", "-NoProfile", "-Command", _process_query(current_pid)],
            text=True,
            timeout=20,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:  # noqa: BLE001 -- every enumeration failure is a safety block
        return False, f"process enumeration failed closed ({type(exc).__name__})"

    parsed: list[int] = []
    for raw in output.splitlines():
        value = raw.strip()
        if not value:
            continue
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            return False, "process enumeration returned malformed PID output -- failed closed"
        parsed.append(int(value))

    competitors = sorted({pid for pid in parsed if pid != current_pid})
    if competitors:
        return False, f"{len(competitors)} competing TalonX process(es): {competitors}"
    return True, "0 competing TalonX processes; enumeration completed successfully"
