"""Read-only V2 release-campaign snapshot for the missed 2026-09-25 EOD close. usage: python v2_snap.py > f.json"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
DB = REPO / "v2_release_rc1.db"
SD = REPO / "results" / "prospective_2026-09-25"

c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
th = {}
for t in tables:
    h = hashlib.sha256()
    for row in c.execute(f"SELECT * FROM [{t}] ORDER BY 1"):
        h.update(repr(row).encode())
    th[t] = (c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0], h.hexdigest()[:12])
q = lambda sql: c.execute(sql).fetchone()
out = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "campaign": dict(zip([d[0] for d in c.execute("SELECT * FROM campaign").description], q("SELECT * FROM campaign"))),
       "cash": q("SELECT cash FROM portfolio WHERE id=1")[0],
       "positions_by_status": dict(c.execute("SELECT status, COUNT(*) FROM positions GROUP BY 1").fetchall()),
       "trades": q("SELECT COUNT(*) FROM trades")[0],
       "pending_entry_intents": q("SELECT COUNT(*) FROM pending_entry_intents")[0],
       "table_hashes": th, "db_sha": hashlib.sha256(DB.read_bytes()).hexdigest()[:16]}
for t in ("account_blocks", "exits", "pending_exits"):
    if t in tables:
        out[t] = th[t][0]
n = sqlite3.connect(f"file:{REPO / 'v2_release_rc1_notifications.db'}?mode=ro", uri=True)
out["v2_notify_outbox"] = n.execute("SELECT destination, event_type, state, COUNT(*) FROM ops_notification_outbox "
                                    "GROUP BY 1,2,3").fetchall()
s = json.loads((REPO / "v2_release_rc1_status.json").read_text())
out["status"] = {k: s.get(k) for k in ("heartbeat_utc", "tick", "data_state", "strategy_version", "campaign_id",
                                       "execution_mode")}
out["status"]["provider_fp"] = (s.get("price_provider_contract") or {}).get("contract_fingerprint")
out["session_dir"] = sorted(p.name for p in SD.iterdir())
out["eod_markers"] = {f: (SD / f).exists() for f in ("eod.json", "final_report.md", "eod_final_checkpoint.json",
                                                      "terminal_summary.txt", "v2_lane.db.eod-copy")}
print(json.dumps(out, indent=1, default=str))
