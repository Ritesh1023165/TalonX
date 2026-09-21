# Telegram preflight - NO real message was sent
Gate checks (real environment): `signal_destination_configured`, `sentinel_destination_configured`, `signal_sentinel_distinct`, `lab_off`,
`signal_delivery_validation_bound`, `sentinel_delivery_validation_bound`, `signal_delivery_enabled` - all PASS.
- TalonX Signal (TRADE_EVENT): dedicated credentials; the prior RI-4 physical validation's one-way fingerprint matches the ACTIVE configuration.
- TalonX Sentinel (OPERATIONS): same.
- TalonX Lab (RESEARCH): OFF (double opt-in not set).
- `--release` still requires `--deliver --transport telegram` (gate `signal_delivery_enabled`, and `start_stack` raises otherwise) - tests: acceptance suite.
- Intelligence card delivery OFF. No token/chat value is emitted anywhere in evidence.
