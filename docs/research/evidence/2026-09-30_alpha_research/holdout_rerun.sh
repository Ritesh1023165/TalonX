#!/usr/bin/env bash
# One-shot: descriptive holdout re-run of every alpha hypothesis on 2026-09-30 (unseen at analysis time) after the
# forward EOD forensic has produced results/profitability/2026-09-30.json. OUTPUT: results/alpha_research/. STOP: one run.
cd /c/workspace/TalonX; PY=.venv/Scripts/python.exe; export PYTHONIOENCODING=utf-8; unset TALONX_OPP_ROOT
until [ -f results/profitability/2026-09-30.json ] && $PY -c "import sys,datetime as d; sys.exit(0 if d.datetime.now(d.timezone.utc)>=d.datetime(2026,10,1,1,0,tzinfo=d.timezone.utc) else 1)"; do sleep 120; done
$PY -m talonx_paperperf.alpha_hypotheses 2026-09-30 > results/alpha_research/holdout_2026-09-30.txt 2>&1
echo "HOLDOUT 2026-09-30: $(grep -E '^H0_CONTROL|^H4_REVERSION' results/alpha_research/holdout_2026-09-30.txt | tr '\n' ' ')"
