# V2 Release Integration RI-4 — Telegram Physical Provisioning and Controlled Delivery Validation

**Verdict: `RI4_ACCEPTED`.** This accepts only the Telegram provisioning and
controlled-delivery gate. It does not accept V2 for release.

## Repository and safety pre-flight

- Branch start: `feature/task131-option-a-integration` at
  `b46c45ced9e2b8b0dba1984f31ec67d989069177`.
- RI-4 pre-delivery commit: `99a67b5b97afbb2bd081c7a1dc42185c9f8434f0`.
- No Python, Redis, or TalonX process was running at the delivery pre-flight;
  `.run/talonx.pids.json` was absent. The checked-in V2 status is historical,
  not evidence of a current market session.
- No production outbox was opened, no service was started or stopped, and no
  provider, broker, or market session was activated.

## Configuration and isolation

Configuration inspection classified values only; it did not emit token, chat
ID, URL, or payload values.

| Destination | Token field | Chat field | Effective mode | Delivery enabled | Result |
|---|---|---|---|---|---|
| TalonX Signal / `TRADE_EVENT` | CONFIGURED | CONFIGURED | EXPLICIT | yes | distinct from Sentinel |
| TalonX Sentinel / `OPERATIONS` | CONFIGURED | CONFIGURED | EXPLICIT | yes | distinct from Signal |
| TalonX Lab / `RESEARCH` | not evaluated for delivery | not evaluated for delivery | OFF | no | no event sent |

`TALONX_NOTIFY_OPERATIONS_ENABLED` is configured. Signal and Sentinel have
different effective destination pairs and different bot credentials. Legacy
primary settings may remain present for compatibility, but neither
first-release destination resolved through them.

Research was corrected to an OFF flag before delivery. Its resolver remained
disabled and no Research row existed in the isolated validation outbox.

## Controlled durable delivery

The validation used a fresh temporary SQLite `NotifyStore`, never the
production outbox. Each event followed the existing durable path:

`validation event → isolated outbox PENDING → destination-specific worker → Telegram → SENT`

| Destination | Event ID | Enqueue state | Attempts | Final state |
|---|---|---|---:|---|
| `TRADE_EVENT` / TalonX Signal | `ri4-signal-300d2e5b09534d518e3818d9e693c61e` | PENDING | 1 | SENT |
| `OPERATIONS` / TalonX Sentinel | `ri4-sentinel-deb6b2acb8364f8583d9e943a9fa2250` | PENDING | 1 | SENT |
| `RESEARCH` / TalonX Lab | none | not enqueued | 0 | no delivery |

Both messages were harmless release-validation notices stating that no trade
was executed / no incident was detected and no action was required. The
worker selected the destination on each row, the two effective pairs were
distinct, and the outbox contained zero Research rows. This proves Signal
validation routed to Signal and Sentinel validation routed to Sentinel; there
is no cross-destination fallback in the completed delivery path.

`delivery_validation.json` is sanitized evidence. It contains only logical
event IDs, state, attempt count, timestamp, and a one-way fingerprint of the
active destination pair. `operator_read` accepts it only when explicitly
selected through `TALONX_NOTIFY_VALIDATION_PATH`, the schema/kind match, the
state is `SENT`, and the fingerprint matches the current pair. A changed
credential or chat fails closed to not validated.

## Operator visibility and tests

The operator projection now distinguishes physical configuration from a
validated delivery. With `TALONX_NOTIFY_VALIDATION_PATH` set to this record,
Signal and Sentinel report `real_delivery_validated: true`; Lab remains false.
No raw credentials are read into operator output.

The focused routing/operator suite was run with fake transport and network
guard enabled:

```powershell
$env:TALONX_TEST_NETWORK_GUARD='1'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp="$env:TEMP\talonx-ri4-operator-validation" tests/test_ri2_notification_routing.py tests/test_ri3_operator.py
```

Result: **62 passed in 6.43s**. The RI-3 legacy-primary fixture was also made
hermetic when a developer has explicit RI-3 credentials in `.env`.

## No trading or secret side effects

The read-only V2 state before validation was: settled cash 300,000.00; zero
open, unresolved, or closed positions; zero pending entry intents; and zero
active account blocks. `v2_lane.db` was 69,632 bytes with SHA-256
`10e6c542df213221db48278a6018b71656650325dd5585b344a14e3b2e16675e`.

The post-validation read-only capture matched that state and hash. The evidence
and tracked diff contain no bot token, chat ID, Telegram token URL, payload
credential, or production-outbox content.

Provider qualification, prospective-paper validation, and V2 final release
acceptance were not started.
