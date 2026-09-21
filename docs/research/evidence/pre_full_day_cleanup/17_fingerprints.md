# Fingerprints / integrity
V2 STRATEGY FINGERPRINT `e2acf6454789217e` - PROVIDER CONTRACT `V2_RELEASE_PRICE_CONTRACT@1` FINGERPRINT `ac5e51aa3599d6c9` (both checked by the gate and by tests 18).
STRATEGY / PROVIDER / ACCOUNTING RULES CHANGED: NO; CAMPAIGN ECONOMICS CHANGED: NO. Runtime files changed after the frozen SHA (a56ec8c) are an explicit closed list in `preflight.FREEZE_OPS_HARDENING_FILES`
(log redaction, supervisor/dispatch/notify hooks, release gate + entry point, startup label, lifecycle expiry, validation command) - none is a strategy/provider/pricing/accounting/ledger file (test 19); everything else is docs/tests/pin.
Frozen executable release identity for evidence stays `v2-paper-rc1 / a56ec8c`; this is a documented operational-hardening delta on top of it.
