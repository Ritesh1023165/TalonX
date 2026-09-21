# Follow-up Investigation — Admission-Mode Reporting Provenance (2026-09-15)

**Trigger**: a later live `/ping` (03:43Z) confirmed collection=569 and
execution scope=626 (both fixes verified working) but still reported
admission=PERMISSIVE. Directed to resolve definitively before declaring
configuration restoration complete.

## 1. Actual behavior vs. reporting

Inspected the real, running V2 companion's own code path, not shell
variables alone: `talonx_v2/service.py:173` —
`self.durable_store_gate_enabled = _env_flag("TALONX_V2_DURABLE_STORE_
ENABLED", default=False)`, read ONCE at the companion's own `__init__`,
in ITS OWN process. This is the actual, authoritative value the running
companion's admission logic uses (lines 433, 707). It was **never
exposed** in `v2_service_status.json` before this fix — meaning /ping and
the dashboard each independently RE-DERIVED the same env var name in
THEIR OWN separate process (Original / Dashboard), never actually reading
the companion's real state. This is a genuine reporting-provenance defect
in its own right, regardless of what the correct value should be — the
exact class of cross-process env-propagation gap already demonstrated
twice tonight (broad-discovery, delivery-enablement).

## 2. Is PERMISSIVE the correct restored value?

Searched this campaign's full audit trail (`docs/audits/task117*/`,
`docs/research/evidence/task13*`, `results/task112*`) for any evidence
`TALONX_V2_DURABLE_STORE_ENABLED` was ever explicitly set for THIS live
deployment. **None found** — unlike broad-discovery and delivery-
enablement, where direct evidence proved they WERE active before the
reboot (real 569-symbol collection, a real sent Telegram message).
`docs/research/TASK131_RETROSPECTIVE.md` states explicitly: **"V2Service's
own runtime default (outside pytest, no env override) remains `False`,
per the literal remediation requirement."**

**Conclusion: PERMISSIVE is genuine, documented, unchanged V2 behavior —
not a restoration regression.** It was NOT flipped to GATED, because:
(a) no evidence supports GATED ever being this deployment's authorized
live state, and (b) the governing directive explicitly requires
preserving "V2 admission... rules" unchanged and prohibits admission/
strategy tuning without evidence-backed authorization.

## 3. Fix applied (reporting provenance, not behavior)

- `talonx_v2/service.py`: `durable_store_gate_enabled` now included in
  `v2_service_status.json`'s own output — the authoritative, same-
  process source.
- `talonx_dispatch/telegram_listener.py` (`/ping`) and
  `talonx_ops/dashboard_read.py`: both now prefer this field when present,
  labelling the source explicitly (`"source: live companion"` vs the old
  env-derived fallback, now labelled `"unverified against the actual
  companion"` for a status file predating this field).

## 4. Verified live (not shell inspection alone)

- `v2_service_status.json` (written by the real running companion, PID
  20912→13572 after the managed restart below): `"durable_store_gate_
  enabled": false` — directly confirmed.
- `DashboardReadModel.v2_broad_discovery()` against the live `~/.talonx`
  home: `admission_policy.source == "live companion (v2_service_status.
  json)"`, `mode == "PERMISSIVE"` — reads the authoritative field, not a
  re-derivation.
- Accounting matched exactly across the restart (cash $300,000.00 / V2,
  $10,000.00 / Original; outbox AMBIGUOUS 2, EXPIRED 25068, PENDING 172,
  SENT 264, 0 IN_FLIGHT — every figure identical before/after).
- V2 fingerprint unchanged: `11107198c5b81237`.
- Single owner per component confirmed via full process listing;
  dashboard `200 OK`.

## 5. Integrated test

`tests/test_task114_prospective.py::
test_start_stack_full_authorized_configuration_together` — one
`start_stack()` call proving broad collection, expanded execution scope,
an operator-supplied GATED-admission override, Intelligence delivery
enabled, and routine digest correctly left OFF all propagate
consistently together, without any flag silently implying or
overriding another. Demonstrates the launcher's capability for an
operator who DOES want GATED admission (a simple
`TALONX_V2_DURABLE_STORE_ENABLED=1` in `env`/`.env`), without this
report claiming that state is currently authorized or active.

## 6. Restart

One stop_stack()/start_stack() cycle of the SAME existing session
(`results/prospective_2026-09-15`) — not a second stack. All 6 processes
(supervisor + 4 children + V2 companion) restarted together since 3 of
them (Original, Dashboard, V2 companion) needed the fix and V2 companion
has no independent auto-restart mechanism of its own, making a surgical
per-process restart materially riskier than the already-proven stop/
start cycle used twice earlier tonight. Intelligence was restarted as an
accepted side effect (not itself needing this fix); its own recovery
mechanism (`reconcile_and_enrich`, Task 133) makes this safe -- no event
is silently orphaned by a mid-cycle restart.
