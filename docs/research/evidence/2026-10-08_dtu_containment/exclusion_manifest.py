"""READ-ONLY exclusion manifest for the DTU shadow study (registered endpoint 2026-10-08T00:15Z). Raw data unchanged.
Every record whose COLLECTION time is at/after the endpoint is excluded. Records collected before the endpoint whose
EVENT time is at/after it are listed as AMBIGUOUS (excluded unless the owner decides otherwise). Writes JSON only."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / "talonx_shadow").is_dir())
DB = REPO / "results/dtu_shadow/shadow.db"
END = "2026-10-08T00:15:00"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("exclusion_manifest.json")

c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
m = {"registered_endpoint_utc": "2026-10-08T00:15:00Z", "database": str(DB.relative_to(REPO)),
     "rule": "EXCLUDE: collection time >= endpoint. AMBIGUOUS: collected before the endpoint but event time >= endpoint "
             "(excluded by default). Raw rows are NOT deleted or modified.", "tables": {}}


def tbl(name, collect_col, event_col=None, key=None, extra_where=""):
    ex = c.execute(f"SELECT COUNT(*), MIN({collect_col}), MAX({collect_col}) FROM {name} WHERE {collect_col} >= ?{extra_where}",
                   (END,)).fetchone()
    e = {"collection_time_column": collect_col, "event_time_column": event_col,
         "excluded_rows": ex[0], "excluded_collection_range": [ex[1], ex[2]]}
    if key:
        e["excluded_keys_by_window"] = dict(c.execute(f"SELECT window_id, COUNT(*) FROM {name} WHERE {collect_col} >= ? "
                                                      f"GROUP BY 1", (END,)).fetchall())
    if event_col:
        amb = c.execute(f"SELECT COUNT(*) FROM {name} WHERE {collect_col} < ? AND {event_col} >= ?", (END, END)).fetchone()[0]
        e["ambiguous_rows_event_after_collected_before"] = amb
    m["tables"][name] = e


tbl("sweeps", "at_utc", key=True)
tbl("verify", "at_utc")
tbl("promotions", "first_at_utc", key=True)
tbl("first_cross", "at_utc", "trade_utc", key=True)
tbl("edgar_8k", "seen_utc", "updated_utc")
tbl("edgar_polls", "at_utc")
tbl("snapshots", "built_utc", key=True)
snap_ids = [r[0] for r in c.execute("SELECT snapshot_id FROM snapshots WHERE built_utc >= ?", (END,))]
m["tables"]["snapshot"] = {"collection_time_column": "via snapshots.built_utc", "excluded_snapshot_ids": snap_ids,
                           "excluded_rows": c.execute(f"SELECT COUNT(*) FROM snapshot WHERE snapshot_id IN "
                                                      f"({','.join('?' * len(snap_ids)) or 'NULL'})", snap_ids).fetchone()[0]}
m["post_endpoint_windows"] = sorted({w for t in m["tables"].values() for w in (t.get("excluded_keys_by_window") or {})})
m["in_study_windows"] = {"SEG1_PROD_DTU_V1": ["2026-09-30", "2026-10-01", "2026-10-02"],
                         "SEG2_PROD_DTU_V2": ["2026-10-05", "2026-10-06", "2026-10-07"],
                         "pre_segment_start_day": ["2026-09-29"]}
m["last_collection_row_utc"] = c.execute("SELECT MAX(at_utc) FROM sweeps").fetchone()[0]
m["last_in_study_sweep_utc"] = c.execute("SELECT MAX(at_utc) FROM sweeps WHERE at_utc < ?", (END,)).fetchone()[0]
c.close()
h = hashlib.sha256()
with DB.open("rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
wal = DB.with_name(DB.name + "-wal")
m["files"] = {"shadow.db": {"bytes": DB.stat().st_size, "sha256": h.hexdigest()},
              "shadow.db-wal": {"bytes": wal.stat().st_size if wal.exists() else 0,
                                "note": "WAL not checkpointed by this read-only tool; hash the db after a checkpoint for an archival copy"},
              "collector.log": {"bytes": (REPO / "results/dtu_shadow/collector.log").stat().st_size}}
OUT.write_text(json.dumps(m, indent=1), encoding="utf-8")
print(json.dumps(m, indent=1))
