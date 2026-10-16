# Read-only checkpoint after the network interruption: 2026-10-16 10:50Z (11:50 BST)

**`HEALTHY_AFTER_NETWORK_RECOVERY`.** Every service has completed real work since the interruption. No restart,
retry, backfill or send was made by this checkpoint. HEAD = origin = `1013bc1` before this commit.

## What the interruption actually was

It was **not only an internet drop.** The laptop lid was closed, so the machine **slept** (Modern Standby).

| UTC | Event (Windows System / WLAN / NetworkProfile logs) |
|---|---|
| 08:16:46Z | Kernel-Power 506: "entering Modern Standby, Reason: Lid" |
| 08:16:34Z / 08:13:52Z | Last Opportunity ingestion cycle / last Intelligence poll before sleep |
| 10:03:45Z | Wi-Fi disconnected (WLAN 8003, NetworkProfile 10001), while asleep |
| 10:33:15Z | Kernel-Power 507: "exiting Modern Standby, Reason: Lid" |
| 10:33:15–10:34:12Z | DNS failures (`getaddrinfo failed`, Errno 11001) and Telegram timeouts. Wi-Fi reconnect failed once at 10:33:23Z, succeeded at 10:34:06Z; network connected 10:34:12Z |

- **Interval:** processing stopped 08:16:46Z–10:33:15Z (2h16m). Network unavailable for the first ~1 min after wake.
- **Error types:** DNS resolution failures and connect/read timeouts only. No TLS, provider-side (HTTP 4xx/5xx) or
  rate-limit errors were recorded.
- **Not a reboot:** boot time is unchanged (2026-10-15 00:32:07Z), and every process kept its owner.

## Components

| Component | Last successful work | Issue / backlog | Recovery evidence |
|---|---|---|---|
| Ingestion | Cycle 12790 10:49:26Z, 603 symbols, data as_of 10:34Z, 0 failures | Probe failed 10:33:15Z (DNS, 51 s before Wi-Fi returned). The 900 s re-probe interval kept PREMARKET UNAVAILABLE until 10:48:16Z | Probe ok 10:48:16Z; cycle 12789 refilled premarket bars 08:01→10:33Z (7,715 bars) |
| Discovery | SCANNED 10:49:19Z: 603 eligible, 396 data-ready, admissible 600 | None now. PROVIDER_STALE / DATA_UNAVAILABLE 10:33–10:39Z | Scan on current data |
| Universe | Published 10-16: DTU_V3_TOP600 `2849da55…`, Core 600, event-eligible 0 | — | Ingestion and discovery: 603 fetched (564 Core + 39 operator-added), admissible 600, same fingerprint |
| Evaluators ×4, notifier, promotion | Cursor 51761 = latest event | No new events while data was unavailable | Heartbeats ≤ 5 s, 0 failures |
| Outcomes, reporting | Reporting generated 10:33:15Z | OUTCOME_PENDING 692 (normal tracking) | 0 failures |
| Sentinel | Polls advancing (2231), no last error | TICK_ERROR 10:33:39Z (ReadError), 10:33:59Z (DNS) | No error since |
| Intelligence | Cycles 10–11 (10:37:30Z, 10:40:46Z): 39/39 issuers, FRESH, 0 errors | Cycle 9 (10:33:34Z) 1 symbol failed | Clean cycles since |
| V2 companion | Tick 16, last tick 10:43:17Z, CURRENT, `last_error` null | Ticks suspended during sleep | 0 positions, 0 pending intents |
| Redis, :8787 | PONG; HTTP 200 | — | Local checks |
| Ownership | One logical owner for each of 20 processes; boot unchanged | — | Process table |

## Telegram delivery

- **Confirmed sends after the interruption (natural):**
  - Lab `OPPORTUNITY_RESEARCH_DIGEST`: created 10:33:16Z, **3 attempts**, SENT 10:34:15Z. In-process retries failed
    on DNS; the outbox retry then delivered.
  - Intelligence `DEGRADED_HEALTH` ops alert (for cycle 9's error): SENT 10:35:46Z.
- **Outbox state:** no PENDING, IN_FLIGHT, AMBIGUOUS or new FAILED/EXPIRED rows in any ops outbox. Duplicate internal
  dedup keys: 0 in every outbox. Internal deduplication does not prove Telegram delivered exactly once.
- **Intelligence:** 2 DIGEST rows PENDING since 07:50:58Z (normal digest hold, 14 HELD events). The 3 historical
  AMBIGUOUS rows are unchanged.
- **Review alerts (Signal bot): `NOT_YET_OBSERVED`.** No promotion has been due since the interruption; the regular
  session opens 13:30Z. The last traced sends are 2026-10-15, 15/15 API_ACCEPTED.

## Trackers and schedules

- **Forward:** 2026-10-16 `20261016T060000Z-2f704a` SUCCESS is intact (5/5 stages exit 0, artifact validated,
  problems []). 2026-10-15 is still MISSED, with no record.
  - One loop; next slot **2026-10-17 06:00Z**.
  - The sleeper re-reads the wall clock every ≤ 300 s, so standby delays a slot by at most ~5 min after wake but
    cannot skip it.
- **VR:** heartbeat 10:49:15Z, window 10-16, both arms BLOCKED, 0 OPEN, 0 trades after the boundary, 0 tick errors.
  The endpoint is unchanged: last collection about 20:21Z, exit about 2026-10-17 00:00Z, closeout not before 00:05Z.
- **PDM:** `verify_integrity` OK. 1 task with 00:15 / 06:30 London triggers. Next run 2026-10-19 23:15Z, never run,
  no store. Interactive user signed in, on AC.
- **DTU collector / ERM:** no processes; ERM tasks have no next run.

## Gaps (recorded, not interpreted)

- **No live processing 08:16–10:48Z** (premarket):
  - Opportunity premarket detection: ingestion data was refilled at 10:48Z, but detection was not live.
  - Intelligence polls: 2h20m gap.
  - V2 ticks and VR ticks: no positions or entries were affected.
- **No sends possible 08:16–10:34Z.** No outbox row is stranded.
- **Insufficient evidence:**
  - Sentinel's runtime detail does not expose the membership it served. It reads the published snapshot
    `2026-10-16@2026-10-15#2849da5594f272db`.
  - Whether any filing or premarket move during the gap would have produced a timely alert.

## Risk and smallest actions

1. **Lid close puts the machine to sleep.** On AC it suspends every TalonX loop, and the network can drop while
   asleep. Before tonight's VR endpoint (20:21Z collection), the 06:00Z forward slot and PDM (10-19 23:15Z), keep the
   lid open or have the owner set the AC lid action to "Do nothing". That is a power-setting change, not made here.
2. **Ingestion re-probes a failed phase only every 900 s.** After a wake, ingestion can sit up to 15 min in
   UNAVAILABLE after the network is back. It self-healed here, so no action is needed now. A shorter retry after a
   failed probe would be a code change for a separate task.
