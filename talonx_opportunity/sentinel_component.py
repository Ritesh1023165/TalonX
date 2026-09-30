"""
Sentinel operator-command poller as a SUPERVISED runtime component (2026-09-26, P0 package 2A).

``talonx_ops.operator_control.sentinel.SentinelCommandPoller`` answers owner-only commands on the TalonX Sentinel
bot. This wrapper runs it under the same runtime contract as every engine component: one instance
(component lock), heartbeat + detail in runtime.db, a recorded deployment boundary, supervised restart.

* Disabled unless ``TALONX_SENTINEL_COMMANDS_ENABLED=1``: the component then idles (never polls Telegram) and reports
  ``enabled: false`` -- a disabled poller is a state, not a crash loop.
* Credentials come only from the Sentinel destination (``operator_control.sentinel.operations_poller``); never the
  Signal or Lab bots, never the legacy default token. The token is never logged.
* The next getUpdates offset is persisted before each update is handled (``sentinel_state.json`` in the runtime root),
  so a restart never re-handles a command (no replay).
* Universe mutation mode (``OPERATOR_UNIVERSE_MUTATION_MODE``) is reported, not changed here: provider / discovery /
  promotion gates read it in their own processes.
"""
from __future__ import annotations

import talonx_ops.log_redaction  # noqa: F401  (process-wide secret redaction before any HTTP logging)
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from talonx_opportunity.db import REPO_ROOT, root_dir

ENABLE_ENV = "TALONX_SENTINEL_COMMANDS_ENABLED"
LONG_POLL_S = 20                       # well inside the 180 s heartbeat bound; stop flag honoured between polls


def enabled(env=None) -> bool:
    return str((env if env is not None else os.environ).get(ENABLE_ENV, "0")).strip() == "1"


def status_text(root=None, env=None) -> str:
    """Compact, mobile-friendly read-only /status for Sentinel (no secrets, no stack traces)."""
    from talonx_ops.operator_control import DRY_RUN, mutation_mode
    lines = ["🛰 TalonX Sentinel — /status"]
    try:
        from talonx_ops.opportunity_read import read_opportunity_status
        s = read_opportunity_status(root)
        comps = {c["component"]: c for c in s.get("components", [])}
        lines.append(f"🧭 Engine: {s['system']['overall']}")
        down = [c["logical"] for c in comps.values() if c["health"] not in ("UP", "BUSY_LONG_SCAN")]
        lines.append("   all components up" if not down else "   ⚠ not up: " + ", ".join(down[:6]))
        disc = s.get("discovery") or {}
        if disc.get("last_scan"):
            ls = disc["last_scan"]
            lines.append(f"🔎 Last scan: {str(ls.get('decision_utc', ''))[11:16]}Z {ls.get('phase')} {ls.get('state')}")
        p = comps.get("promotion")
        if p:
            lines.append(f"📈 Promotion: {(p.get('detail') or {}).get('mode') or p.get('mode') or '?'} · {p['health']}")
        lines += _scope_lines(root)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"🧭 Engine: status unavailable ({type(exc).__name__})")
    mode = mutation_mode(env)
    lines.append(f"🛡 Control plane: {mode}" + (" (changes recorded as PENDING)" if mode == DRY_RUN else ""))
    try:
        sp = Path(os.environ.get("TALONX_V2_STATUS_PATH") or REPO_ROOT / "v2_release_rc1_status.json")
        v = json.loads(sp.read_text())
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(v["heartbeat_utc"])).total_seconds()
        lines.append(f"🏦 V2: {v.get('data_state')} · heartbeat {age:.0f}s · {v.get('execution_mode')} "
                     f"{v.get('campaign_id') or ''}".rstrip())
    except Exception:  # noqa: BLE001
        lines.append("🏦 V2: status file unavailable")
    lines.append("Paper only · no broker orders · /help for commands")
    return "\n".join(lines)


