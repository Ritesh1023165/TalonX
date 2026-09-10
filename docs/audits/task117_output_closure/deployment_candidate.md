# Deployment candidate — Task 117 output closure

Branch `research/talonx-strategy-validation`. **Not** for `main`. No production activation, no
DB migration, no external sends in this change set itself.

## What deploys (code)

| file | change | risk | activation-gated? |
|---|---|---|---|
| `talonx_ingest/intelligence/edgar_normalize.py` | `parse_acceptance_datetime[_ex]` → EDGAR-Eastern for bare `Z`/`+00:00`/naive; explicit offsets trusted; `acceptance_tz_assumed_eastern` flag | **medium** — changes persisted `accepted_at_utc` / `session_bucket` for *new* ingests | switch `EDGAR_ACCEPTANCE_ASSUMES_EASTERN=True` (default). Set `False` to reproduce pre-fix. |
| `talonx_ingest/intelligence/domain.py` | `+ ACCEPTANCE_TZ_ASSUMED_EASTERN` flag | none (additive enum member) | no |
| `talonx_v2/form4_source.py` | `from_insider_store` missing-`filing_date` fallback keys on the acceptance instant's **ET date** | low — only affects rows with a NULL `filing_date`; not in the fingerprint hash | no |
| `talonx_ops/prospective/funnel.py` | `build_funnel(execution_allowlist="auto")` — scope the near-miss/cluster funnel to the enforced 39 | low — observational read model only | `"auto"` default; `None` restores old behaviour |
| `talonx_ops/supervisor.py` | `count_telegram_get_updates_owners()` — dedup shim+worker, token match | low | no |
| `talonx_ops/dashboard_read.py` | `_v2_eod_state(now=…)` + `_v2_position_lifecycle(now=…)` — current-session only | low | no |
| `talonx_dispatch/consumer.py` | earnings heads-up also writes `last_telegram_push` | low (one extra cache row) | no |
| `talonx_ingest/intelligence/delivery/{config,outbox,pipeline}.py` | `CARD_MAX_AGE_SECONDS`, `STATE_EXPIRED`, `DeliveryOutbox.expire_stale()`, `process_pending(enforce_age_cutoff=…)` | low — `enforce_age_cutoff` defaults **False**; no current caller passes it | the drain wiring itself is **not** added; see below |

Tests added: `test_task117_acceptance_timezone.py` (26), `test_task117_intel_delivery_age_cutoff.py`
(5), `test_task117_telegram_owner_dedup.py` (4); fixtures updated in `test_intelligence_edgar_normalize.py`,
`test_intelligence_pipeline.py`, `test_task117_migration.py`, `test_task117_deployment_rehearsal.py`.

## What does NOT deploy (documented, needs its own change + validation)

1. **Historical `ingestion_ledger.db` tz-rebuild** — `timestamp_findings.md` §"Migration proposal"
   (6 steps, on a copy). Requires a live-EDGAR spot check that is not possible here.
2. **Intelligence delivery drain wired into `runner.run_poll_loop`** —
   `intelligence_delivery_closure.md` §"Non-executed production activation steps" (7 steps).
   Gated behind `deliver_intelligence_cards=False`.
3. **D4** (startup-verdict) and **D6** (per-lane quant counters + EOD snapshot) — `remaining_gaps.md`.
4. **BLSH V2-scope re-classification** — a semantic scope change; `issuer_identity_findings.md`.
5. **Oracle event-version identity / supersede semantics** — `oracle_provenance.md` §"Bounded corrections".

## Pre-deploy checks

- `V2 fingerprint == 11107198c5b81237` (verified: none of the 5 hashed files touched).
- Full `pytest` green (consolidated run: see `remaining_gaps.md` §"Test status").
- `git diff --stat` = only the files above + this bundle + `.gitignore` (one added line for the
  git-ignored evidence dir).
- Production `v2_lane.db` md5 `29e57dbcd1a567fbc4bb0e73efdba95f` unchanged; Redis PONG.

## Deploy order

1. Merge this branch's commit — **code + tests only affect fresh ingestion and read models**; no
   running service is required for the code to be correct.
2. Before the next live Intelligence session, decide the D5 delivery-intent question. If "keep
   dry-run": correct any "delivery enabled" copy and stop. If "deliver": follow
   `intelligence_delivery_closure.md` steps 2–7 in a **separate** change.
3. The tz-rebuild (item 1 above) is independent and can follow any time; run it on a copy and
   diff the V2 replay before touching production.
