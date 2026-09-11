# Backlog rehearsal — the 9,843-row `intelligence_delivery` outbox

Rehearsed on a **consistent isolated copy**
(`results/task117_delivery_timestamp_completion_evidence/ingestion_ledger.rehearsal.db`,
a `shutil.copy2` of the S3 `.postclose` snapshot). **Production was not touched.**
Evidence JSON: `results/task117_delivery_timestamp_completion_evidence/backlog_rehearsal.json`.

## Composition (unchanged from the prior audit, restated)

| bucket | rows |
|---|---|
| enqueued **2026-09-04** (one-time `--with-backfill` bulk) | 9,779 |
| S1 2026-09-08 live | 6 |
| S2 2026-09-09 live | 35 |
| S3 2026-09-10 live | 23 |
| **total** | **9,843**, 100 % `PENDING`, 0 ever `SENT` |
| by band | HIGH 5,837 · MEDIUM 3,216 · LOW 767 · CRITICAL 23 (all in the 09-04 bulk) |

## Actual dispositions at a concrete rehearsal cutoff

Freshness is measured from the **older of (public event time, enqueue time)** —
`expire_stale(event_time_lookup=…)` joins `text_events.accepted_at_utc`. So *"an
old filing enqueued today"* does not count as fresh, and the `EXPIRED` reason
records which basis triggered it.

**Cutoff = 2026-09-11T13:30:00Z** (a plausible next-session start):

| | count |
|---|---:|
| PENDING before | 9,843 |
| → EXPIRED (older than the 6 h IMMEDIATE / 24 h DIGEST cutoff by event-or-enqueue time) | **9,841** |
| → still PENDING (genuinely fresh at this cutoff) | **2** |

The 2 survivors are the **ORCL** and **JPM** DIGEST cards from 2026-09-10
(event time 16:16 / 16:27 UTC → ~21 h old at the cutoff, inside the 24 h DIGEST
window). **This is the point of the exercise: not all 9,843 rows are stale at
every possible activation time** — the number of survivors depends on the cutoff
and is computed, not assumed. If activation happened later (say 2026-09-12) all
9,843 would expire.

(For this particular backlog, event-time and enqueue-time give the same expiry
count — 9,841 — because every row's event time ≤ its enqueue time. The
event-time basis still matters for the general case and is what the code uses.)

## CRITICAL rows

All 23 CRITICAL rows were enqueued 2026-09-04 (the bulk). Event types:
INSIDER_TRANSACTION, QUARTERLY_FILING, REGULATION_FD, MATERIAL_AGREEMENT,
DEBT_FINANCING, ACQUISITION_DISPOSITION, AGREEMENT_TERMINATED, RESTRUCTURING (×1),
DELISTING_NOTICE (×1). Every one is ≥ 7 days old at any plausible activation →
all → EXPIRED. A CRITICAL label does not make a week-old alert timely; the
underlying facts, if still relevant, resurface on the next filing. The full list
(`delivery_id`, `event_id`, `symbol`, `enqueued_at_utc`) is at
`results/task117_output_closure_evidence/critical_backlog_review.csv` for a human
to eyeball before any activation.

## Audit preservation — verified

- `expire_stale` is a **state transition + `EXPIRED` log line + `suppress_reason`**,
  never a `DELETE`.
- **No old row is marked `SENT`.**
- Idempotent (`test_expire_stale_is_idempotent_and_never_touches_terminal_rows`).
- Disabled-mode drains do **not** call `expire_stale` (backlog expiry is a
  separate, explicit operation — `enforce_age_cutoff` must be passed on purpose).

## Does disabled mode permit expiry?

**No — not implicitly.** `deliver_cycle` in `mode="disabled"` calls
`process_pending` **without** `enforce_age_cutoff`, so it holds rows PENDING and
mutates nothing. Expiry only happens on the **enabled** path
(`deliver_cards_enforce_age_cutoff=True`, default) or when a rehearsal / an
explicit activation step calls `outbox.expire_stale()` directly. Preparing this
behaviour does **not** authorize a production expiry now; the production step is
in `deployment_candidate.md`.
