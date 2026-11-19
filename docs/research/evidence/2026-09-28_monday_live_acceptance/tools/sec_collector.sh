#!/usr/bin/env bash
# PURPOSE: bounded SEC live-acceptance evidence collection (read-only).
# STOP: runs once at $1 (UTC ISO; default 16:00Z) and exits.
# OUTPUT: results/monday_2026-09-28/sec_live_<HHMM>.json, tracks_<HHMM>.json
set -u
cd /c/workspace/TalonX
M=results/monday_2026-09-28
PY=.venv/Scripts/python.exe
T=${1:-2026-09-28T16:00:00+00:00}
export PYTHONIOENCODING=utf-8
until $PY -c "import sys,datetime as d; sys.exit(0 if d.datetime.now(d.timezone.utc)>=d.datetime.fromisoformat('$T') else 1)"; do sleep 60; done
TAG=${T:11:2}${T:14:2}
env -u TALONX_OPP_ROOT $PY docs/research/evidence/2026-09-26_p0_package1/tools/live_acceptance.py 2026-09-28 > $M/sec_live_$TAG.json 2>&1
( cd results/continuous_fullday_2026-09-25 && env -u TALONX_OPP_ROOT TRACK_SINCE=2026-09-28T07:00:00+00:00 ../../$PY live_tracks.py > ../monday_2026-09-28/tracks_$TAG.json 2>&1 )
echo SEC_COLLECT_DONE $TAG $(date -u +%T)
