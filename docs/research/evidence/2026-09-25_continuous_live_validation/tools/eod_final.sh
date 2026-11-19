#!/usr/bin/env bash
# Final end-of-session evidence pass (read-only). Waits until $1 (UTC ISO), then collects everything once.
set -u
cd /c/workspace/TalonX
E=results/continuous_fullday_2026-09-25
PY=.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8
until $PY -c "import sys,datetime as d; sys.exit(0 if d.datetime.now(d.timezone.utc)>=d.datetime.fromisoformat('$1') else 1)"; do sleep 60; done
env -u TALONX_OPP_ROOT $PY $E/eod_evidence.py > $E/eod_evidence_final.json 2> $E/eod_evidence_final.err
for s in $($PY -c "
import json;d=json.load(open('$E/eod_evidence_final.json',encoding='utf-8'))
print(' '.join(x['slot']+','+(x['next_scan'] or '') for x in d['skipped_slots'] if x['slot']>='20:50'))"); do
  slot=${s%,*}; nxt=${s#*,}; f=$E/skip_${slot/:/}.json
  [ -s "$f" ] || env -u TALONX_OPP_ROOT $PY $E/skip_impact.py 2026-09-25T${slot}:00+00:00 2026-09-25T${nxt}+00:00 > $f 2>&1
done
( cd $E && env -u TALONX_OPP_ROOT ../../$PY live_tracks.py > tracks_final.json 2> tracks_final.err )
( cd $E && env -u TALONX_OPP_ROOT ../../$PY studies2.py > s2_final.json 2> s2_final.err )
env -u TALONX_OPP_ROOT $PY $E/eod_evidence.py > $E/eod_evidence_final.json 2>> $E/eod_evidence_final.err
echo EOD_FINAL_DONE $(date -u +%T)
