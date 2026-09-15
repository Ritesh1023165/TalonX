# GATED Admission — Explicit Operator Authorization Applied (2026-09-15)

**Authorization**: the operator explicitly authorized
`TALONX_V2_DURABLE_STORE_ENABLED=True` for this development campaign,
superseding the PERMISSIVE default, with all other strategy/pricing/
expiry/reservation/exit rules preserved unchanged. This directive
explicitly accepted the companion-sourced reporting fix from the prior
investigation and asked that the historical-activity investigation not
be repeated.

## 1. Persisted through the supported configuration path

Appended to `.env` (gitignored, not committed) — the SAME file Task 132
already wired `load_dotenv()` for — rather than an ad-hoc interactive
shell export (the fragile pattern that caused every gap found tonight):

```
TALONX_V2_DURABLE_STORE_ENABLED=true
```

This survives a host restart, unlike a shell-session export.

## 2. Applied via the minimum supported managed lifecycle action available

No targeted "restart just the V2 companion" primitive exists in this
codebase (the V2 companion has no independent auto-restart mechanism the
way supervisor-owned children do, and a manual kill+respawn would require
re-implementing the lock-acquire/rebind sequence outside the tested,
supported path). The smallest fully-supported action is one
`stop_stack()`/`start_stack()` cycle of the SAME existing session
(`results/prospective_2026-09-15`) — the same mechanism already used
successfully 3 times earlier tonight, never a second stack.

## 3. Verified in the real child process and a fresh status snapshot

- `v2_service_status.json` (written by the actual running companion):
  `"durable_store_gate_enabled": true` — direct, same-process
  confirmation.
- `DashboardReadModel.v2_broad_discovery()["admission_policy"]`:
  `{"mode": "GATED", "source": "live companion (v2_service_status.json)",
  ...}` — the dashboard read path reflects the authoritative source.
- `/ping`'s own admission-mode line reads the identical field (same code
  path as the dashboard fix, `talonx_dispatch/telegram_listener.py`) --
  confirmed by code identity; not separately round-tripped through a
  live Telegram message.

## 4. Broad collection / expanded execution / delivery / digest-off — all still correctly configured

Post-cutover live confirmation (`post_gated_admission_cutover_heartbeat.
json`):

- `effective_symbols`: 569 (broad collection unaffected).
- `execution_scope_enforced: true` (expanded execution unaffected).
- `last_cycle.delivery.mode: "enabled"` (Intelligence delivery still
  active).
- `last_cycle.delivery.DIGEST.held_reason: "digest_not_due"` (digest
  still off by default -- `TALONX_INTEL_DELIVER_DIGEST_ENABLED` was not
  added to `.env`, confirmed unchanged).

## 5. Accounting and obligations preserved

| | before | after |
|---|---|---|
| V2 cash | $300,000.00 | $300,000.00 |
| V2 open positions | 0 | 0 |
| Original cash | $10,000.00 | $10,000.00 |
| intelligence_delivery AMBIGUOUS | 2 | 2 |
| intelligence_delivery IN_FLIGHT | 0 | 0 |
| V2 fingerprint | `11107198c5b81237` | `11107198c5b81237` |

Single owner per component confirmed via full process listing; dashboard
`200 OK`.

## 6. New isolated test

`test_start_stack_full_authorized_configuration_together`
(`tests/test_task114_prospective.py`) already covers this exact
combination end-to-end at the launcher-wiring level (broad collection +
expanded execution + an operator-supplied GATED override + delivery +
digest-off, all together, none silently overriding another) — no
additional test needed for the activation itself.

## What changed vs. what did not

**Changed**: `TALONX_V2_DURABLE_STORE_ENABLED` is now `true`, persisted
in `.env`. This is a REAL admission-policy change, explicitly authorized
by the operator this turn -- from now on, a durable PENDING intent is
REQUIRED before any V2 entry, and a hard cash/slot reservation gate
applies at intent-creation time (per `docs/research/TASK131_
REMEDIATION_DESIGN.md` Directive 6's own documented GATED semantics).

**Unchanged**: pricing, expiry (`exit_fallforward_max_sessions`), the
hold period (10 trading sessions), reservation mechanics, exit rules, the
frozen strategy fingerprint, and every other V2Config value — none of
these were touched.
