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
POPULATIONS = ("active", "eligible", "excluded", "structural", "core", "promoted", "overrides")
SUBS = {"universe": ("summary", "status", "move", "list", "add", "remove") + POPULATIONS, "exclude": ("add", "remove", "list", "status"),
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

🌐 DTU Visibility (read-only, LIVE)
/universe summary
/universe active [file]
/universe eligible [file]
/universe excluded [file]
/universe structural [file]
/universe core [file]
/universe promoted [file]
/universe status <SYMBOL>

🛠 Operator Overrides
/universe move <SYMBOL> active
/universe move <SYMBOL> eligible
/universe move <SYMBOL> excluded
/universe move <SYMBOL> auto
/universe overrides [file]

🚫 Exclusions (legacy)
/exclude add|remove|list|status <SYMBOL>

🔎 Scanning
/scanned
/scanned file
/scanned candidates
/scanned setups
/scanned signals

🖥 System
/status  ·  /help  ·  /help <command>"""

PRE_EOD = ("\n\n⏳ Mutation mode: DRY_RUN\n\nRead-only commands show LIVE state.\n\nMove commands are recorded as "
           "PENDING only and do not affect provider fetching, DTU membership, discovery, Lab or Signal until an "
           "approved activation boundary.")

HELP = {
    "universe": f"""{HEAD} — /universe

Visibility (read-only, LIVE DTU state — never mutates anything):
/universe summary — counts per population
/universe active [file] — what TalonX is processing NOW (Core + event-promoted + operator/V2 + protected)
/universe eligible [file] — EVENT_ELIGIBLE and not active now (reachable by the gap / 8-K event tier)
/universe excluded [file] — AUTO_EXCLUDED (below V1 price / ADV20 floors)
/universe structural [file] — STRUCTURALLY_EXCLUDED (ETFs, warrants, units, preferreds ...)
/universe core [file] · /universe promoted [file]
/universe status PLTR — system state, override, effective state, protections, reason

Operator overrides (the system DTU state is never rewritten; the effective state is derived):
/universe move PLTR active — FORCE_ACTIVE
/universe move PLTR eligible — FORCE_ELIGIBLE (event tier only, no continuous scan)
/universe move PLTR excluded — FORCE_EXCLUDED (held while an open position / intent / V2 scope protects it)
/universe move PLTR auto — clear the override (back to the automatic DTU)
/universe overrides [file] — operator overrides only (NOT the DTU universe)

Legacy: /universe add PLTR · /universe remove PLTR (operator-added fetch list; shown in /universe list).""",
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
           scanned=None, universe=None) -> Reply | None:
    """Returns None for non-command text (so other resolvers keep working). ``universe``: host-supplied factory
    ``store -> LiveUniverse`` (None -> live DTU views report unavailable; never a guess)."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    parts = raw.split()
    cmd = parts[0][1:].split("@")[0].lower()
    args = parts[1:]
    if cmd == "ping":
        return None                                             # the existing /ping handler owns it
    authorized = owner_chat_id is not None and str(chat_id) == str(owner_chat_id)
    mutating = cmd in ("universe", "exclude") and args and args[0].lower() in ("add", "remove", "move")
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
    if cmd == "universe" and sub == "list":             # ambiguous legacy name: explain, never "0 active"
        return Reply(_overrides_redirect(store, mode))
    if sub == "list":
        return Reply(_list(cmd, store, mode))
    if cmd == "universe" and (sub == "summary" or sub in POPULATIONS):   # read-only LIVE DTU views
        from talonx_ops.operator_control import universe_view as UV
        if sub == "summary":
            return Reply(UV.summary_text(UV.UniverseView(), HEAD) + "\n" + _override_counts(store) +
                         "\n/universe active · eligible · excluded · structural [file]")
        v = universe(store) if universe else UV.LiveUniverse(store=store)
        if len(args) > 1 and args[1].lower() == "file" and v.available():
            rows = v.population(sub)
            return Reply(f"{HEAD} — {UV.POP_TITLE[sub][0]} ({len(rows)}) · {v.wid}", document=v.csv(rows),
                         filename=f"universe_{sub}_{v.wid}.csv")
        return Reply(UV.population_text(v, sub, HEAD))
    if cmd == "universe" and sub == "move":
        sym, err = normalize_symbol(args[1] if len(args) > 1 else None)
        target = args[2].lower() if len(args) > 2 else None
        if err or target not in MOVE_TARGETS:
            return Reply(f"❗ {err or 'target must be one of: ' + ' | '.join(MOVE_TARGETS)}\n"
                         "Usage: /universe move <SYMBOL> <active|eligible|excluded|auto>\n"
                         "Example: /universe move PLTR active")
        return _move(sym, target, " ".join(args[3:])[:120], store=store, user=user, chat=str(chat_id), mode=mode,
                     raw=raw, universe=universe)
    sym, err = normalize_symbol(args[1] if len(args) > 1 else None)
    if err:
        return Reply(f"❗ {err}\n{_usage(cmd, sub)}")
    if sub == "status":
        if cmd == "universe":
            from talonx_ops.operator_control import universe_view as UV
            return Reply(UV.live_status_text(universe(store) if universe else UV.LiveUniverse(store=store), sym,
                                             HEAD, mode) +
                         _legacy_intent(sym, store))
        return Reply(_status(sym, store, mode))
    reason = " ".join(args[2:])[:120] or None
    return _mutate(cmd, sub, sym, reason, store=store, user=user, chat=str(chat_id), mode=mode, raw=raw)


def _legacy_intent(sym: str, store: OperatorStore) -> str:
    u, e = store.universe_row(sym), store.exclusion_row(sym)
    out = []
    if u and u["status"] in ("ACTIVE", "REMOVED"):
        out.append(f"Operator universe (legacy): {u['status']} ({u['activation']})")
    if e and e["status"] == "EXCLUDED":
        out.append(f"Operator exclusion (legacy): EXCLUDED ({e['activation']})")
    return ("\n" + "\n".join(out)) if out else ""


MOVE_TARGETS = {"active": "FORCE_ACTIVE", "eligible": "FORCE_ELIGIBLE", "excluded": "FORCE_EXCLUDED", "auto": "NONE"}


def _override_counts(store: OperatorStore) -> str:
    ov = store.overrides()
    by = {k: sum(1 for r in ov if r["override"] == k) for k in ("FORCE_ACTIVE", "FORCE_ELIGIBLE", "FORCE_EXCLUDED")}
    return (f"Operator overrides: FORCE_ACTIVE {by['FORCE_ACTIVE']} · FORCE_ELIGIBLE {by['FORCE_ELIGIBLE']} · "
            f"FORCE_EXCLUDED {by['FORCE_EXCLUDED']}")


def _overrides_redirect(store: OperatorStore, mode: str) -> str:
    """/universe list: operator intent only (overrides + legacy add / exclude rows) -- never a '0 active' universe."""
    ov = store.overrides()
    n = {k: sum(1 for r in ov if r["override"] == k) for k in ("FORCE_ACTIVE", "FORCE_EXCLUDED", "FORCE_ELIGIBLE")}
    added, excluded = sorted(store.added()), sorted(store.excluded())
    rows = []
    for s_ in added:
        u = store.universe_row(s_) or {}
        rows.append(f"➕ {s_} · {u.get('activation', '')}")
    for s_ in excluded:
        e = store.exclusion_row(s_) or {}
        rows.append(f"🚫 {s_} · {e.get('activation', '')}")
    for r in ov:
        if r["override"] == "FORCE_ELIGIBLE":
            rows.append(f"↔ {r['symbol']} · FORCE_ELIGIBLE · {r['status']}")
    return "\n".join([f"{HEAD} — OPERATOR OVERRIDES", "",
                      f"Operator-added: {len(added)} (via override {n['FORCE_ACTIVE']})",
                      f"Operator-excluded: {len(excluded)} (via override {n['FORCE_EXCLUDED']})",
                      f"Operator-eligible (FORCE_ELIGIBLE): {n['FORCE_ELIGIBLE']}",
                      f"Mode: {mode}"] + (["", *rows[:40]] if rows else []) +
                     ["", "This is NOT the full DTU universe.", "",
                      "Use:", "/universe summary", "/universe active", "/universe eligible", "/universe excluded",
                      "/universe overrides"])


def _move(sym, target, reason, *, store, user, chat, mode, raw, universe=None) -> Reply:
    """Operator override request. The system DTU state is never rewritten. Safety protections win; DRY_RUN records
    PENDING only (no provider / discovery / DTU change). Idempotent."""
    from talonx_ops.operator_control import universe_view as UV
    v = universe(store) if universe else UV.LiveUniverse(store=store)
    req = MOVE_TARGETS[target]
    if not v.available():
        return Reply("❗ DTU state unavailable — /universe move not recorded.")
    x = v.rows().get(sym)
    if x is None:
        store.audit(actor=user, chat=chat, authorized=True, command=raw, symbol=sym, before=None, after=None,
                    mode=mode, result="REJECTED_NOT_IN_BASE_UNIVERSE")
        return Reply(f"❗ {sym} is not in the TalonX base universe ({v.wid}) — move rejected.")
    cur = store.current_override(sym)
    sysst, eff = x["SYSTEM_STATE"], x["EFFECTIVE_STATE"]
    why = reason or ""
    if req == cur:
        status = "ALREADY_AUTO" if req == "NONE" else "ALREADY_REQUESTED"
    elif cur == "NONE" and ((req == "FORCE_ACTIVE" and eff == "ACTIVE") or
                            (req == "FORCE_EXCLUDED" and sysst in ("AUTO_EXCLUDED", "STRUCTURALLY_EXCLUDED")) or
                            (req == "FORCE_ELIGIBLE" and sysst == "EVENT_ELIGIBLE" and eff != "ACTIVE")):
        status = "ALREADY_EFFECTIVE"
    elif req in ("FORCE_EXCLUDED", "FORCE_ELIGIBLE") and (x["POSITION_PROTECTED"] or x["INTENT_PROTECTED"]
                                                          or x["V2_PROTECTED"]):
        status = "HELD_PROTECTED"
        why = ("OPEN_POSITION_PROTECTED" if x["POSITION_PROTECTED"] else "PENDING_INTENT_PROTECTED"
               if x["INTENT_PROTECTED"] else "V2_SCOPE_PROTECTED")
    else:
        status = "APPLIED" if mode == ACTIVE else "PENDING"
    record = status in ("PENDING", "APPLIED")
    rid = store.record_override_request(symbol=sym, requested=req, status=status, operator=user, source="SENTINEL",
                                        mode=mode, previous_system_state=sysst, previous_effective_state=eff,
                                        reason=why, snapshot_id=x["SNAPSHOT_ID"], state_as_of=x["STATE_AS_OF"],
                                        apply_current=record)
    store.audit(actor=user, chat=chat, authorized=True, command=raw, symbol=sym, before={"override": cur},
                after={"override": req if record else cur, "status": status}, mode=mode, result=status, reason=why)
    lines = [f"{HEAD} — OVERRIDE REQUEST", "", sym, "", f"System state: {sysst}",
             f"Current effective state: {eff}", f"Current override: {cur}", "", f"Requested override: {req}", "",
             f"Mode: {mode}", f"Status: {status}"]
    if status == "HELD_PROTECTED":
        lines += [f"Reason: {why}", f"Effective state remains {eff} until the protection clears.",
                  "Nothing recorded as pending."]
    elif status.startswith("ALREADY"):
        lines.append("No change (idempotent).")
    elif mode != ACTIVE:
        lines += ["", "No provider/discovery change has been applied."]
        if req == "FORCE_ELIGIBLE":
            lines.append("Note: FORCE_ELIGIBLE has no runtime representation yet (architectural gap) — "
                         "recorded as intent only.")
    lines.append(f"Request: {rid}")
    return Reply("\n".join(lines), mutated=record, audit_id=rid)


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
