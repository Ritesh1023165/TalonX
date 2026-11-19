#!/usr/bin/env bash
# Daily EOD PAPER_SIGNAL profitability report (read-only). usage: eod_profit.sh WINDOW NEXT_DAY
# PURPOSE: after the session, reconstruct every Signal of WINDOW (research + actionable entry, measured spread,
# horizons, portfolio, concentration, strata, DTU) and refresh the combined report over every analysed window.
# OUTPUT: results/profitability/<WINDOW>*.json, combined.json. STOP: exits after one run at NEXT_DAY 00:40Z.
set -u
cd /c/workspace/TalonX
PY=.venv/Scripts/python.exe
W=$1; N=$2
export PYTHONIOENCODING=utf-8; unset TALONX_OPP_ROOT
until $PY -c "import sys,datetime as d; sys.exit(0 if d.datetime.now(d.timezone.utc)>=d.datetime.fromisoformat('${N}T00:40:00+00:00') else 1)"; do sleep 60; done
$PY -m talonx_paperperf.signal_forensics $W
WINS=$(ls results/profitability/20??-??-??.json | xargs -n1 basename | sed 's/.json//' | tr '\n' ' ')
$PY -m talonx_paperperf.signal_forensics combine $WINS
echo "EOD_PROFIT ${W} done; combined over: ${WINS}"
