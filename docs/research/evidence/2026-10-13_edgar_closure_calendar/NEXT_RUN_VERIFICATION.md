# 2026-10-14 natural run: end-to-end verification of the EDGAR closure correction

**Status: PENDING.**
- The run is scheduled for **2026-10-14 06:00Z (07:00 BST)**. At 2026-10-13 22:2xZ it was not yet due.
- Do not trigger it.
- The correction is **not** declared end-to-end verified until this natural run supplies the evidence below.

## Read-only check, after 07:00 BST

Run from `C:\workspace\TalonX` (status fields only; no outcome file opened):

```powershell
.venv\Scripts\python.exe -c "import json; x=json.load(open('results/v2_validation/forward_runs/2026-10-14.json',encoding='utf-8')); print({k:x.get(k) for k in ('run_id','runner_version','state','scheduled_utc','started_utc','ended_utc','deadline_utc','failed_stage','error_class')}); print('cutoffs', x.get('cutoffs')); [print(s['name'], s['state'], s.get('exit_code')) for s in x['stages']]; a=x['stages'][0].get('acquisition') or {}; print('calendar', a.get('calendar')); print('days_sec_closed', a.get('days_sec_closed'), '| index_not_found', a.get('days_index_not_found'), '| crawl', a.get('state'), a.get('acquisition_result'), a.get('cause')); print('artifact validated', (x.get('artifact') or {}).get('validated'), '| persistence_retries', len(x.get('persistence_retries') or []))"
Get-ChildItem results\v2_validation\forward_runs -Filter '2026-10-14.*.persistence_failure.*.json' | Select-Object Name
Test-Path results\v2_validation\edgar\20261012.done ; Test-Path results\v2_validation\edgar\20261012.jsonl
```

## Expected for a verified correction

| Check | Expected |
|---|---|
| Runner | `runner_version` begins `forward_runner v1.2` |
| Calendar | `calendar.calendar_id = EDGAR_CLOSURES_V1`, `sha256 = a03cdf54c3b448d77eebbc237d5eb3a7cdc6d0f41203f5109538f8bf992949e3` |
| Closure | `days_sec_closed` contains `2026-10-12` |
| No fake data | Both `Test-Path` lines print `False` (no fake `.done` or `.jsonl` for 10-12) |
| Run | Terminal `state`; stage exit codes recorded; cutoffs info ≤ 2026-10-13 and prices ≤ 2026-10-13 |
| Artifact | `validated` as recorded by the runner (never inferred from a file's existence) |
| Persistence | No `persistence_failure` diagnostic |
| Dashboard (`:8787` Validation → V2@1 forward tracker runs) | If SUCCESS: 7 succeeded, 3 incomplete (10-05, 10-11, 10-13), 5 unverified (09-30 … 10-04), 17 not yet due, 32 total |

If the crawl fails on an **expected** filing day, that is the unchanged acquisition rule working, not a failure of the
closure correction. Report it as is.
