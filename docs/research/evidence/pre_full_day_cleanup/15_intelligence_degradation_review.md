# Intelligence degradation (TASK N) - recovered; bounded follow-up
- Start: Intelligence processing log was **510,901 s (~5.9 days) old** at the first checkpoint 18:42:37Z, newest insider event 2026-09-15T16:23Z; market feed STALE (pre-start).
- Sentinel `DEGRADED_HEALTH intelligence: PROCESSING_OR_INPUT_DEGRADED` created 18:45:14Z, sent 18:47:35Z.
- Recovery: by the 19:12:40Z checkpoint the processing log was 26 s old and the newest insider event 2026-09-21T08:59Z (the supervisor-started Intelligence service caught up within ~30 min); healthy at 19:42Z and 20:05Z.
- Approved Intelligence deliveries missed: none (Intelligence card delivery is OFF in the release). V2 trade lane: not affected in the canary (cold start, no trade), BUT the insider store was ~6 days behind at 18:42Z - the checkpoint's early "ADC single near-miss" then "cluster" was
  this catch-up (ADC's second-owner filing dated 2026-09-17 became visible), not a checkpoint bug.
- **Operational rule for the full-day run:** start the stack early enough (>= 45 min before pre-open) and confirm `intelligence` processing-log age is small and `newest_insider_event` is current BEFORE the open, so pre-open intent creation sees fresh Form 4 data. Not a blocker.
