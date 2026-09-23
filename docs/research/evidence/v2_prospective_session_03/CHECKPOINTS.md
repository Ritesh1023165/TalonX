# Session 03 checkpoints (2026-09-23)

These come from the checkpoint daemon (every 30 min, 27 checkpoints from 06:47Z to 19:47Z) plus the final EOD checkpoint (20:13Z). The market calendar is XNYS: open 13:30Z, close 20:00Z. There were 0 unplanned restarts: supervisor 8932, V2 companion 14592, checkpoint daemon 3632 and ingester 7272 were each the same PID from start to controlled stop.

| # | UTC | V2 health / tick | V2 hb age s | data | market / priced | intel log age s | code-P window / today | clusters (fresh / stale) | intents | cash | open | EXIT_UNRES | blocks | V2 outbox sent/pend/fail/amb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 startup | 06:47 | STARTING / 317 | 38522.7 | CURRENT | STALE / 51 | 38580 | 10 / 0 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |
| 2 morning warm-up | 07:17 | HEALTHY / 12 | 25.8 | CURRENT | HEALTHY / 51 | 4 | 10 / 0 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |
| 3 pre-open | 13:17 | HEALTHY / 156 | 22.5 | CURRENT | HEALTHY / 51 | 149 | 11 / 1 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |
| 4 shortly after open (13:30Z) | 13:47 | HEALTHY / 168 | 19.9 | CURRENT | HEALTHY / 51 | 85 | 11 / 1 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |
| 5 mid-morning | 15:17 | HEALTHY / 204 | 10.3 | CURRENT | HEALTHY / 51 | 6 | 11 / 1 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |
| 6 midday | 16:47 | HEALTHY / 240 | 1.4 | CURRENT | HEALTHY / 51 | 61 | 11 / 1 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |
| 7 mid-afternoon | 18:17 | HEALTHY / 276 | 25.3 | CURRENT | HEALTHY / 51 | 172 | 11 / 1 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |
| 8 late session | 19:47 | HEALTHY / 312 | 15.6 | CURRENT | HEALTHY / 51 | 185 | 11 / 1 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |
| 9 close / EOD final | 20:13 | HEALTHY / 322 | 0.0 | CURRENT | HEALTHY / 51 | 137 | 11 / 1 | 2 (1 / 1) | 0 | 100000.0 | 0 | 0 | 0 | 0/0/0/0 |

Notes:
- **Row 1 (startup, 06:47Z):** read before the new stack's first tick. The V2 heartbeat age, tick number, `STALE` market and Intelligence log age are left over from Session 02's stopped stack. By row 2 (07:17Z) everything was `HEALTHY` and current.
- **Provider:** SIP `alpaca:sip:1Day:adjustment=split`, fallback NONE. `pricing_unavailable_recent` = [] and witness disagreements = [] at EOD. Market feed coverage 1.0, 51 symbols priced, 0 provider failures/retries/rate limits (`/ping`). No CSV fallback.
- **Notifications (release outbox):** Signal (TRADE_EVENT) sent 0, failed 0, pending 0, ambiguous 0; no trade events were due. Sentinel: `STARTUP` SENT 06:47:27Z; `DEGRADED_HEALTH` (Intelligence `PROCESSING_OR_INPUT_DEGRADED`) SENT 12:55:43Z; `SHUTDOWN` PENDING at stop (known bounded issue). Session 02's SHUTDOWN is now `EXPIRED`, so the 2 h expiry worked as designed. Stale test-fixture alerts: 0.
- **Intelligence lane (separate from V2):** 2 `[INFO]` cards were SENT to Telegram: ADC 11:03:11Z (3 distinct insiders bought within 30 days, about $4.14M) and AFL 13:03:08Z (2 insiders sold). Delivery was enabled for the supervised Intelligence process by `--deliver --transport telegram` (Task 140), although the pre-start gate reported it OFF (see README findings).
- The legacy Original lane sent 0 official alerts. The Experimental lane sent 0 externally (104 held by the external boundary, as designed).
