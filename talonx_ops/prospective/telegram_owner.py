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

2026-09-26 (P0 package 2A): two DISTINCT command pollers are expected -- the Signal command/reply poller
(``run_talonx.py`` DispatchAgent, TRADE_EVENT bot) and the Sentinel operator-command poller (``talonx_opportunity
component sentinel``, OPERATIONS bot). Each Telegram-connected PID is classified by role; the report is healthy when
each poller role has at most one instance (EXPECTED_DISTINCT_POLLERS). Two of the SAME role is DUPLICATE_SAME_ROLE;
a Telegram client of no known role is UNKNOWN_TELEGRAM_CLIENT; send-only producers (outbox drains, V2, Intelligence)
are SENDER and never count as pollers. A PID whose command line cannot be read keeps the legacy meaning (counted as a
Signal poller). An ENABLED Sentinel whose registered process is dead is SENTINEL_POLLER_DEAD.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Any

# Telegram Bot API front-end ranges (stable for years).
_TG_PREFIXES = ("149.154.", "91.108.")

SIGNAL, SENTINEL, SENDER, UNKNOWN, UNRESOLVED = ("SIGNAL_COMMANDS", "SENTINEL_COMMANDS", "SENDER", "UNKNOWN",
                                                 "UNRESOLVED")
# send-only Telegram producers (never call getUpdates)
_SENDER_MARKERS = ("talonx_opportunity component notifier", "talonx_opportunity component promotion",
                   "talonx_v2.run", "talonx_ingest.intelligence.service", "talonx_ops.prospective",
                   "talonx_ops.notify", "talonx_ops.supervisor", "dashboard_web.py")
_SENTINEL_MARKERS = ("talonx_opportunity component sentinel", "talonx_ops.operator_control.sentinel")


def role_of_cmdline(parts: list[str]) -> str:
    joined = " ".join(parts or [])
    if not joined:
        return UNRESOLVED
    if any(t == "run_talonx.py" or t.replace("\\", "/").endswith("/run_talonx.py") for t in parts) \
            and "--skip-dispatch" not in joined:
        return SIGNAL
    if any(m in joined for m in _SENTINEL_MARKERS):
        return SENTINEL
    if any(m in joined for m in _SENDER_MARKERS):
        return SENDER
    return UNKNOWN


def _role_of_pid(pid: int) -> str:
    try:
        import psutil
        return role_of_cmdline(psutil.Process(pid).cmdline())
    except Exception:  # noqa: BLE001 -- gone / access denied: legacy meaning (a Signal poller)
        return UNRESOLVED


def _sentinel_cmdline_count() -> int:
    """Logical Sentinel pollers by command line (shim + real child = one)."""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return 0
    m = {}
    for p in psutil.process_iter(["cmdline", "pid"]):
        try:
            if role_of_cmdline(p.info.get("cmdline") or []) == SENTINEL:
                m[p.pid] = p
        except Exception:  # noqa: BLE001
            continue
    n = 0
    for pid, proc in m.items():
        try:
            par = proc.parent()
        except Exception:  # noqa: BLE001
            par = None
        if par is None or par.pid not in m:
            n += 1
    return n


def _sentinel_expected_but_dead() -> bool | None:
    """True when the registry says the Sentinel poller is ENABLED and RUNNING but its pid is dead (None: unknown)."""
    try:
        import json
        import os
        import sqlite3
        from pathlib import Path
        root = Path(os.environ.get("TALONX_OPP_ROOT") or Path(__file__).resolve().parents[2] / "results" / "opportunity")
        db = root / "runtime.db"
        if not db.exists():
            return None
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            r = c.execute("SELECT pid, state, detail_json FROM components WHERE name='sentinel'").fetchone()
        finally:
            c.close()
        if r is None or r[1] not in ("RUNNING", "DEGRADED"):
            return False
        if not (json.loads(r[2] or "{}") or {}).get("enabled"):
            return False
        import psutil
        return not psutil.pid_exists(int(r[0] or 0))
    except Exception:  # noqa: BLE001
        return None


@dataclass
class PollerReport:
    logical_owners: int
    healthy: bool
    network_pids: list[int] = field(default_factory=list)
    cmdline_matches: int | None = None
    method: str = "network"
    detail: str = ""
    roles: dict[str, int] = field(default_factory=dict)
    verdict: str = ""
    pid_roles: dict[str, str] = field(default_factory=dict)

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


def _verdict(roles: dict[str, int], sentinel_dead: bool | None) -> tuple[bool, str]:
    sig = roles.get(SIGNAL, 0) + roles.get(UNRESOLVED, 0)
    if sig > 1 or roles.get(SENTINEL, 0) > 1:
        return False, "DUPLICATE_SAME_ROLE"
    if roles.get(UNKNOWN, 0):
        return False, "UNKNOWN_TELEGRAM_CLIENT"
    if sentinel_dead:
        return False, "SENTINEL_POLLER_DEAD"
    return True, "EXPECTED_DISTINCT_POLLERS"


def logical_poller_report() -> PollerReport:
    net_pids, how = _network_pids()
    sentinel_dead = _sentinel_expected_but_dead()
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
            roles = {SIGNAL: logical, SENTINEL: _sentinel_cmdline_count()}
            ok, verdict = _verdict(roles, sentinel_dead)
            return PollerReport(logical_owners=logical + roles[SENTINEL], healthy=ok,
                                network_pids=[], cmdline_matches=cmd_n, method="cmdline-fallback", roles=roles,
                                verdict=verdict,
                                detail="no established Telegram connection right now (mid long-poll); "
                                       f"cmdline heuristic -> {logical} Signal + {roles[SENTINEL]} Sentinel")
        by_pid = {pid: _role_of_pid(pid) for pid in net_pids}
        roles = {r: sum(1 for v in by_pid.values() if v == r) for r in (SIGNAL, SENTINEL, SENDER, UNKNOWN, UNRESOLVED)}
        ok, verdict = _verdict(roles, sentinel_dead)
        pollers = n - roles[SENDER]
        return PollerReport(logical_owners=pollers, healthy=ok, network_pids=net_pids,
                            cmdline_matches=cmd_n, method="network", roles=roles, verdict=verdict,
                            pid_roles={str(k): v for k, v in by_pid.items()},
                            detail=f"{n} distinct PID(s) with an established Telegram connection "
                                   f"({pollers} poller(s)): {verdict}")

    # network method unavailable -> conservative cmdline heuristic, shim-aware
    if cmd_n is None:
        return PollerReport(logical_owners=0, healthy=True, method=how,
                            detail="poller count unavailable")
    logical = max(1, cmd_n // 2) if cmd_n and cmd_n % 2 == 0 else cmd_n
    roles = {SIGNAL: logical or 0, SENTINEL: _sentinel_cmdline_count()}
    ok, verdict = _verdict(roles, sentinel_dead)
    return PollerReport(logical_owners=(logical or 0) + roles[SENTINEL], healthy=ok, cmdline_matches=cmd_n,
                        roles=roles, verdict=verdict,
                        method=f"cmdline-only ({how})",
                        detail=f"network probe unavailable; cmdline matches {cmd_n} -> ~{logical} logical "
                               "(even count treated as shim+child pairs)")
