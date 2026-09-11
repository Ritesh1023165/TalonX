# Backlog rehearsal — `intelligence_delivery` outbox (Task 117 §2)

**No production mutation.** Rehearsed on isolated `shutil.copy2` copies of the
S3 `.postclose` snapshot. Prior full analysis:
`docs/audits/task117_delivery_timestamp_completion/backlog_rehearsal.md`
(Task E) — this doc restates the composition and re-verifies at the activation
windows relevant to *tomorrow*.

## Composition (isolated copy, 9,843 rows, 100 % PENDING originally, 0 ever SENT)

| dimension | breakdown |
|---|---|
| origin | 9,779 from the one-time 2026-09-04 `--with-backfill` bulk · S1 6 · S2 35 · S3 23 |
| band | CRITICAL 23 · HIGH 5,837 · MEDIUM 3,216 · LOW 767 |
| route | IMMEDIATE 5,860 · DIGEST 3,983 |
| all 23 CRITICAL | enqueued 2026-09-04; ≥ 7 days old at any plausible activation |

## Freshness policy (trustworthy timestamps)

`expire_stale(now, max_age_seconds, event_time_lookup)` measures age from the
**older of (public event acceptance time via `text_events.accepted_at_utc`,
enqueue time)**. So *an old filing newly enqueued today is NOT fresh* — its
event time dominates. `CARD_MAX_AGE_SECONDS = {IMMEDIATE: 6 h, DIGEST: 24 h}`.
`EXPIRED` is terminal, writes an audit line, and **no row is deleted and no
EXPIRED row is ever marked SENT**. Rows whose freshness cannot be established
(no usable event time and no enqueue time) are held, not sent.

## Dispositions recomputed at concrete cutoffs

| activation cutoff (UTC) | EXPIRED | still PENDING (genuinely fresh) |
|---|---:|---:|
| 2026-09-11 T13:30 | 9,841 | **2** — the ORCL & JPM DIGEST cards from 2026-09-10 (event 16:16 / 16:27 Z, ~21 h old, inside the 24 h DIGEST window) |
| 2026-09-12 T13:30 (realistic "tomorrow" activation) | **9,843** | **0** |

Numbers are **computed at the cutoff**, not assumed. Re-run tonight
(`outbox.expire_stale` on the isolated copy) confirms: at a 2026-09-12 cutoff
the 2 survivors also expire → 9,843 EXPIRED, 0 PENDING, 0 deleted, 0 SENT.

## CRITICAL subset — reviewed, not sent

All 23 CRITICAL rows are from the 2026-09-04 bulk (event types:
INSIDER_TRANSACTION, QUARTERLY_FILING, REGULATION_FD, MATERIAL_AGREEMENT,
DEBT_FINANCING, ACQUISITION_DISPOSITION, AGREEMENT_TERMINATED, RESTRUCTURING ×1,
DELISTING_NOTICE ×1). Every one is ≥ 7 days old at any plausible activation and
expires by event-time. They were enumerated and read from the isolated copy;
**none were sent**.

## First enabled cycle cannot flood Telegram

- IMMEDIATE: `process_pending` runs `expire_stale` **first** (when
  `enforce_age_cutoff` / `TALONX_INTEL_DELIVER_AGE_CUTOFF`), so a first enabled
  cycle sees ~0–2 eligible rows, not thousands; it is further bounded by
  `deliver_cards_per_cycle` (default 20).
- DIGEST: `process_digest` aggregates *all* eligible DIGEST rows into **one**
  message per 6 h bucket (`_digest_text_from_rows`, `MAX_DIGEST_ROWS` cap), and
  the `last_digest_bucket` meta key makes a restart in the same window a no-op.
- So the worst case for a first enabled cycle after this backlog is: **0–2
  IMMEDIATE sends + at most 1 digest message.**

## Production backlog procedure (prepared, NOT executed)

1. Stop nothing; the live poll loop stays in `disabled` mode.
2. On a **copy** of `~/.talonx/ingestion_ledger.db`, run
   `python -c "from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox;
   ob=DeliveryOutbox('<copy>'); print(len(ob.expire_stale(now=<activation instant>,
   max_age_seconds=None, event_time_lookup=<text_events join>)))"` to see the
   exact EXPIRED/PENDING split at the real activation instant.
3. If acceptable, apply the same `expire_stale` **once** to the live DB while
   the loop is in `disabled` mode (auditable: EXPIRED rows keep their content
   and get a log line).
4. Then flip `deliver_intelligence_cards=1` + `dry_run_delivery=False`; the
   first enabled cycle now has only genuinely-fresh rows to consider.

## Cross-route overlap with Original long-term alerts

Intelligence cards and Original's `long_term_alerts` are separate routes with
separate outboxes. `enqueue_card` de-dups by `delivery_id` (content-addressed on
`alert_id` + render version) and `classify_update` suppresses unchanged
repetition (`DECISION_SUPPRESS`), while a **materially changed** card enqueues
as `UPDATE` with explicit provenance (`disposition='UPDATE'`, reason recorded).
No Intelligence card is routed through Original's dispatch and vice-versa
(`external_boundary.py` OFFICIAL family separation, Task 110).
