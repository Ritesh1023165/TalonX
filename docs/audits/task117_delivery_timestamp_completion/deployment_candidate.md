# Deployment candidate

Branch `research/talonx-strategy-validation`. **Not** for `main`. No production
activation / DB mutation / external send / backlog expiry / timestamp rebuild in
this change set.

## Code that deploys

| file | change | risk | gate |
|---|---|---|---|
| `talonx_ingest/intelligence/edgar_normalize.py` | timestamp: **reverted** global Eastern reinterpretation; `parse_acceptance_datetime_ex(raw, *, source=...)` + `ACCEPTANCE_SOURCE_TZ` (`submissions`→UTC, `sgml_header`→Eastern) | low — the wired `submissions` path is back to genuine-UTC; explicit offsets respected; naive→UTC+flag | — |
| `talonx_ingest/intelligence/domain.py` | flags `ACCEPTANCE_OFFSET_ABSENT`, `ACCEPTANCE_TZ_SOURCE_SGML_EASTERN`, `ACCEPTANCE_DST_WALLCLOCK_ADJUSTED` (removed `ACCEPTANCE_TZ_ASSUMED_EASTERN`) | none (enum) | — |
| `talonx_ingest/intelligence/delivery/pipeline.py` | `process_pending(mode=…)` — `disabled` / `simulate` / `enabled`; no false SENT; `AMBIGUOUS` handling; `DrainResult` telemetry fields; `event_time_lookup` | medium — changes the drain contract; all callers updated | — |
| `talonx_ingest/intelligence/delivery/outbox.py` | `STATE_AMBIGUOUS` + `mark_ambiguous`; `expire_stale(event_time_lookup=…)` (older-of event/enqueue) | low — additive | — |
| `talonx_ingest/intelligence/delivery/config.py` | `CARD_MAX_AGE_SECONDS` (unchanged from prior task) | none | — |
| `talonx_ingest/intelligence/service/config.py` | `deliver_intelligence_cards` (**False**), `deliver_cards_per_cycle` (20), `deliver_cards_enforce_age_cutoff` (True), `deliver_cards_timeout_seconds` (20) | low | `TALONX_INTEL_DELIVER_CARDS` |
| `talonx_ingest/intelligence/service/runner.py` | `deliver_cycle` wired once per `run_poll_loop` cycle; `_InertSender` for disabled mode | **medium** — a new step in the supervised loop, but disabled-by-default and time-boxed | `deliver_intelligence_cards` |
| `talonx_ops/prospective/proc.py` | `ConcurrentStartError`, `_live_prior_stack`, `assert_no_live_prior_stack`, `startup_verdict`; `start_stack(allow_when_running=…)` refuses a 2nd stack | low | `--force` overrides |
| `talonx_ops/prospective/__main__.py` | `cmd_start` uses `startup_verdict` + concurrent guard + ownership-safe cleanup on `FAILED_WITH_RESIDUALS`; verdict-driven exit code (0/2/3/4) | low | — |
| `talonx_ops/prospective/lane_accounting.py` | **new** — lane-scoped EOD accounting snapshot (read-only) | low | — |
| `talonx_ops/prospective/close.py` | writes `lane_accounting_eod.json` during `close` | low (additive) | — |
| `talonx_v2/form4_source.py` | **reverted** to the pre-task `t.accepted_at_utc.date()` | none | — |

New tests: `test_task117_acceptance_timezone.py` (rewritten, 25),
`test_task117_delivery_runner_integration.py` (7),
`test_task117_startup_verdict.py` (11), `test_task117_lane_accounting.py` (5).
Updated: `test_delivery_pipeline.py`, `test_task117_intel_delivery_age_cutoff.py`
(`_drain` → `mode="enabled"`), `test_intelligence_edgar_normalize.py` /
`test_intelligence_pipeline.py` (reverted to UTC fixtures).

## Production activation steps — NOT executed

### A. Enable intelligence-card delivery

1. On a **copy** of `~/.talonx/ingestion_ledger.db`, run
   `DeliveryOutbox(copy).expire_stale(event_time_lookup=<text_events lookup>)`
   at the real activation cutoff → confirm the disposition split (at
   2026-09-11T13:30Z it was 9,841 EXPIRED / 2 PENDING; recompute for the actual
   cutoff). Eyeball the 23 CRITICAL rows
   (`results/task117_output_closure_evidence/critical_backlog_review.csv`).
2. `export TALONX_INTEL_DELIVER_AGE_CUTOFF=1` (default), `TALONX_INTEL_DELIVER_PER_CYCLE=20`.
3. Start the service with delivery still **disabled**
   (`TALONX_INTEL_DELIVER_CARDS` unset). Verify one full session: `deliver_cycle`
   logs `mode=disabled`, `held` counts climb, **nothing sent**.
4. In a separate change, set `TALONX_INTEL_DELIVER_CARDS=1` **and** run the
   service with `--send` (`dry_run_delivery=False`). First verify against an
   intercepted transport (a `RecordingSender` shim) before the real token.
5. First real drain: confirm the age cutoff expires the backlog (state
   transitions + `EXPIRED` log lines, **no `SENT` on old rows**), then only
   fresh cards send, ≤ 20/cycle.

### B. Timestamp rebuild — BLOCKED, do not run

`insiderstore_before_after.md`: **0 VERIFIED_CORRECTION** → there is nothing to
rebuild. The ~4 h persisted-vs-retrieved anomaly is `UNRESOLVED` (contradictory
raw evidence). A rebuild is only justified if a live-EDGAR cross-check of the
S1–S3 accessions shows the persisted values are wrong. If so, the rebuild (on a
copy) is: for each row whose source field is `submissions.acceptanceDateTime`
and whose value disagrees with a re-fetched submissions value, replace with the
re-fetched value + append `acceptance_value_corrected`; recompute
`session_bucket`; re-run significance for changed buckets; diff the Task-116
replay on a copy of `v2_lane.db`. Idempotent (re-run = no-op), reversible
(originals in the manifest).

## Pre-deploy checks

- V2 fp `11107198c5b81237` (none of the 5 hashed files touched — verified).
- `pytest tests/` green (see `remaining_gaps.md` §"Test status").
- `git diff --stat` = only the files above + this bundle.
- `~/.talonx/ingestion_ledger.db` md5 `2ae2105c6f51a4af4b3b80dc06e5f30f`,
  `v2_lane.db` `29e57dbcd1a567fbc4bb0e73efdba95f`, Redis `PING → PONG` (run_id
  retained).
