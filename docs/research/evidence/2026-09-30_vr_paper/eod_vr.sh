#!/usr/bin/env bash
# VR_PAPER_V1 EOD (research, read-only on production). Purpose: VIRTUAL_REALTIME vs ACTIONABLE lifecycle EOD from the
# live tracker + CONTROL vs SHADOW (pullback / reversion reference) replay for one window.
# Waits for the nightly profitability forensic of WID (results/profitability/WID.json), then runs once.
# Stop condition: one run (or give up 2 days after WID). Output: results/vr_paper/eod_WID.json,
# results/vr_paper/replay_WID.json, results/vr_paper/eod_WID.log
cd /c/workspace/TalonX; PY=.venv/Scripts/python.exe; export PYTHONIOENCODING=utf-8; unset TALONX_OPP_ROOT
W=${1:?WID}; L=results/vr_paper/eod_$W.log
until [ -f results/profitability/$W.json ]; do
  $PY -c "import sys,datetime as d; sys.exit(0 if d.date.today()<=d.date.fromisoformat('$W')+d.timedelta(days=2) else 1)" || { echo GIVE_UP >> $L; exit 1; }
  sleep 300
done
sleep 120
$PY -m talonx_paperperf.vr_live eod $W >> $L 2>&1
$PY -m talonx_paperperf.vr_replay $W >> $L 2>&1
echo "{\"vr_eod_done\": \"$(date -u +%FT%TZ)\"}" >> $L
