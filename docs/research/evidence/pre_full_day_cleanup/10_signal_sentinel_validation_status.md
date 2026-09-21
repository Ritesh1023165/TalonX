# Signal / Sentinel validation after rotation (TASK I)
- **SIGNAL: READY** - dedicated credentials, never exposed, previous physical validation still matches the active configuration (`signal_delivery_validation_bound` PASS).
- **SENTINEL: NOT_READY** now (its bot token is compromised - `compromised_credentials_rotated` FAIL). After rotation its one-way pair fingerprint changes, so the prior validation no longer applies: **NEEDS_REVALIDATION** (gate
  `sentinel_delivery_validation_bound` FAIL) until step 5 of `09_credential_rotation_status.md`. Not claimed valid; no message sent in this task.
- **LAB: OFF** (gate `lab_off` PASS; no fallback).
- New tested command `talonx_ops.notify.validate` (dry-run by default; refuses Lab; refuses a still-compromised token; never writes a secret; record accepted by the gate; a rotated credential invalidates it again - tests 22-24).
