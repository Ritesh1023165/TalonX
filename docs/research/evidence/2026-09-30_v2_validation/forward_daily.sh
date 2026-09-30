#!/usr/bin/env bash
# INSIDER_BUY_CLUSTER_V2@1 SHADOW forward tracker (research only; sends nothing, changes no V2 state).
# Purpose: prospective (post-2026-09-06-freeze) episodes + outcomes. Waits for the Jul-Sep backfill (20260929.done),
# then daily at 06:00Z: crawl EDGAR Form 4 up to yesterday -> episodes -> prices -> evaluate -> forward summary.
# Stop condition: 2026-10-31. Output: results/v2_validation/forward/<date>.json (+ forward.log).
cd /c/workspace/TalonX; PY=.venv/Scripts/python.exe; export PYTHONIOENCODING=utf-8; unset TALONX_OPP_ROOT
L=results/v2_validation/forward.log
until [ -f results/v2_validation/edgar/20260929.done ]; do sleep 300; done
while $PY -c "import sys,datetime as d; sys.exit(0 if d.date.today()<=d.date(2026,10,31) else 1)"; do
  Y=$($PY -c "import datetime as d; print((d.datetime.utcnow()-d.timedelta(days=1)).date())")
  { $PY -m talonx_paperperf.form4_edgar 2026-09-30 "$Y" --rate 4 && $PY -m talonx_paperperf.v2_validation episodes \
    && $PY -m talonx_paperperf.v2_validation prices && $PY -m talonx_paperperf.v2_validation evaluate > /dev/null \
    && $PY -m talonx_paperperf.v2_validation forward; } >> $L 2>&1
  echo "{\"cycle_done\": \"$(date -u +%FT%TZ)\"}" >> $L
  $PY -c "
import datetime as d,time
n=d.datetime.utcnow(); t=(n+d.timedelta(days=1)).replace(hour=6,minute=0,second=0,microsecond=0)
time.sleep(max(60,(t-n).total_seconds()))"
done
