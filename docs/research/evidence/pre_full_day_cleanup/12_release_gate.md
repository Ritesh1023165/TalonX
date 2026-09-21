# Release gate (TASK K) - read-only, `release_gate_current_env.json`
**RELEASE GATE: NOT_READY - solely because of `compromised_credentials_rotated` (ROTATION_REQUIRED for the two exposed bot tokens).** All other 19 checks PASS: SIP mode, provider QUALIFIED, provider fp `ac5e51aa3599d6c9`, strategy fp `e2acf6454789217e`,
paper-only, release campaign config + identity, Signal/Sentinel configured + distinct, Lab OFF, validation bound, delivery enabled, `release_notification_store` (isolated release outbox, no contamination), no account block, ledger reconciles.
Telegram-related gate status reported separately: Signal PASS; Sentinel credential FAIL (compromised); validation-bound PASS until rotation.
