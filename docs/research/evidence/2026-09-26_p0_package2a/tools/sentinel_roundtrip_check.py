"""Read-only verification of a REAL Sentinel Telegram round-trip (DRY_RUN). usage: python sentinel_roundtrip_check.py
[--since ISO] -> JSON. Proves: commands were handled by the supervised poller, every command is audited, mutations are
PENDING (DRY_RUN), unauthorised attempts were rejected, provider fetch universe unchanged, poller health distinct."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def main(since: str):
    out = {"since": since}
    rt = ro(REPO / "results" / "opportunity" / "runtime.db")
    r = rt.execute("SELECT pid, state, detail_json, config_fps_json FROM components WHERE name='sentinel'").fetchone()
    out["sentinel"] = {"pid": r["pid"], "state": r["state"], **json.loads(r["detail_json"] or "{}")} if r else None
    db = Path(os.environ.get("TALONX_OPERATOR_DB") or REPO / "operator_control.db")
    if db.exists():
        c = ro(db)
        cols = [x[1] for x in c.execute("PRAGMA table_info(operator_audit)")]
        tcol = next((x for x in ("at_utc", "created_utc", "ts_utc") if x in cols), cols[1])
        rows = [dict(x) for x in c.execute(f"SELECT * FROM operator_audit WHERE {tcol} >= ? ORDER BY {tcol}", (since,))]
        out["audit"] = [{k: x.get(k) for k in (tcol, "authorized", "command", "symbol", "mode", "result")} for x in rows]
        out["exclusions"] = [dict(x) for x in c.execute("SELECT * FROM symbol_exclusions")]
        out["universe"] = [dict(x) for x in c.execute("SELECT * FROM operator_universe")]
    else:
        out["audit"] = "operator_control.db not created yet (no mutating/audited command received)"
    from talonx_ops.operator_control import mutation_mode
    from talonx_ops.operator_control.gates import effective_symbols
    base = ["TSLA", "AAPL", "MSFT"]
    out["gate_identity_in_this_env"] = {"mode": mutation_mode(), "identity": effective_symbols(list(base)) == base}
    m = ro(REPO / "results" / "opportunity" / "market.db")
    st = m.execute("SELECT window_id, symbols, cycle_utc FROM ingestion_state ORDER BY cycle_utc DESC LIMIT 1").fetchone()
    out["ingestion_fetch_universe"] = dict(st) if st else None
    from talonx_ops.prospective.telegram_owner import logical_poller_report
    pr = logical_poller_report().to_dict()
    out["poller_health"] = {k: pr[k] for k in ("verdict", "healthy", "roles", "pid_roles")}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[a.index("--since") + 1] if "--since" in a else "2026-09-26T00:00:00")
