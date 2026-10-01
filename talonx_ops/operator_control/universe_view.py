"""Read-only Dynamic Tradable Universe view for Sentinel (/universe summary | status SYM | excluded [file]).
Reads market.db (mode=ro) DTU tables written by DATA_INGESTION; never mutates anything; no symbol floods."""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_STATES = ("ACTIVE_CORE", "EVENT_PROMOTED", "OPERATOR_ADDED")

# V2 execution scope, read-only, WITHOUT importing the research lane (2026-10-01 boundary fix). Same source, regex and
# file selection as talonx_premarket.__main__._v2_scope(None): the newest results/prospective_*/logs/v2_companion.log
# that logged a non-empty scope; within a log the LAST "scope ENFORCED" line wins. Parity is pinned by a test.
_V2_SCOPE_RE = re.compile(r"V2 execution scope ENFORCED -- \d+ allowed issuers: (.*)$")


def v2_scope(repo_root: Path | None = None) -> set[str]:
    for p in reversed(sorted(Path(repo_root or REPO_ROOT).glob("results/prospective_*/logs/v2_companion.log"))):
        scope: set[str] = set()
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _V2_SCOPE_RE.search(line)
            if m:
                scope = {x.strip().upper() for x in m.group(1).split(",") if x.strip()}
        if scope:
            return scope
    return set()


class UniverseView:
    def __init__(self, root=None, window_id: str | None = None):
        self.root = Path(root) if root else REPO_ROOT / "results" / "opportunity"
        p = self.root / "market.db"
        self.m = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5) if p.exists() else None
        if self.m is not None:
            # 2026-10-01 (P0): one read transaction per view instance (one Sentinel command) -> every DTU table read
            # by this view comes from the same committed ingestion generation, never a mix of two cycles.
            self.m.execute("BEGIN")
        self.wid = window_id
        if self.m is not None and self.wid is None:
            try:
                r = self.m.execute("SELECT window_id FROM dtu_snapshots ORDER BY window_id DESC LIMIT 1").fetchone()
                self.wid = r[0] if r else None
            except sqlite3.Error:
                self.wid = None

    def available(self) -> bool:
        return self.m is not None and self.wid is not None

    def close(self) -> None:
        if self.m is not None:
            try:
                self.m.rollback()
            finally:
                self.m.close()
                self.m = None

    def latest(self) -> dict:
        r = self.m.execute("SELECT cycle_utc, n_active, counts_json, fallback_reason FROM dtu_active WHERE window_id=? "
                           "ORDER BY cycle_utc DESC LIMIT 1", (self.wid,)).fetchone()
        return {} if r is None else {"cycle_utc": r[0], "n_active": r[1], "counts": json.loads(r[2] or "{}"),
                                     "fallback": r[3]}

    def summary(self) -> dict:
        snap = self.m.execute("SELECT snapshot_version, created_utc, counts_json FROM dtu_snapshots WHERE window_id=?",
                              (self.wid,)).fetchone()
        return {"window": self.wid, "snapshot_version": snap[0] if snap else None,
                "snapshot_created_utc": snap[1] if snap else None,
                "snapshot_counts": json.loads(snap[2]) if snap else {}, **self.latest()}

    def status(self, sym: str) -> dict:
        r = self.m.execute("SELECT state, reason, core_rank, price, adv20 FROM dtu_snapshot WHERE window_id=? AND "
                           "symbol=?", (self.wid, sym)).fetchone()
        prom = self.m.execute("SELECT reason, started_utc, expires_utc, source_event_id FROM dtu_promotions WHERE "
                              "symbol=? ORDER BY started_utc DESC LIMIT 3", (sym,)).fetchall()
        return {"symbol": sym, "snapshot_state": r[0] if r else "NOT_IN_UNIVERSE", "reason": r[1] if r else None,
                "core_rank": r[2] if r else None, "price": r[3] if r else None, "adv20": r[4] if r else None,
                "promotions": [{"reason": p[0], "started_utc": p[1], "expires_utc": p[2], "source": p[3]}
                               for p in prom]}

    def excluded_rows(self) -> list[dict]:
        rows = self.m.execute("SELECT symbol, state, reason, price, adv20, core_rank FROM dtu_snapshot WHERE "
                              "window_id=? AND state NOT IN ('ACTIVE_CORE') ORDER BY state, symbol",
                              (self.wid,)).fetchall()
        return [{"symbol": r[0], "state": r[1], "reason": r[2], "price": r[3], "adv20": r[4], "core_rank": r[5],
                 "promotion_eligible": r[1] == "EVENT_ELIGIBLE", "snapshot_date": self.wid} for r in rows]

    def excluded_csv(self) -> bytes:
        buf = io.StringIO()
        rows = self.excluded_rows()
        w = csv.DictWriter(buf, fieldnames=["symbol", "state", "reason", "price", "adv20", "core_rank",
                                            "promotion_eligible", "snapshot_date"])
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().encode()


