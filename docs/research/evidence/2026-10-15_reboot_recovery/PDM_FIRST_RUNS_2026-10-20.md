# PDM_V1 first runs and V2 forward 2026-10-20: read-only check at 06:14Z

**Both PDM triggers ran cleanly; forward SUCCESS.** Operational metadata only. No markout value, return or `results`
table row was read, and nothing was run, restarted or launched.

## PDM_V1 (`\TalonX\PDM_V1_Collector`)

| Run | Trigger (London) | Started → finished (UTC) | State | Registered / observations created | Acquisition |
|---|---|---|---|---|---|
| 1 | 00:15 | 2026-10-19 23:15:00 → 23:20:04 | ENABLED | 50 / 50 | 200 requests (entry/exit bar + quote × 50), 0 errors, 50 due / 50 processed, 0 deferred, budget not exhausted, R5 not reached |
| 2 | 06:30 | 2026-10-20 05:30:00 → 05:30:02 | ENABLED | 0 / 0 (nothing new) | 0 requests, 0 errors |

- **Task Scheduler:** LastRunTime 2026-10-20 05:30Z, LastTaskResult 0, missed runs 0, next 2026-10-20 23:15Z.
  - Exactly two run records, so no unexpected extra runs.
  - The Task Scheduler operational event log returned no entries (it appears not to be enabled). The run records
    above are the evidence.
- **Integrity:** `verify_integrity` OK after the runs.
- **Deliveries registered:** 50, all `DELIVERED_CLEAN` (session 2026-10-19 = all 50 V3 review alerts of that day,
  each with a delivery trace).
- **Observation states (operational):**
  - 49 MEASURED (exact target bars retrieved, cost state OK).
  - 1 `MISSING_EXIT_BAR` ("entry=OK exit=ABSENT": the provider returned no trade bar for that exit minute). This is
    a protocol-defined state, not an acquisition error.
- **Inputs:** 200 RETRIEVED from `alpaca:sip:v2`. Acquisition errors 0.
- **Study:** not complete; endpoint 2026-11-17 22:00Z.

## V2 forward 2026-10-20

- **Run:** `20261020T060000Z-9cc75e` SUCCESS, 06:00:00–06:04:12Z.
- **Cutoffs:** filings ≤ 2026-10-19, prices ≤ 2026-10-19.
- **Stages:** 5/5 exit 0, 0 retries, stderr empty. Artifact validated, problems [].
- **Loop:** one logical loop; next slot 2026-10-21 06:00Z.

## Machine

No reboot (boot 2026-10-15 00:32:07Z). The checks ran on schedule overnight.
