# Campaign decision

**CAMPAIGN: NEW** (`V2-PAPER-RC1`). The legacy $300k campaign (`v2_lane.db`, no campaign record) is NOT continued and NOT touched (md5 unchanged).

**CAMPAIGN CREATION: PREPARED_FOR_CREATION_AT_LAUNCH** - chosen deliberately:
- One campaign == one ledger file (the `campaign` table is a single row). A clean $100k campaign therefore needs its own ledger, not a reset of `v2_lane.db`.
- The operator preflight refuses to run without an existing ledger ("never recreate"), so creation is an explicit, one-time, operator-run pre-open step:
  `python -m talonx_v2.release_gate --init-campaign` (create-once; refuses an existing file; refuses the legacy `v2_lane.db`; verifies the ledger is clean).
- Nothing was created in the production location in this task. The exact creation was proven in an isolated temp directory
  (`campaign_init_isolated.json`, `release_gate_on_isolated_campaign.json`, `prospective_preflight_isolated.txt`).

| field | value |
|---|---|
| campaign_id | V2-PAPER-RC1 |
| ledger / status file | `v2_release_rc1.db` / `v2_release_rc1_status.json` (repo root; selected via TALONX_V2_DB_PATH / TALONX_V2_STATUS_PATH) |
| strategy / version | INSIDER_BUY_CLUSTER_V2 / INSIDER_BUY_CLUSTER_V2@1 |
| execution mode | PAPER (real capital disabled) |
| starting cash / allocation | $100,000 / $10,000 fee-inclusive |
| provider contract | V2_RELEASE_PRICE_CONTRACT@1, ac5e51aa3599d6c9 |
| strategy fingerprint (recorded on the campaign row) | e2acf6454789217e |

**Guard against running the release on the wrong ledger.** The release gate FAILS (and `--release` refuses to start) unless the campaign id, cash, allocation
and mode env match the release campaign, the ledger is not `v2_lane.db`, and - if the ledger exists - its campaign row is `SEEDED_AT_CREATION` with the release identity.
