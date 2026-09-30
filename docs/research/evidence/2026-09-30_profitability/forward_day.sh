#!/usr/bin/env bash
# Forward alpha validation -- one session (read-only). usage: forward_day.sh WINDOW NEXT_DAY
# PURPOSE: TRACK A/B live (every 15 min 13:50Z..20:40Z): CONTROL vs SHADOW(SQF_V1) outcomes so far;
#          TRACK E EOD (NEXT_DAY 00:40Z): full forensic, append the session to forward_alpha_validation.md,
#          cumulative CONTROL vs SHADOW checkpoint, refreshed combined report.
# OUTPUT: results/profitability/live_<WINDOW>.log, <WINDOW>*.json, forward_<WINDOW>_eod.txt.
# STOP: exits after the EOD step (one run per session; no duplicate trackers).
set -u
cd /c/workspace/TalonX
PY=.venv/Scripts/python.exe
W=$1; N=$2
L=results/profitability/live_${W}.log
export PYTHONIOENCODING=utf-8; unset TALONX_OPP_ROOT
wait_until() { until $PY -c "import sys,datetime as d; sys.exit(0 if d.datetime.now(d.timezone.utc)>=d.datetime.fromisoformat('$1') else 1)"; do sleep 60; done; }
before() { $PY -c "import sys,datetime as d; sys.exit(0 if d.datetime.now(d.timezone.utc)<d.datetime.fromisoformat('$1') else 1)"; }
wait_until "${W}T13:50:00+00:00"
while before "${W}T20:40:00+00:00"; do
  { date -u +%FT%TZ; $PY -m talonx_paperperf.signal_forensics $W --live; $PY -m talonx_paperperf.forward day $W --live; } >> $L 2>&1
  sleep 900
done
wait_until "${N}T00:40:00+00:00"
E=results/profitability/forward_${W}_eod.txt
{ $PY -m talonx_paperperf.signal_forensics $W; $PY -m talonx_paperperf.forward append $W;
  $PY -m talonx_paperperf.forward day $W; echo "--- CUMULATIVE"; $PY -m talonx_paperperf.forward cumulative;
  WINS=$(ls results/profitability/20??-??-??.json | xargs -n1 basename | sed 's/.json//' | tr '\n' ' ');
  $PY -m talonx_paperperf.signal_forensics combine $WINS; } > $E 2>&1
echo "FORWARD_EOD ${W}: $(grep -E 'CURRENT_VERDICT' $E | tail -1)"
