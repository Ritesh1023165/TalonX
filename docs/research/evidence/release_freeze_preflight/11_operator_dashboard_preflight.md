# Operator / dashboard preflight (read-only)
`operator_snapshot` on the fresh release campaign ledger (test `test_freeze_operator_reads_the_fresh_release_campaign_read_only`): file md5 unchanged by the read;
shows campaign id V2-PAPER-RC1, strategy/version, PAPER, starting capital 100,000, settled cash 100,000, no positions / unresolved, no blocks, reconciliation HEALTHY;
restart-continuity guard accepts it. Provider contract, notification state and runtime state come from the status file and notification views (covered by RI-3 / final-acceptance tests).
Dashboard readers honour TALONX_V2_DB_PATH / TALONX_V2_STATUS_PATH (already env-aware; `paths.py` now matches) - the processes started by `start --release` inherit them.
CAVEAT (operator): a dashboard/listener started OUTSIDE the release shell would look at the legacy `v2_lane.db`; start everything from the release shell.
