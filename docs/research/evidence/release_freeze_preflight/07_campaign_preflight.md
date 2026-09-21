# Campaign preflight (isolated ledger - same code path as launch)
Source: `campaign_init_isolated.json` (created + verified), `release_gate_on_isolated_campaign.json`, `prospective_preflight_isolated.txt`.

| item | expected | observed |
|---|---|---|
| starting cash | 100,000 | 100,000 |
| settled cash | 100,000 | 100,000 |
| reserved capital | 0 | 0 |
| available cash | 100,000 | 100,000 |
| open positions | 0 | 0 |
| EXIT_UNRESOLVED | 0 | 0 |
| pending entry intents | 0 (total intents 0) | 0 |
| active account blocks | 0 | 0 |
| realized P&L | 0 | 0 |
| dividend receivables | 0 | 0 |
| trades / processed episodes / corporate-action rows | 0 | 0 |
| V2 alert outbox rows (no inherited notification state) | 0 | 0 |
| provenance | SEEDED_AT_CREATION | SEEDED_AT_CREATION |

A second `--init-campaign` is refused (exit 2); a `v2_lane.db` target is refused. The restart-continuity guard accepts the fresh ledger. Release gate READY (18 checks, all PASS).
Real-environment gate with the release env and no ledger yet: READY, one WARN (`campaign_identity`: ledger to be created at launch) - `release_gate_real_environment.json`.
Note: the shared operational notification store `notifications.db` is not campaign-scoped; the V2 Signal outbox lives in the campaign ledger and is empty.
