"""
Sentinel command handling (pure; transport-free). ``handle(text, ...) -> Reply``.

Authorisation: the owner chat (``TALONX_NOTIFY_OPERATIONS_CHAT_ID``, the Sentinel destination) -- the same chat-id
equality rule the existing listener uses. Unauthorised requests never mutate state and are audited (no secret ever
appears in a reply or the audit row).
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from talonx_ops.operator_control import ACTIVE, DRY_RUN
from talonx_ops.operator_control.store import OperatorStore, normalize_symbol

HEAD = "⚙️ TALONX SENTINEL"
COMMANDS = ("help", "universe", "exclude", "scanned", "status")
SUBS = {"universe": ("add", "remove", "list", "status"), "exclude": ("add", "remove", "list", "status"),
        "scanned": ("file", "candidates", "setups", "signals")}


@dataclass
class Reply:
    text: str
    document: bytes | None = None
    filename: str | None = None
    mutated: bool = False
    audit_id: str | None = None
    extra: dict = field(default_factory=dict)


HELP_TOP = f"""{HEAD} — COMMAND HELP

🌐 Universe
/universe add <SYMBOL>
/universe remove <SYMBOL>
/universe list
/universe status <SYMBOL>

🚫 Exclusions
/exclude add <SYMBOL>
/exclude remove <SYMBOL>
/exclude list
/exclude status <SYMBOL>

🔎 Scanning
/scanned
/scanned file
/scanned candidates
/scanned setups
/scanned signals

🖥 System
/status  ·  /help  ·  /help <command>"""

PRE_EOD = ("\n\n⏳ Mode: DRY_RUN — changes are recorded as PENDING and do not affect provider fetching, "
           "discovery, Lab or Signal until an approved activation boundary.")

HELP = {
    "universe": f"""{HEAD} — /universe

Manage operator-added symbols in the fetch universe.
/universe add PLTR — add PLTR to future provider fetches
/universe remove PLTR — stop fetching an operator-added symbol
/universe list — operator-added / removed symbols
/universe status PLTR — current state of one symbol

• Discovery starts from the activation boundary forward — no history backfill or replay.
• History is kept when a symbol is removed; re-adding never replays it.
• An exclusion always wins over the universe.""",
    "exclude": f"""{HEAD} — /exclude

Stop all work on a symbol without deleting history.
/exclude add TSLA — exclude TSLA
/exclude remove TSLA — restore TSLA
/exclude list — all current exclusions
/exclude status TSLA — current state of one symbol

When ACTIVE, an excluded symbol is:
• dropped from yfinance and Alpaca fetch batches (never fetched)
• skipped by discovery (no scoring, SEC lookup, candidates or lifecycle)
• never sent to Lab or promoted to Signal; queued promotions expire (OPERATOR_EXCLUDED)
• history kept; already-sent paper signals keep their outcome tracking
Restoring never replays the excluded period — only new events count.""",
    "scanned": f"""{HEAD} — /scanned

/scanned — today's scan summary (symbols seen, candidates, setups, paper signals)
/scanned candidates — active candidates (top by score)
/scanned setups — BULLISH/BEARISH setups
/scanned signals — paper-signal promotions
/scanned file — CSV export of today's session""",
    "status": f"""{HEAD} — /status

/status (and /ping) — system health. Operator-control state: /exclude list, /universe list.""",
    "help": HELP_TOP,
}


def _usage(cmd: str, sub: str | None = None) -> str:
    ex = {"universe": "/universe add PLTR", "exclude": "/exclude add TSLA", "scanned": "/scanned setups"}[cmd]
    subs = " | ".join(SUBS[cmd])
    return f"Usage: /{cmd} <{subs}>{' <SYMBOL>' if sub in ('add', 'remove', 'status') else ''}\nExample: {ex}\n/help {cmd} for details"


def _fmt_rows(rows: list[dict], keys: tuple[str, ...]) -> str:
    out = []
    for r in rows:
        parts = [str(r.get(keys[0]))]
        for k in keys[1:]:
            v = r.get(k)
            parts.append(f"{v:.1f}" if isinstance(v, float) else str(v))
        out.append(" · ".join(parts))
    return "\n".join(out)


