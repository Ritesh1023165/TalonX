"""Fail-closed detection of competing TalonX application processes.

This is an operational safety gate, not the execution-ownership lock.  The
per-account OS lock remains the authoritative last line of defence around
broker mutations; this check prevents two full application pipelines from
being started accidentally before either reaches that boundary.
"""

from __future__ import annotations

import os
import json
import subprocess
from typing import Callable

ORIGINAL_ROLE = "ORIGINAL"
PIV_ROLE = "PIV"


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
        "$_.ProcessId -notin $excluded } | ForEach-Object { "
        "$role = if ($_.CommandLine -match 'talonx_piv\\.cli') { 'PIV' } else { 'ORIGINAL' }; "
        "$isolated = $role -eq 'PIV' -and $_.CommandLine -match '(?:^|\\s)--isolated-parallel(?:\\s|$)'; "
        "[pscustomobject]@{pid=[int]$_.ProcessId;role=$role;isolated=[bool]$isolated} | ConvertTo-Json -Compress }"
    )


def no_competing_talonx_process(
    *,
    exclude_pid: int | None = None,
    check_output: Callable[..., str] = subprocess.check_output,
    current_role: str | None = None,
    piv_isolation_verified: bool = False,
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

    parsed: list[dict[str, object]] = []
    for raw in output.splitlines():
        value = raw.strip()
        if not value:
            continue
        # Numeric-only output remains accepted for the legacy strict mode so
        # existing diagnostic callers and their captured fixtures remain
        # compatible. Role-aware startup requires structured proof.
        if value.isascii() and value.isdecimal() and int(value) > 0:
            if current_role is not None:
                return False, "process enumeration omitted runtime role -- failed closed"
            parsed.append({"pid": int(value), "role": "UNKNOWN", "isolated": False})
            continue
        try:
            row = json.loads(value)
        except json.JSONDecodeError:
            return False, "process enumeration returned malformed PID/process output -- failed closed"
        if (
            not isinstance(row, dict)
            or isinstance(row.get("pid"), bool)
            or not isinstance(row.get("pid"), int)
            or row["pid"] <= 0
            or row.get("role") not in {ORIGINAL_ROLE, PIV_ROLE}
            or not isinstance(row.get("isolated"), bool)
        ):
            return False, "process enumeration returned malformed PID/process output -- failed closed"
        parsed.append(row)

    peers = {int(row["pid"]): row for row in parsed if int(row["pid"]) != current_pid}
    if current_role is None:
        if peers:
            return False, f"{len(peers)} competing TalonX process(es): {sorted(peers)}"
        return True, "0 competing TalonX processes; enumeration completed successfully"

    if current_role not in {ORIGINAL_ROLE, PIV_ROLE}:
        return False, "unknown current runtime role -- failed closed"
    blocked: list[int] = []
    allowed_peer = 0
    for pid, row in peers.items():
        peer_role = str(row["role"])
        if peer_role == current_role:
            blocked.append(pid)
        elif current_role == PIV_ROLE:
            if piv_isolation_verified:
                allowed_peer += 1
            else:
                blocked.append(pid)
        elif bool(row["isolated"]):
            allowed_peer += 1
        else:
            blocked.append(pid)
    if blocked:
        return False, f"runtime-role process policy blocked peer PID(s): {sorted(blocked)}"
    return True, (
        f"runtime-role process policy passed for {current_role}; "
        f"{allowed_peer} isolated opposite-role peer(s) allowed"
    )