# ============================================================================================================ live view
# SYSTEM_STATE (the automatic DTU classification, never rewritten) vs OPERATOR_OVERRIDE (operator_control.db) vs
# EFFECTIVE_STATE (derived). Effective states come from the PRODUCTION resolver (talonx_opportunity.universe_tiers.
# resolve, called read-only with the live inputs); "active right now" is the latest dtu_active set that ingestion
# fetched and discovery evaluated. Nothing here writes to any store.
CSV_FIELDS = ["SYMBOL", "SYSTEM_STATE", "EFFECTIVE_STATE", "OPERATOR_OVERRIDE", "OVERRIDE_STATUS", "REASON", "CORE",
              "EVENT_PROMOTED", "EVENT_ELIGIBLE", "AUTO_EXCLUDED", "STRUCTURAL_EXCLUSION", "V2_PROTECTED",
              "POSITION_PROTECTED", "INTENT_PROTECTED", "LIFECYCLE_PROTECTED", "FETCH_ELIGIBLE", "DISCOVERY_ELIGIBLE",
              "CORE_RANK", "PRICE", "ADV20", "STATE_AS_OF", "SNAPSHOT_ID"]


class LiveUniverse(UniverseView):
    """Per-symbol live DTU view for Sentinel lists / status / files.

    ``deps`` supplies the PRODUCTION logic from the host (the Opportunity-Engine Sentinel component), so this frozen
    talonx_ops package never imports the opportunity lane: ``deps.window(wid)`` (trading window),
    ``deps.resolve(...)`` (universe_tiers.resolve), ``deps.protections(w, now_iso) -> (lifecycle, positions+intents)``
    (the DTU protection readers) and ``deps.intents(w) -> set`` (display split only)."""

    def __init__(self, root=None, window_id: str | None = None, *, store=None, deps=None,
                 v2_scope: set[str] | None = None, now: str | None = None):
        super().__init__(root, window_id)
        self.store, self.deps, self._v2, self._now = store, deps, v2_scope, now
        self._rows: dict[str, dict] | None = None

    def available(self) -> bool:
        return super().available() and self.deps is not None

    # -- live inputs (read-only) ---------------------------------------------------------------------------------------
    def _snapshot(self) -> dict[str, dict]:
        return {r[0]: {"state": r[1], "reason": r[2], "core_rank": r[3], "price": r[4], "adv20": r[5]}
                for r in self.m.execute("SELECT symbol, state, reason, core_rank, price, adv20 FROM dtu_snapshot WHERE "
                                        "window_id=?", (self.wid,))}

    def active_set(self) -> tuple[set[str], str | None]:
        cyc, syms = None, None
        for c, sj in self.m.execute("SELECT cycle_utc, symbols_json FROM dtu_active WHERE window_id=? ORDER BY "
                                    "cycle_utc DESC", (self.wid,)):
            cyc = cyc or c
            if sj is not None:
                syms = set(json.loads(sj))
                break
        return syms or set(), cyc

    def _promotions(self, now: str) -> list[dict]:
        cols = ("window_id", "symbol", "reason", "started_utc", "expires_utc")
        return [dict(zip(cols, r)) for r in self.m.execute(
            f"SELECT {','.join(cols)} FROM dtu_promotions WHERE window_id=? OR (expires_utc IS NOT NULL AND "
            "expires_utc > ?)", (self.wid, now))]

    def _protections(self, w, now: str):
        prot, positions = self.deps.protections(w, now)
        return prot, set(positions), set(self.deps.intents(w))

    def rows(self) -> dict[str, dict]:
        if self._rows is not None:
            return self._rows
        from datetime import datetime, timezone
        w = self.deps.window(self.wid)
        now = self._now or datetime.now(timezone.utc).isoformat()
        snap = self._snapshot()
        if self._v2 is None:
            self._v2 = v2_scope()                     # no research-lane import (boundary)
        prot, positions, intents = self._protections(w, now)
        # the resolver's operator inputs in the CURRENT mode (DRY_RUN -> none applied: identity)
        from talonx_ops.operator_control import gates
        st = gates._state()
        added, removed, excluded = st if st is not None else (set(), set(), set())
        _, states = self.deps.resolve(snap, now=now, promotions=self._promotions(now), operator_added=set(added),
                              operator_excluded=set(excluded) | set(removed), v2_forced=self._v2,
                              positions=positions, protections=prot)
        active, as_of = self.active_set()
        snap_id = self.summary()["snapshot_version"]
        out = {}
        for s, (eff, why) in states.items():
            sysr = snap.get(s, {"state": "NOT_IN_BASE", "reason": None})
            ov = self.store.override_row(s) if self.store is not None else None
            ovn = ov["override"] if ov and ov["status"] != "CLEARED" else "NONE"
            live = s in active
            out[s] = {"SYMBOL": s, "SYSTEM_STATE": sysr["state"], "RESOLVED_STATE": eff,
                      "EFFECTIVE_STATE": "ACTIVE" if live else ("EXCLUDED" if eff in ("AUTO_EXCLUDED",
                                                                                         "STRUCTURALLY_EXCLUDED",
                                                                                         "OPERATOR_EXCLUDED")
                                                                else "ELIGIBLE" if eff == "EVENT_ELIGIBLE"
                                                                else "INACTIVE"),
                      "OPERATOR_OVERRIDE": ovn, "OVERRIDE_STATUS": ov["status"] if ov and ovn != "NONE" else "",
                      "REASON": why, "CORE": sysr["state"] == "ACTIVE_CORE",
                      "EVENT_PROMOTED": eff == "EVENT_PROMOTED", "EVENT_ELIGIBLE": sysr["state"] == "EVENT_ELIGIBLE",
                      "AUTO_EXCLUDED": sysr["state"] == "AUTO_EXCLUDED",
                      "STRUCTURAL_EXCLUSION": sysr["state"] == "STRUCTURALLY_EXCLUDED",
                      "V2_PROTECTED": s in self._v2, "POSITION_PROTECTED": s in (positions - intents),
                      "INTENT_PROTECTED": s in intents, "LIFECYCLE_PROTECTED": prot.get(s) or "",
                      "FETCH_ELIGIBLE": live, "DISCOVERY_ELIGIBLE": live,
                      "CORE_RANK": sysr.get("core_rank"), "PRICE": sysr.get("price"), "ADV20": sysr.get("adv20"),
                      "STATE_AS_OF": as_of, "SNAPSHOT_ID": snap_id}
        self._rows = out
        return out

    # -- populations ------------------------------------------------------------------------------------------------
    def population(self, name: str) -> list[dict]:
        r = self.rows()
        f = {"active": lambda x: x["FETCH_ELIGIBLE"],
             "eligible": lambda x: x["SYSTEM_STATE"] == "EVENT_ELIGIBLE" and not x["FETCH_ELIGIBLE"],
             "excluded": lambda x: x["SYSTEM_STATE"] == "AUTO_EXCLUDED",
             "structural": lambda x: x["SYSTEM_STATE"] == "STRUCTURALLY_EXCLUDED",
             "core": lambda x: x["SYSTEM_STATE"] == "ACTIVE_CORE",
             "promoted": lambda x: x["RESOLVED_STATE"] == "EVENT_PROMOTED",
             "overrides": lambda x: x["OPERATOR_OVERRIDE"] != "NONE"}[name]
        return [x for s, x in sorted(r.items()) if f(x)]

    def csv(self, rows: list[dict]) -> bytes:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for x in rows:
            w.writerow({k: ("YES" if v is True else "NO" if v is False else v) for k, v in x.items()})
        return buf.getvalue().encode()


