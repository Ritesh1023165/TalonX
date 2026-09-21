# Full-day paper session - operator checklist (no new strategy metrics)

## PRE-OPEN
- [ ] `git rev-parse v2-paper-rc1^{commit}` = a56ec8c8d10adb36a113ebd373204f297c230081; HEAD on `main` descends from it (preflight `repo_head_matches_release` READY)
- [ ] `git status` clean except the two untracked notifications.db-shm/-wal test artifacts (preflight `repo_tree_clean` FINDING is non-blocking)
- [ ] release env exported (same window); `--init-campaign` done once; `--verify-campaign` clean on day 0
- [ ] `python -m talonx_v2.release_gate` READY (provider QUALIFIED, contract ac5e51aa3599d6c9, strategy e2acf6454789217e, Signal + Sentinel validated, Lab OFF, campaign PASS)
- [ ] no stale TalonX process; ports free; Redis reachable; disk space; legacy `v2_lane.db` md5 still cff00b0f... (untouched)
- [ ] launch command run once; `start` prints READY; /ping from Signal shows Release mode ON, SIP contract line, Campaign V2-PAPER-RC1, blocks none

## DURING SESSION
- [ ] /ping checkpoints (~30 min): runtime/heartbeat fresh, market-data health, account blocks none, EXIT_UNRESOLVED 0
- [ ] provider health (rate limit / outage flags); V2 opportunity counts; paper fills (whole share, fee-inclusive <= $10,000)
- [ ] Signal deliveries (ENTRY_INTENT/BUY/SELL) arrive in TalonX Signal; Sentinel alerts arrive in TalonX Sentinel only; Lab silent
- [ ] any account block or EXIT_UNRESOLVED -> investigate (Sentinel alert); never clear a block without the audited path
- [ ] dashboard (:8787) shows the release campaign (not the legacy $300k)

## EOD (after the XNYS close; provider bars are final only at close+4h+16min)
- [ ] new-entry boundary: pre-open intents only; nothing else expected intraday
- [ ] due exits (Session-10 / +5 recovery) resolved or EXIT_UNRESOLVED surfaced; dividend ACCRUED/CREDITED state
- [ ] `.venv\Scripts\python.exe -m talonx_ops.prospective close` (same window/env): reconciliation, cash, positions, notifications, provider errors
- [ ] evidence in `results/prospective_<date>/` incl. `v2_release_rc1.db.eod-copy`-style copy and status
- [ ] STOP; do not edit strategy/thresholds; report findings
