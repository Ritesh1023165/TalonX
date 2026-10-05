#!/usr/bin/env bash
# INSIDER_BUY_CLUSTER_V2@1 SHADOW forward tracker, daily loop v2 (2026-10-05 reliability fix; research only, sends
# nothing, changes no V2 state). Same schedule (06:00Z), stop date (2026-10-31), stages and arguments as
# forward_daily.sh (kept unchanged for provenance). Differences:
#   * the cycle is run by talonx_paperperf.forward_runner: explicit RUNNING/SUCCESS/PARTIAL/FAILED status in
#     results/v2_validation/forward_runs/<day>.json, classified transient retries in the prices stage, a run deadline;
#   * the terminal log line reports the TRUE state ("cycle_end" + state + exit) -- the old "cycle_done" line was
#     written even when a stage failed;
#   * the loop runs the cycle IMMEDIATELY when started: start it only at a slot (the wrapper sleeps to the next slot
#     first), and it then sleeps to the next 06:00Z, so a failed day is never caught up automatically.
cd /c/workspace/TalonX; PY=.venv/Scripts/python.exe; export PYTHONIOENCODING=utf-8; unset TALONX_OPP_ROOT
L=results/v2_validation/forward.log
until [ -f results/v2_validation/edgar/20260929.done ]; do sleep 300; done
while $PY -c "import sys,datetime as d; sys.exit(0 if d.date.today()<=d.date(2026,10,31) else 1)"; do
  D=$($PY -c "import datetime as d; print(d.date.today())")
  S=$($PY -c "import datetime as d; print(d.datetime.now(d.timezone.utc).replace(minute=0,second=0,microsecond=0).isoformat())")
  $PY -m talonx_paperperf.forward_runner run --scheduled "$S" >> $L 2>&1
  RC=$?
  ST=$($PY -c "import json; print(json.load(open('results/v2_validation/forward_runs/$D.json')).get('state','UNKNOWN'))" 2>/dev/null || echo NO_STATUS_RECORD)
  echo "{\"cycle_end\": \"$(date -u +%FT%TZ)\", \"day\": \"$D\", \"state\": \"$ST\", \"exit\": $RC}" >> $L
  $PY -m talonx_paperperf.forward_runner sleep-to-next-slot
done
echo "{\"loop_end\": \"$(date -u +%FT%TZ)\", \"reason\": \"stop date 2026-10-31 passed\"}" >> $L