POP_TITLE = {"active": ("ACTIVE UNIVERSE", "effective active now: Core + event-promoted + operator/V2 + protected "
                                           "(the exact set ingestion fetches and discovery evaluates)"),
             "eligible": ("EVENT-ELIGIBLE", "system EVENT_ELIGIBLE and NOT active now (reachable by the gap / 8-K "
                                            "event tier)"),
             "excluded": ("AUTO-EXCLUDED", "system AUTO_EXCLUDED (below V1 price / ADV20 floors at D-1)"),
             "structural": ("STRUCTURALLY EXCLUDED", "funds / ETFs / warrants / units / preferreds / non-tradable ..."),
             "core": ("CORE", "D-1 frozen top-1200 by ADV20 (system state; V2-scope names show as operator-added)"),
             "promoted": ("EVENT-PROMOTED", "live gap / 8-K promotion or lifecycle protection"),
             "overrides": ("OPERATOR OVERRIDES", "operator intent only -- NOT the DTU universe")}


def population_text(v: "LiveUniverse", name: str, head: str, preview: int = 40) -> str:
    if not v.available():
        return f"{head} — {name.upper()}\nDTU not available (mode OFF or snapshot not built): full universe in use."
    rows = v.population(name)
    title, note = POP_TITLE[name]
    lines = [f"{head} — {title} ({len(rows)}) · {v.wid}", note]
    if name == "active":
        by: dict[str, int] = {}
        for x in rows:
            by[x["RESOLVED_STATE"]] = by.get(x["RESOLVED_STATE"], 0) + 1
        lines.append(" · ".join(f"{k} {n}" for k, n in sorted(by.items(), key=lambda kv: -kv[1])))
    if name in ("excluded", "structural"):
        by = {}
        for x in rows:
            by[x["REASON"]] = by.get(x["REASON"], 0) + 1
        lines += [f"• {n} {k}" for k, n in sorted(by.items(), key=lambda kv: -kv[1])[:8]]
    if name == "overrides":
        lines += [f"{x['SYMBOL']} · {x['OPERATOR_OVERRIDE']} ({x['OVERRIDE_STATUS']}) · system {x['SYSTEM_STATE']} · "
                  f"effective {x['EFFECTIVE_STATE']}" for x in rows[:preview]] or ["None"]
    elif rows:
        lines.append("Preview: " + " ".join(x["SYMBOL"] for x in rows[:preview]) +
                     (f" … +{len(rows) - preview}" if len(rows) > preview else ""))
    if len(rows) > preview or name not in ("overrides",):
        lines.append(f"Full list: /universe {name} file")
    lines.append(f"As of {str(rows[0]['STATE_AS_OF'] if rows else '')[11:19]}Z · snapshot "
                 f"{v.summary()['snapshot_version']}")
    return "\n".join(lines)


