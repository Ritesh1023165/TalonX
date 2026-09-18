# V2 Release Integration RI-4 — Telegram Physical Provisioning and Controlled Delivery Validation

**Verdict: `RI4_NOT_ACCEPTED`.** This is a bounded pre-flight result, not a
V2 release-acceptance result. No Telegram validation message was sent.

## Repository and safety pre-flight

- Branch and starting HEAD: `feature/task131-option-a-integration` at
  `b46c45ced9e2b8b0dba1984f31ec67d989069177`.
- The worktree was clean at the start. There were no commits after that
  reported RI-3 SHA.
- No Python, Redis, or TalonX process was running. `.run/talonx.pids.json`
  was absent. The checked-in V2 status is stale historical status from
  2026-09-15, rather than evidence of a current market session.
- No production outbox was opened for delivery, no service was started or
  stopped, and no provider, broker, or market session was activated.

## Configuration presence and separation

All configuration inspection loaded the local runtime environment only to
classify fields; it never emitted token, chat ID, URL, or payload values.

| Destination | Token field | Chat field | Effective mode | Resolver enabled | Separation result |
|---|---|---|---|---|---|
| TalonX Signal / `TRADE_EVENT` | CONFIGURED | CONFIGURED | EXPLICIT | yes | Signal/Sentinel pairs are distinct; bot tokens are distinct |
| TalonX Sentinel / `OPERATIONS` | CONFIGURED | CONFIGURED | EXPLICIT | yes | Signal/Sentinel pairs are distinct; bot tokens are distinct |
| TalonX Lab / `RESEARCH` | configured local fields | configured local fields | not eligible for this validation | no | aliases the Signal chat and is rejected by the resolver |

`TALONX_NOTIFY_OPERATIONS_ENABLED` is CONFIGURED (`1`). Legacy primary
credentials are also present, but neither first-release destination relies on
them: both resolve through their explicit pairs.

## Blocking condition

The local environment sets `TALONX_NOTIFY_RESEARCH_ENABLED` to an enabled
value. RI-4 requires Research to remain OFF (`TALONX_NOTIFY_RESEARCH_ENABLED`
must not be enabled), even when the resolver subsequently disables it for
isolation. The resolver did reject Research because its chat aliases Signal,
which prevented a Research send; that protective rejection does not satisfy
the required pre-flight state.

Therefore the two authorized real sends were deliberately not attempted:

| Controlled event | Logical destination | Enqueued | Attempts | Final state |
|---|---|---:|---:|---|
| Signal validation | `TRADE_EVENT` | no | 0 | NOT_SENT — pre-flight blocked |
| Sentinel validation | `OPERATIONS` | no | 0 | NOT_SENT — pre-flight blocked |
| Research validation | `RESEARCH` | no | 0 | NOT_SENT — prohibited |

No isolated validation outbox was created, so no historical or production
pending row could have been consumed. The existing `NotifyStore` plus
`worker.drain` path remains the prescribed durable route for a later approved
validation: event → isolated outbox → destination-specific worker → Telegram
→ `SENT`.

## Regression and operator checks

The existing routing and operator tests were run with
`TALONX_TEST_NETWORK_GUARD=1`:

```powershell
$env:TALONX_TEST_NETWORK_GUARD='1'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp="$env:TEMP\talonx-ri4-pytest-final2" tests/test_ri2_notification_routing.py tests/test_ri3_operator.py
```

Result: **61 passed in 6.73s**. The test fixture now clears explicit Signal
credentials and disables Research in its own `monkeypatch` scope, so its
legacy-primary scenario remains hermetic when a developer has local RI-3
credentials in `.env`.

The read-only operator projection, loaded with the same local environment,
reports Signal and Sentinel as logical routing configured, physically
configured, and `real_delivery_validated: false`; Lab is disabled by the
resolver and also `real_delivery_validated: false`. This is the truthful
configured-versus-validated distinction required at this stage.

## No trading or secret side effects

The read-only V2 state before and after the RI-4 work was identical:

- `v2_lane.db`: 69,632 bytes; SHA-256
  `10e6c542df213221db48278a6018b71656650325dd5585b344a14e3b2e16675e`.
- Settled cash: 300,000.00; open, unresolved, and closed positions: 0.
- Pending entry intents: 0; active account blocks: 0.
- Reserved and available capital are unknown for this legacy fixture because
  its campaign allocation is absent; no value was written or inferred.

The evidence and tracked diff contain no Telegram secret, chat ID, or token
URL. The only implementation change is test isolation in
`tests/test_ri3_operator.py`; it neither sends a message nor changes runtime
configuration.

## Required operator correction before rerun

Set `TALONX_NOTIFY_RESEARCH_ENABLED` to a non-enabled value (normally remove
it or set `0`) in the actual runtime environment. Keep Research credentials
isolated from Signal if they remain configured. Then rerun RI-4 from this
branch; only if that pre-flight passes may it send exactly one harmless Signal
validation and one harmless Sentinel validation through a fresh isolated
outbox.

Provider qualification, prospective-paper validation, and V2 final release
acceptance were not started.