def _scope_lines(root=None) -> list[str]:
    """Scope + today's Opportunity Engine delivery counts, labelled per lane (no ambiguous 'pushed 0')."""
    import sqlite3
    out = []
    r = root_dir(root)

    def ro(name):
        p = r / name
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5) if p.exists() else None
    try:
        from talonx_ops.operator_control.universe_view import UniverseView
        v = UniverseView(r)
        if v.available():
            s = v.summary()
            c = s.get("counts", {})
            out.append(f"🌐 OE universe: Core {c.get('ACTIVE_CORE', s['snapshot_counts'].get('ACTIVE_CORE', 0))} · "
                       f"event-promoted {c.get('EVENT_PROMOTED', 0)} · effective active {s.get('n_active', 'n/a')} · "
                       f"event-eligible {c.get('EVENT_ELIGIBLE', s['snapshot_counts'].get('EVENT_ELIGIBLE', 0))}"
                       + (" ⚠️ fallback full" if s.get("fallback") else ""))
        else:
            m = ro("market.db")
            n = m.execute("SELECT symbols FROM ingestion_state ORDER BY window_id DESC LIMIT 1").fetchone() if m else None
            out.append(f"🌐 OE universe: full ({n[0] if n else '?'} symbols, Dynamic Universe OFF)")
    except Exception:  # noqa: BLE001
        out.append("🌐 OE universe: unavailable")
    try:
        from talonx_premarket import __main__ as M
        out.append(f"🏛 V2 / filing scope: {len(M._v2_scope(None))} names (separate lane)")
    except Exception:  # noqa: BLE001
        pass
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        p = ro("promotion.db")
        if p:
            wid = p.execute("SELECT MAX(window_id) FROM promotions").fetchone()[0]
            st = dict(p.execute("SELECT state, COUNT(*) FROM promotions WHERE window_id=? GROUP BY 1", (wid,)).fetchall())
            out.append(f"🚨 PAPER_SIGNAL (OE, window {wid}): sent {st.get('PROMOTED_SIGNAL', 0)} · queued "
                       f"{st.get('QUEUED', 0)} · expired {st.get('EXPIRED', 0)} · rejected "
                       f"{st.get('REJECTED_WHILE_QUEUED', 0)}")
        n = ro("notification.db")
        lab = ro("opportunity_research_notifications.db")
        if n and lab:
            imm = lab.execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE state='SENT' AND sent_at_utc LIKE ? "
                              "AND event_type NOT LIKE '%DIGEST'", (today + "%",)).fetchone()[0]
            dg = lab.execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE state='SENT' AND sent_at_utc LIKE ? "
                             "AND event_type LIKE '%DIGEST'", (today + "%",)).fetchone()[0]
            out.append(f"🧪 Lab today: immediate {imm} · digests {dg}")
    except Exception:  # noqa: BLE001
        out.append("🚨/🧪 delivery counts unavailable")
    return out


class SentinelComponent:
    def __init__(self, *, root=None, env=None, bot_factory=None, store=None):
        self.root, self.env = root, (env if env is not None else os.environ)
        self.enabled = enabled(self.env)
        self.state_path = root_dir(root) / "sentinel_state.json"
        self.bot_factory, self.store = bot_factory, store
        self.loop = self.bot = self.poller = None
        self.identity: str | None = None
        self.offset = self._load_offset()
        self.polls = 0

    # -- durable offset (no replay across restarts) ----------------------------------------------------------------
    def _load_offset(self) -> int | None:
        try:
            return int(json.loads(self.state_path.read_text())["next_offset"])
        except Exception:  # noqa: BLE001
            return None

    def _save_offset(self, off: int) -> None:
        self.offset = off
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"next_offset": off, "updated_utc": datetime.now(timezone.utc).isoformat()}))
        os.replace(tmp, self.state_path)

    def _start(self) -> None:
        from talonx_ops.operator_control.sentinel import operations_poller
        self.loop = asyncio.new_event_loop()
        self.bot, self.poller, self.identity = operations_poller(
            loop=self.loop, env=self.env, store=self.store, bot_factory=self.bot_factory,
            status_provider=lambda: status_text(self.root, self.env))
        self.poller.reply_log = self._append_reply

    def _append_reply(self, rec: dict) -> None:
        with (root_dir(self.root) / "sentinel_replies.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def tick(self) -> float:
        if not self.enabled:
            return 60.0                                    # disabled: idle, never touch Telegram
        if self.poller is None:
            self._start()
        self.loop.run_until_complete(self.poller.poll_once(self.offset, timeout=LONG_POLL_S,
                                                           on_offset=self._save_offset))
        self.polls += 1
        return 0.5

    def detail(self) -> dict:
        from talonx_ops.operator_control import mutation_mode
        return {"enabled": self.enabled, "mutation_mode": mutation_mode(self.env), "destination": "SENTINEL",
                "bot": self.identity, "polls": self.polls, "handled": getattr(self.poller, "handled", 0),
                "last_error": getattr(self.poller, "last_error", None), "next_offset": self.offset}

    def config_fps(self) -> dict[str, str]:
        from talonx_ops.operator_control import mutation_mode
        return {"enabled": "1" if self.enabled else "0", "mutation_mode": mutation_mode(self.env),
                "destination": "SENTINEL"}


def main(argv=None) -> int:
    from talonx_opportunity.runtime import run_component
    from talonx_premarket import __main__ as M
    M._env()                                           # .env with override=False (process-scoped values win)
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (they embed the bot token)
    root = os.environ.get("TALONX_OPP_ROOT")
    c = SentinelComponent(root=root)
    run_component("sentinel", tick=c.tick, root=root, detail=c.detail, config_fps=c.config_fps())
    return 0