def yn(b) -> str:
    return "YES" if b is True else "NO" if b is False else "UNKNOWN"


def live_status_text(v: "LiveUniverse", sym: str, head: str, mode: str) -> str:
    if not v.available():
        return f"{head} — {sym}\nDTU not available: full universe in use."
    x = v.rows().get(sym)
    if x is None:
        return f"{head} — {sym}\nNot in the TalonX base universe ({v.wid}). System state: NOT_IN_UNIVERSE"
    s = v.status(sym)
    p = s["promotions"][0] if s["promotions"] else None
    lines = [f"{head} — {sym}", "",
             f"System state: {x['SYSTEM_STATE']}", f"Effective state: {x['EFFECTIVE_STATE']} ({x['RESOLVED_STATE']})",
             f"Operator override: {x['OPERATOR_OVERRIDE']}" + (f" ({x['OVERRIDE_STATUS']}, mode {mode})"
                                                             if x["OPERATOR_OVERRIDE"] != "NONE" else ""), "",
             f"Core: {yn(x['CORE'])}" + (f" (rank {x['CORE_RANK']})" if x["CORE_RANK"] else ""),
             f"Event promoted: {yn(x['EVENT_PROMOTED'])}", f"Event eligible: {yn(x['EVENT_ELIGIBLE'])}",
             f"Auto excluded: {yn(x['AUTO_EXCLUDED'])}", f"Structural exclusion: {yn(x['STRUCTURAL_EXCLUSION'])}", "",
             f"V2 protected: {yn(x['V2_PROTECTED'])}", f"Open-position protected: {yn(x['POSITION_PROTECTED'])}",
             f"Pending-intent protected: {yn(x['INTENT_PROTECTED'])}",
             f"Lifecycle protected: {x['LIFECYCLE_PROTECTED'] or 'NO'}", "",
             f"Fetch eligible: {yn(x['FETCH_ELIGIBLE'])}", f"Discovery eligible: {yn(x['DISCOVERY_ELIGIBLE'])}", "",
             f"Reason: {x['REASON'] or '-'}"]
    if p:
        lines.append(f"Promotion: {p['reason']} since {str(p['started_utc'])[11:16]}Z · expires "
                     f"{str(p['expires_utc'])[:16] if p['expires_utc'] else 'end of window'}")
    lines += [f"Snapshot: {x['SNAPSHOT_ID']}", f"As of: {x['STATE_AS_OF']}"]
    return "\n".join(lines)


