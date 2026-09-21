# Corrected backlog rehearsal (Task 117 final-activation A5)

## What was wrong

The prior runbook's rehearsal command passed `event_time_lookup=None` to
`expire_stale` "to simplify the runbook." That silently drops the public
event-acceptance-time basis and falls back to enqueue-time only — **not**
the same policy the live runtime uses (`runner.py::deliver_cycle`'s
`_event_time` closure, which joins `text_events.accepted_at_utc`). The task
explicitly calls this out: *"Do not pass event_time_lookup=None merely to
simplify the runbook. Unknown freshness must not silently become fresh."*

## Corrected method

- Fresh isolated copy of the **live** `ingestion_ledger.db` (never the
  production file itself).
- A real `event_time_lookup` matching the runtime's own policy: `event_id →
  text_events.accepted_at_utc`, parsed the same way, `None` only when the
  join genuinely has no timestamp (which correctly leaves enqueue-time as
  the sole basis for that row — "unknown becomes fresh" is avoided because
  `expire_stale` already takes the basis as `min(enqueue, event)` over
  whichever candidates exist; a row with truly no event time is judged on
  enqueue time alone, not treated as automatically fresh).
- Run at the **actual rehearsal timestamp** (real wall-clock UTC at
  execution time), not a placeholder date.
- (Implementation note: the 9,843-row rehearsal prefetches
  `text_events(event_id, accepted_at_utc)` into an in-memory dict once,
  rather than one SQL round-trip per row, purely for rehearsal speed — the
  live runtime path already only ever processes ≤`deliver_cards_per_cycle`
  rows per cycle, so this optimisation is rehearsal-only and changes no
  runtime behaviour.)

## Result — actual rehearsal timestamp `2026-09-11T07:17:03Z`

| | count |
|---|---:|
| PENDING before | 9,843 |
| → EXPIRED (event-time-or-enqueue-time basis, correctly applied) | **9,840** |
| → still PENDING (genuinely fresh) | **3** |

Composition before: CRITICAL 23 · HIGH 5,837 · MEDIUM 3,216 · LOW 767.

The 3 survivors (all `MEDIUM`/DIGEST, correct — none of the 23 CRITICAL rows
survive at this timestamp):

| symbol | enqueued | age at rehearsal instant |
|---|---|---|
| AFL | 2026-09-10T13:18:12Z | ~18.0 h — inside the 24 h DIGEST window |
| ORCL | 2026-09-10T20:24:11Z | ~11.0 h |
| JPM | 2026-09-10T20:30:53Z | ~10.8 h |

Sample of an EXPIRED disposition (representative, all AMD DIGEST rows from
the 2026-09-04 bulk enqueue, ~7 days old — well past both the 6 h IMMEDIATE
and 24 h DIGEST cutoffs):
```
telegram:card:SEC:0000002488-24-000040:INSIDER_TRANSACTION:telegram-intel-v1
  symbol=AMD route=DIGEST band=MEDIUM enqueued=2026-09-04T11:17:38Z -> EXPIRED
```

This is a *different* count from the earlier (uncorrected) rehearsal's 2
survivors — the point of using the real policy: the actual basis for each
row (event time vs. enqueue time) determines the outcome, and it is
**computed, not assumed**. Note also that the earlier rehearsal was run at a
different (slightly earlier) wall-clock instant, so the two counts are not
directly comparable in isolation, which is exactly why the runbook must use
the real policy and the actual timestamp rather than a stand-in.

## Production state

**Production `ingestion_ledger.db` was never opened for this rehearsal in a
way that could mutate it** — only an isolated copy, made and destroyed within
this session, was touched. Production `expire_stale` remains **unexecuted**.
The isolated copy was deleted immediately after capturing this result; no
database was committed or left on disk.

## What the runbook now says

`docs/audits/task117_overnight_release_closure/deployment_candidate.md` §3a
already showed the correct pattern (join `text_events` for the lookup) in
concept; this correction makes explicit that `event_time_lookup=None` must
never be used for the actual production check, and that the check must be
re-run at the real activation instant (not reused from this rehearsal, since
time will have moved on).
