# Campaign verification (TASK J) - no re-init
`python -m talonx_v2.release_gate --verify-campaign` in the release environment (`campaign_verify.json`):
**CAMPAIGN: V2-PAPER-RC1 - CAMPAIGN STATE: CLEAN** (continuation rule). cash 100,000 = starting 100,000; 0 open/closed positions; reserved $0; 0 pending intents (0 total); 0 blocks; 0 EXIT_UNRESOLVED; realized P&L 0; 0 dividend receivables; 0 trades; 0 outbox rows;
provenance SEEDED_AT_CREATION. The 2 `processed_episodes` rows (ABCL `SKIPPED_ENTRY_STALE`, ADC `SKIPPED_NO_PRIOR_INTENT`) are the canary's non-economic skip records; the verify mode now allows exactly that
(`--verify-campaign` = continuation; `--init-campaign` remains strict) and any non-SKIPPED episode still fails (test_21). Note: ADC's SKIPPED record is terminal - that cluster will not be entered later.