def summary_text(v: UniverseView, head: str) -> str:
    if not v.available():
        return f"{head} — UNIVERSE\nDTU snapshot not available (DTU mode OFF or not built yet): full universe in use."
    s = v.summary()
    c, sc = s.get("counts", {}), s["snapshot_counts"]
    fb = s.get("fallback")
    return "\n".join([
        f"{head} — UNIVERSE ({s['window']})",
        f"Core: {c.get('ACTIVE_CORE', sc.get('ACTIVE_CORE', 0))}",
        f"Event-promoted: {c.get('EVENT_PROMOTED', 0)} (protected {c.get('protected', 0)})",
        f"Event-eligible: {c.get('EVENT_ELIGIBLE', sc.get('EVENT_ELIGIBLE', 0))}",
        f"Auto-excluded: {c.get('AUTO_EXCLUDED', sc.get('AUTO_EXCLUDED', 0))}",
        f"Operator-added: {c.get('OPERATOR_ADDED', 0)} · Operator-excluded: {c.get('OPERATOR_EXCLUDED', 0)}",
        f"Structurally excluded: {sc.get('STRUCTURALLY_EXCLUDED', 0)}",
        f"Effective active: {s.get('n_active', 'n/a')}" + (f" ⚠️ FALLBACK full universe: {fb}" if fb else ""),
        f"Snapshot: {s['snapshot_version']}"])


def status_text(v: UniverseView, sym: str, head: str) -> str:
    if not v.available():
        return f"{head} — {sym}\nDTU not available: full universe in use."
    s = v.status(sym)
    p = s["promotions"][0] if s["promotions"] else None
    lines = [f"{head} — {sym} (universe {v.wid})", f"Snapshot state: {s['snapshot_state']}",
             f"Why: {s['reason'] or '-'}", f"Core rank: {s['core_rank'] or '-'}"]
    if p:
        lines.append(f"Promotion: {p['reason']} since {str(p['started_utc'])[11:16]}Z · expires "
                     f"{str(p['expires_utc'])[:16] if p['expires_utc'] else 'never'}")
    return "\n".join(lines)


def excluded_text(v: UniverseView, head: str) -> str:
    if not v.available():
        return f"{head} — EXCLUDED\nDTU not available."
    rows = v.excluded_rows()
    by: dict[str, int] = {}
    for r in rows:
        k = f"{r['state']}:{(r['reason'] or '').split('_RANK_')[0] if r['state'] != 'EVENT_ELIGIBLE' else 'outside Core'}"
        by[k] = by.get(k, 0) + 1
    top = sorted(by.items(), key=lambda kv: -kv[1])[:12]
    return "\n".join([f"{head} — NOT IN CORE ({len(rows)}) · {v.wid}"] + [f"• {n} {k}" for k, n in top] +
                     ["Full list: /universe excluded file"])
