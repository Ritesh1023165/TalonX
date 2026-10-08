#!/usr/bin/env bash
# DTU endpoint closeout driver (2026-10-08 overnight task). Runs ONLY the existing, documented per-window final
# evaluation (results/dtu_shadow/daily.sh run_eval: dtu_eval + verify_contract + harm_check, identical commands/greps)
# for windows that have no *_final.txt yet. It does NOT run daily.sh's snapshot-build step (collection, not evaluation;
# every window already has its collector-built snapshot), never kills the collector, never overwrites an existing
# final, and computes no aggregate / study-level verdict.
set -u
cd /c/workspace/TalonX
PY=.venv/Scripts/python.exe
E=results/overnight_20261008/dtu
D=results/dtu_shadow/checkpoints
export PYTHONIOENCODING=utf-8; unset TALONX_OPP_ROOT
log() { echo "{\"at\": \"$(date -u +%FT%TZ)\", $1}" >> $E/closeout.jsonl; }
until $PY -c "import sys,datetime as d; sys.exit(0 if d.datetime.now(d.timezone.utc)>=d.datetime(2026,10,8,0,20,tzinfo=d.timezone.utc) else 1)"; do sleep 30; done
log "\"event\": \"start\", \"code_head\": \"$(git rev-parse HEAD)\", \"talonx_shadow_tree\": \"$(git rev-parse HEAD:talonx_shadow)\""
# collector state at the endpoint (read-only)
$PY - >> $E/collector_state_at_endpoint.json <<'PY'
import json, sqlite3, psutil, datetime as d
c = sqlite3.connect("file:results/dtu_shadow/shadow.db?mode=ro", uri=True)
procs = [{"pid": p.info["pid"], "cmd": " ".join(p.info["cmdline"] or [])[-80:]} for p in psutil.process_iter(["pid", "cmdline"])
         if "talonx_shadow.dtu run" in " ".join(p.info["cmdline"] or []) or "tracker_dtu_collector" in " ".join(p.info["cmdline"] or [])]
print(json.dumps({"checked_utc": d.datetime.now(d.timezone.utc).isoformat(), "collector_processes": procs,
                  "last_sweep": c.execute("SELECT max(at_utc), max(id) FROM sweeps").fetchone(),
                  "sweeps_after_endpoint": c.execute("SELECT count(*) FROM sweeps WHERE at_utc >= '2026-10-08T00:15:00'").fetchone()[0],
                  "per_window": c.execute("SELECT window_id, count(*), min(at_utc), max(at_utc) FROM sweeps GROUP BY 1").fetchall()},
                 indent=1))
PY
for W in 2026-10-01 2026-10-02 2026-10-05 2026-10-06 2026-10-07; do
  if [ -f $D/${W}_final.txt ]; then log "\"window\": \"$W\", \"event\": \"skip_existing_final\""; continue; fi
  if [ -f results/dtu_shadow/eval/${W}.json ]; then log "\"window\": \"$W\", \"event\": \"skip_existing_eval_json\""; continue; fi
  t0=$(date -u +%FT%TZ)
  {
    $PY -m talonx_shadow.dtu_eval $W; rc1=$?
    echo "--- CONTRACT"; $PY -m talonx_shadow.verify_contract $W | grep -E '"(samples|C_share_within_10bps|C_same_minute_pairs|SNAPSHOT_FIELD_CONTRACT)"|"(PREMARKET|REGULAR|AFTER_HOURS)"'
    echo "--- HARM"; $PY -m talonx_shadow.harm_check $W | grep -E "STOP_CONDITION|median_s|failed_batches"
    echo "--- RC dtu_eval=$rc1"
  } > $D/${W}_final.txt 2>&1
  rc=$(grep -o "RC dtu_eval=[0-9]*" $D/${W}_final.txt | cut -d= -f2)
  h1=$(sha256sum $D/${W}_final.txt | cut -c1-64); h2=$(sha256sum results/dtu_shadow/eval/${W}.json 2>/dev/null | cut -c1-64)
  log "\"window\": \"$W\", \"event\": \"final_eval\", \"started\": \"$t0\", \"dtu_eval_exit\": \"$rc\", \"final_txt_sha256\": \"$h1\", \"eval_json_sha256\": \"$h2\""
done
log "\"event\": \"done\""
