# Intelligence `POLL_ERRORS` alerts: diagnosis and fix (2026-10-07)

**Symptom:** repeated Operations messages:

> "OPERATIONS: intelligence: PROCESSING_OR_INPUT_DEGRADED. Causes: POLL_ERRORS. Inspect dashboard and local evidence."

**Classification:** a deterministic content rejection was counted as a poll error on every cycle, and the alert
policy emits one incident per clock hour.

| Ruled out | Evidence |
|---|---|
| Provider / network failure | No symbol failures in the episode |
| Stale input | Freshness FRESH throughout |
| Duplicate delivery | One logical event per hour, delivered once |

**Change classification:** Intelligence ops observability (health accounting). This is a post-freeze runtime change
confined to files already on the V2 release-freeze allowlists:

- `talonx_ingest/intelligence/service/poller.py`: `FREEZE_RELEASE_FIDELITY_FIX_FILES`;
- `talonx_ingest/intelligence/service/runner.py` and `poll_history.py`: `FREEZE_SESSION03_HARDENING_FILES`.

It touches no strategy-fingerprint file, no provider/pricing/accounting/ledger file and no V2 admission input: the
insider store contents are unchanged, because mismatched filings were never persisted before or after.

## Evidence (read-only, existing telemetry)

**Process ownership.** There is a single Intelligence service: `talonx_ingest.intelligence.service poll
--with-backfill` (venv shim 6812 plus the real interpreter 11776). It is a child of `talonx_ops.supervisor run`
(5316) and has run since 2026-10-04 23:12 BST. No other producer of `health:intelligence:*` exists.

**Poll history** (`~/.talonx/intelligence/poll_history.jsonl`, counts and cause codes only):

- The last clean cycle was **2026-10-05T20:20:21Z**. From **2026-10-05T20:23:36Z** (21:23 BST), **every** cycle
  (637 consecutive cycles to 2026-10-07T08:17Z, about 3.3 min apart, 17–19 per hour) has `error_count = 1`,
  `health_causes = ["POLL_ERRORS"]`, `freshness = FRESH` and `symbols_polled = 39`.
- One cycle in the run also had a symbol failure. The recovery pass and delivery were healthy.

**The error** (heartbeat `last_cycle.errors`, 2026-10-07T08:20:33Z):

> "BAC form4 0000070858-26-000473: ISSUER_CIK_MISMATCH: filing declares 0001083839, expected 0000070858 for BAC"

The accession is listed in BAC's own submissions; its prefix is BAC's CIK, so BAC filed it. The ownership XML
declares a different issuer, CIK 0001083839. This is BAC acting as filer or reporting owner for another company.

**Why it repeated:**

- The Task 131 identity guard correctly drops the filing: it is never persisted.
- Because nothing is persisted, `has_event()` stays false, so the next cycle re-reads the cached XML and drops it
  again.
- `poller.py` appended every non-ok ownership outcome, including this verified drop, to `result.errors`.
- `runner.py` feeds `len(res.errors)` into `intelligence_health_causes` → `POLL_ERRORS` on every cycle.
- The cached XML (`form_ownership_xml_cache`) means there is no repeated network fetch: this is accounting only.

**Outbox** (`v2_release_rc1_notifications.db`, `ops_notification_outbox`, read-only):

- **37** `DEGRADED_HEALTH` rows, dedup keys `health:intelligence:PROCESSING_OR_INPUT_DEGRADED:<YYYY-MM-DDTHH>`, one per
  hour from **2026-10-05T20** to **2026-10-07T08**.
- All are SENT: first 2026-10-05T20:25:28Z, last 2026-10-07T08:02:53Z. There were 38 attempts in total; only the
  2026-10-05T21 event took 2 attempts, a retry of the same logical event.
- **Each message is a new hourly event for one unchanging condition**, not a duplicate delivery. The six messages
  noticed by the owner are part of this series (seven were sent from 03:00 BST on 2026-10-07).

## Fix

In `talonx_ingest/intelligence/service/poller.py`, an ownership outcome is now classed as an other-issuer drop only
when **both** of these hold:

- `identity_check == "DROPPED_MISMATCH"`;
- the reason starts with `ISSUER_CIK_MISMATCH`, meaning a parseable declared issuer CIK that differs from the watched
  CIK.

Such an outcome is counted in `PollCycleResult.identity_drops`. It is not appended to `errors` and does not mark the
ownership source as failed.

The count is exposed as `identity_drops` in the cycle summary, the heartbeat and `poll_history.jsonl`. It is logged
by the guard as a warning on every cycle, as before.

**Unchanged:**

- Submissions fetch failures, ownership XML fetch/index failures, filings without a parseable issuer CIK
  (`DROPPED_NO_CIK`), a missing authoritative CIK, and parse/ingest failures all remain counted errors and still
  raise `POLL_ERRORS`.
- `SOURCE_STALE` / `SOURCE_DOWN` and the other causes are unchanged.
- The hourly incident policy and the alert text are unchanged.
- Nothing is persisted differently.

**No new thresholds.**

## Tests

`tests/test_intel_identity_drop_health.py` has 8 tests:

1. other-issuer drop → telemetry, no causes, still not persisted;
2. persistent re-seen drop over 4 cycles → never `POLL_ERRORS`;
3. no-issuer-CIK filing still an error;
4. ownership XML fetch failure still an error;
5. submissions outage still `POLL_SYMBOL_FAILURES` and `POLL_ERRORS`;
6. matching issuer unchanged;
7. STALE / DOWN still alert with zero errors;
8. poll history records `identity_drops`.

Seven of the eight fail on the unfixed code; the stale/down test passes either way. The affected regression suites
(poller, identity guard, runner, Session 03 health hardening, delivery, task 133/136b, V2 freeze/preflight):
**341 passed, 3 failed**. All 3 failures are pre-existing and also fail on unmodified `0b2967d`: one Windows
subprocess environment error in `test_ri3_operator`, and two date-scenario tests in
`test_v2_sec_filing_date_admission`.

## Remaining limitations (not changed here)

- The incident policy still emits one identical `DEGRADED_HEALTH` per clock hour for any **genuine** persistent
  condition. There is no incident or reminder hysteresis, no recovery message, and no failed/total scope or duration
  in the text. That is a separate, larger alert-policy change.
- Other benign per-cycle entries still count as errors if they occur, for example the planned
  "form4 per-cycle budget exhausted — deferred to next cycle". It was not observed in this episode.
- The dropped accession is still re-read from cache and re-logged (WARNING) every cycle. This is cheap, with no
  network, but noisy in the log.

## Rollback

```
git revert <fix-commit>
```

Then let the supervisor restart only the Intelligence child: terminate its process and the supervisor relaunches it
(OPTIONAL component, unbounded restart, 15 s backoff). Rollback restores hourly `POLL_ERRORS` alerts while that BAC
filing remains in the submissions window.