def handle(text: str, *, chat_id, user: str, owner_chat_id, store: OperatorStore, mode: str = DRY_RUN,
           scanned=None) -> Reply | None:
    """Returns None for non-command text (so other resolvers keep working)."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    parts = raw.split()
    cmd = parts[0][1:].split("@")[0].lower()
    args = parts[1:]
    if cmd == "ping":
        return None                                             # the existing /ping handler owns it
    authorized = owner_chat_id is not None and str(chat_id) == str(owner_chat_id)
    mutating = cmd in ("universe", "exclude") and args and args[0].lower() in ("add", "remove")
    if not authorized:
        store.audit(actor=user, chat=str(chat_id), authorized=False, command=raw, symbol=None, before=None,
                    after=None, mode=mode, result="REJECTED_UNAUTHORIZED")
        return Reply("⛔ Not authorised. Operator commands are owner-only on TalonX Sentinel.")
    if cmd not in COMMANDS:
        guess = difflib.get_close_matches(cmd, COMMANDS, n=1, cutoff=0.6)
        return Reply(f"Unknown command /{cmd[:20]}." + (f" Did you mean /{guess[0]}?" if guess else "") + " Try /help")
    if cmd == "help":
        topic = args[0].lower().lstrip("/") if args else "help"
        return Reply(HELP.get(topic, f"No help for {topic[:20]!r}. Try /help") + (PRE_EOD if mode != ACTIVE and topic in
                                                                                ("universe", "exclude", "help") else ""))
    if cmd == "status":
        return None                                             # defer to the existing status/ping path
    if cmd == "scanned":
        return _scanned(args, scanned)
    sub = args[0].lower() if args else None
    if sub not in SUBS[cmd]:
        return Reply(_usage(cmd, sub))
    if sub == "list":
        return Reply(_list(cmd, store, mode))
    sym, err = normalize_symbol(args[1] if len(args) > 1 else None)
    if err:
        return Reply(f"❗ {err}\n{_usage(cmd, sub)}")
    if sub == "status":
        return Reply(_status(sym, store, mode))
    reason = " ".join(args[2:])[:120] or None
    return _mutate(cmd, sub, sym, reason, store=store, user=user, chat=str(chat_id), mode=mode, raw=raw)


def _activation(mode: str) -> str:
    return "ACTIVE" if mode == ACTIVE else "PENDING_ACTIVATION"


def _mutate(cmd, sub, sym, reason, *, store, user, chat, mode, raw) -> Reply:
    act = _activation(mode)
    if cmd == "exclude":
        before = store.exclusion_row(sym)
        cur = (before or {}).get("status")
        if sub == "add" and cur == "EXCLUDED":
            return Reply(f"ℹ️ {sym} is already excluded ({before['activation']}).")
        if sub == "remove" and cur != "EXCLUDED":
            return Reply(f"ℹ️ {sym} is not excluded.")
        store.set_exclusion(sym, "EXCLUDED" if sub == "add" else "RESTORED", by=user, reason=reason, activation=act)
    else:
        before = store.universe_row(sym)
        cur = (before or {}).get("status")
        if sub == "add" and cur == "ACTIVE":
            return Reply(f"ℹ️ {sym} is already in the operator universe ({before['activation']}).")
        if sub == "remove" and cur != "ACTIVE":
            return Reply(f"ℹ️ {sym} is not an operator-added symbol.")
        store.set_universe(sym, "ACTIVE" if sub == "add" else "REMOVED", by=user, reason=reason, activation=act)
    after = store.exclusion_row(sym) if cmd == "exclude" else store.universe_row(sym)
    aid = store.audit(actor=user, chat=chat, authorized=True, command=raw, symbol=sym, before=before, after=after,
                      mode=mode, result=f"{act}", reason=reason or "")
    live = mode == ACTIVE
    if cmd == "exclude" and sub == "add":
        body = (f"🚫 {sym} EXCLUDED\n\nProvider fetch: OFF\nDiscovery: OFF\nLab: OFF\nSignal promotion: OFF\n"
                f"Historical records: preserved") if live else (
            f"🚫 {sym} exclusion accepted as PENDING\n\nLive provider fetching: unchanged until activation\n"
            f"Historical records: preserved\nReplay on restore: NO\n\nActivation: next approved runtime boundary")
    elif cmd == "exclude":
        body = (f"✅ {sym} RESTORED — only new events from now are eligible (no replay)" if live else
                f"✅ {sym} restore accepted as PENDING — no replay; live fetching unchanged until activation")
    elif sub == "add":
        body = (f"➕ {sym} ADDED — fetched from the next cycle; no backfill/replay" if live else
                f"➕ {sym} add accepted as PENDING — no backfill/replay; live fetching unchanged until activation")
    else:
        body = (f"➖ {sym} REMOVED — no longer fetched; history kept" if live else
                f"➖ {sym} removal accepted as PENDING — history kept; live fetching unchanged until activation")
    return Reply(f"{HEAD} — OPERATOR CONTROL\n\n{body}\n\nAudit: {aid}", mutated=True, audit_id=aid)


def _status(sym: str, store: OperatorStore, mode: str) -> str:
    u, e = store.universe_row(sym), store.exclusion_row(sym)
    ex = (e or {}).get("status") == "EXCLUDED"
    lines = [f"{HEAD} — {sym}",
             f"Operator universe: {(u or {}).get('status', 'not operator-managed')}"
             + (f" ({u['activation']})" if u else ""),
             f"Exclusion: {'EXCLUDED' if ex else (e or {}).get('status', 'none')}" + (f" ({e['activation']})" if e else ""),
             f"Mode: {mode}"]
    if ex:
        lines.append("Effective: NOT fetched" if mode == ACTIVE else "Effective today: still fetched (PENDING)")
    return "\n".join(lines)


def _list(cmd: str, store: OperatorStore, mode: str) -> str:
    if cmd == "exclude":
        rows = [dict(r) for r in store.con.execute("SELECT symbol, activation, excluded_at FROM symbol_exclusions "
                                                   "WHERE status='EXCLUDED' ORDER BY symbol")]
        head = f"{HEAD} — EXCLUSIONS ({len(rows)}) · mode {mode}"
        return head + ("\n" + "\n".join(f"🚫 {r['symbol']} · {r['activation']} · since {r['excluded_at'][:16]}Z"
                                        for r in rows[:40]) if rows else "\nNone")
    rows = [dict(r) for r in store.con.execute("SELECT symbol, status, activation FROM operator_universe ORDER BY symbol")]
    head = f"{HEAD} — OPERATOR UNIVERSE ({sum(r['status'] == 'ACTIVE' for r in rows)} active) · mode {mode}"
    return head + ("\n" + "\n".join(f"{'➕' if r['status'] == 'ACTIVE' else '➖'} {r['symbol']} · {r['status']} · "
                                    f"{r['activation']}" for r in rows[:40]) if rows else "\nNone")


def _scanned(args, scanned) -> Reply:
    if scanned is None:
        return Reply("Scan data unavailable right now.")
    sub = args[0].lower() if args else None
    if sub is None:
        s = scanned.summary()
        if not s.get("available"):
            return Reply("No scan data for today yet.")
        return Reply(f"""{HEAD} — SCANNED ({s['window']})
