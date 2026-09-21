# Notification isolation contract (TASK C)

**TEST NOTIFICATIONS CAN REACH REAL SENTINEL: NO - RELEASE OUTBOX ISOLATED: YES.** Chosen direction **A (release-specific outbox), enforced by the gate, plus test isolation** - impossible by construction, not by manual deletion:

1. **The release owns its outbox:** `TALONX_NOTIFY_DB_PATH=v2_release_rc1_notifications.db` is part of the release environment (`python -m talonx_v2.release_gate --print-env`). Every consumer already honours it
   (`close._default_ops_notify_store`, `producers`, `run.py` companion drain, `operator_read`), and children inherit it from the launch shell. The shared `notifications.db` is never opened by a release session.
2. **Gate check `release_notification_store`** (FAIL -> `--release` refuses to start): the variable must be set, must not be the shared `notifications.db`, must be the release filename, and - if the release outbox exists - it must hold
   no PENDING/RETRY rows whose provenance campaign is not `V2-PAPER-RC1` (campaign-agnostic rows such as intelligence health are allowed).
3. **Tests cannot write it:** `tests/conftest.py` autouse fixture (a) points `TALONX_NOTIFY_DB_PATH` at a per-test temp file and (b) makes constructing a `NotifyStore` on the repo-root `notifications.db` or `v2_release_rc1_notifications.db` raise,
   even if a test scrubs the env var. Mutation-verified: removing the fixture fails the regression test.
4. **Time-bound lifecycle notices:** STARTUP/SHUTDOWN carry `deliver_by` (+2 h) so a stale one EXPIRES instead of being sent late/out of order.
No notification architecture was redesigned; routing (Signal=TRADE_EVENT, Sentinel=OPERATIONS, Lab=RESEARCH OFF) is unchanged.
