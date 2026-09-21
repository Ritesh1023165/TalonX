# RELEASE FREEZE + PREFLIGHT + CONTROLLED MERGE - `v2-paper-rc1`

**Verdict: RELEASE_FREEZE_PREFLIGHT_ACCEPTED_WITH_BOUNDED_FOLLOWUPS**

- FROZEN RELEASE SHA: `a56ec8c8d10adb36a113ebd373204f297c230081` (tag `v2-paper-rc1`); accepted candidate `b723901` + the release-freeze mechanism only
- V2 STRATEGY FINGERPRINT `e2acf6454789217e` - PROVIDER CONTRACT `V2_RELEASE_PRICE_CONTRACT@1` FINGERPRINT `ac5e51aa3599d6c9` (Alpaca SIP, 1Day, adjustment=split, no fallback)
- RELEASE PRICING MODE: SIP - CSV USED FOR RELEASE: NO
- CAMPAIGN: NEW `V2-PAPER-RC1`, $100,000 / $10,000, PAPER; CREATION: PREPARED_FOR_CREATION_AT_LAUNCH; CAMPAIGN STATE: CLEAN (proven in an isolated ledger)
- Legacy $300k campaign (`v2_lane.db`) untouched (md5 cff00b0f...)
- TALONX SIGNAL READY - TALONX SENTINEL READY - TALONX LAB OFF - PING READY (owner: TalonX Signal / primary listener)
- FULL-DAY PAPER SESSION: NOT_STARTED - PROSPECTIVE VALIDATION: NOT_STARTED - REAL-MONEY TRADING: NOT_ENABLED - REAL TELEGRAM TEST SEND: NO - V2 PROFITABILITY: UNPROVEN

## Why a freeze commit was needed
The accepted candidate could not run a clean second campaign: one campaign is one ledger, the operator hard-defaulted to the legacy `v2_lane.db` with $300k, and the release gate did not
check campaign identity. The freeze adds (only) release mechanism: a dedicated campaign ledger selected by env, a gate that refuses any non-release identity, create-once campaign creation, and a
frozen-SHA pin check (a frozen SHA cannot contain its own hash, so descendants that change only docs/tests/pin are accepted). No strategy, provider, pricing or accounting file changed.
It also fixed a latent defect: `start --release` handed the gate only the 4 resolved env vars (the real launch would have seen no credentials); it now passes the full environment.

## Main
Direct push to `main` is refused by the active repository ruleset (pull request required). Merged via pull request with a merge commit (not squash/rebase), preserving the frozen SHA. See `16_merge_method.md`.

## Files
01 repository state - 02 accepted baseline - 03 freeze metadata - 04 tag metadata - 05 fingerprints - 06 campaign decision - 07 campaign preflight - 08 provider - 09 Telegram -
10 /ping - 11 operator/dashboard - 12 EOD/reconciliation - 13 exact launch procedure (NOT run) - 14 operator checklist - 15 main divergence audit - 16 merge method -
17 post-merge verification - 18 smoke evidence - 19 bounded follow-ups - 20 verdict - plus raw outputs: `release_gate_real_environment.json`, `release_gate_on_isolated_campaign.json`,
`release_gate_on_main.json`, `campaign_init_isolated.json`, `prospective_preflight_isolated.txt`, `provider_liquidity_window_probe.txt`, `eod_reconcile_isolated_campaign.txt`, `post_merge_gate_and_pin.txt`.