Phase: {s['current_phase']} · last scan {(s['last_scan_utc'] or '')[11:16]}Z ({s['last_scan_s']}s)
Symbols seen (with prints): {s['unique_symbols_seen']}
Evaluated last scan: {s['symbols_evaluated_last_scan']} (data-ready {s['data_ready_last_scan']})
Candidates: {s['candidates']} · Setups (any time today): {s['setups']}
Paper signals: {s['paper_signal_promotions']} (shadow {s['shadow_promotions']})
/scanned file for the full CSV""")
    if sub not in SUBS["scanned"]:
        return Reply(_usage("scanned", sub))
    if sub == "file":
        text, n = scanned.export_csv()
        return Reply(f"{HEAD} — scanned export: {n} symbols ({scanned.wid})", document=text.encode("utf-8"),
                     filename=f"talonx_scanned_{scanned.wid}.csv")
    n, rows = getattr(scanned, sub)()
    keys = ("symbol", "score", "reference_price", "state") if sub == "signals" else ("symbol", "state", "max_score",
                                                                                     "last_gap_pct")
    more = f"\n… {n - len(rows)} more — /scanned file" if n > len(rows) else ""
    label = {"candidates": "ACTIVE CANDIDATES", "setups": "ACTIVE SETUPS", "signals": "PAPER PROMOTIONS"}[sub]
    return Reply(f"{HEAD} — {label} ({n})\n" + (_fmt_rows(rows, keys) if rows else "None") + more)
