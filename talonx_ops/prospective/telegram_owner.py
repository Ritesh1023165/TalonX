"""
Telegram getUpdates owner detection (Task 114 B6).

The frozen ``count_telegram_get_updates_owners()`` greps process cmdlines
for ``run_talonx.py`` -- on Windows the ``.venv`` launcher shim AND the
real interpreter child both match, so a single logical poller reports as
2 ("shim double-count", Task 112T/113 P3).

This module resolves the *logical* owner by counting DISTINCT processes
that actually hold an ESTABLISHED TCP connection to Telegram's API
network (Bot API front end, 149.154.160.0/20 + 91.108.4.0/22).  A real
second independent poller shows a second owning PID here -> DEGRADED.
Wrapper shim + child collapse to one PID because only the child opens
the socket.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Any

# Telegram Bot API front-end ranges (stable for years).
_TG_PREFIXES = ("149.154.", "91.108.")


@dataclass
class PollerReport:
    logical_owners: int
    healthy: bool
    network_pids: list[int] = field(default_factory=list)
    cmdline_matches: int | None = None
    method: str = "network"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _telegram_ips() -> set[str]:
    ips: set[str] = set()
    for host in ("api.telegram.org",):
        try:
            for res in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP):
                ips.add(res[4][0])
        except OSError:
            pass
    return ips


def _network_pids() -> tuple[list[int], str]:
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return [], "psutil-unavailable"
    ips = _telegram_ips()
    pids: set[int] = set()
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status != psutil.CONN_ESTABLISHED or not c.raddr:
                continue
            rip = c.raddr.ip if hasattr(c.raddr, "ip") else c.raddr[0]
            if rip in ips or any(rip.startswith(p) for p in _TG_PREFIXES):
                if c.pid:
                    pids.add(c.pid)
    except (psutil.AccessDenied, PermissionError):
        return [], "net-connections-access-denied"
    except Exception as exc:  # noqa: BLE001
        return [], f"net-connections-error:{type(exc).__name__}"
    return sorted(pids), "ok"


def logical_poller_report() -> PollerReport:
    net_pids, how = _network_pids()
    try:
        from talonx_ops.supervisor import count_telegram_get_updates_owners
        cmd_n = count_telegram_get_updates_owners()
    except Exception:  # noqa: BLE001
        cmd_n = None

    if how == "ok":
        n = len(net_pids)
        # 0 network owners can mean "between long-poll cycles" -- fall back to
        # the cmdline heuristic, but interpret an EVEN count (shim+child pairs)
        # as that many / 2 logical owners.
        if n == 0 and cmd_n:
            logical = max(1, cmd_n // 2) if cmd_n % 2 == 0 else cmd_n
            return PollerReport(logical_owners=logical, healthy=logical <= 1,
                                network_pids=[], cmdline_matches=cmd_n, method="cmdline-fallback",
                                detail="no established Telegram connection right now (mid long-poll); "
                                       f"cmdline heuristic -> {logical} logical")
        return PollerReport(logical_owners=n, healthy=n <= 1, network_pids=net_pids,
                            cmdline_matches=cmd_n, method="network",
                            detail=f"{n} distinct PID(s) with an established Telegram connection")

    # network method unavailable -> conservative cmdline heuristic, shim-aware
    if cmd_n is None:
        return PollerReport(logical_owners=0, healthy=True, method=how,
                            detail="poller count unavailable")
    logical = max(1, cmd_n // 2) if cmd_n and cmd_n % 2 == 0 else cmd_n
    return PollerReport(logical_owners=logical, healthy=logical <= 1, cmdline_matches=cmd_n,
                        method=f"cmdline-only ({how})",
                        detail=f"network probe unavailable; cmdline matches {cmd_n} -> ~{logical} logical "
                               "(even count treated as shim+child pairs)")
