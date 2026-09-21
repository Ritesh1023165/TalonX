# Task 83-R1 — Production Collector Correctness and Evidence-Integrity Closure

Closes the verified Task 83 collector defects without reopening Task 81/82
or launching any runtime. Start SHA `fd9b66a`.

## Deliverables

| # | Deliverable | File |
|---|---|---|
| 1 | Completed acceptance matrix | `acceptance_matrix.md` |
| 2 | Stable-manifest / runtime-status contract | `contracts.md` §1 |
| 3 | Event / run-scope alignment contract | `contracts.md` §2 |
| 4 | Transport-health state machine | `contracts.md` §3 |
| 5 | Notification telemetry contract | `contracts.md` §4 |
| 6 | Archive-integrity specification | `contracts.md` §5 |
| 7 | Expanded rehearsal matrix (exact results) | `expanded_rehearsal_matrix.md`, `expanded_rehearsal_matrix.csv`, `retained_20_scenarios_matrix.csv` |
| 8 | Raw focused / adjacent / full-suite outputs | `raw_test_output/` |
| 9 | Fresh-clone manifest verification | `fresh_clone_manifest_verification.md` |
| 10 | Start/final SHAs, changed files, remaining blockers | `verification_report.md`, `remaining_blockers.md` |
| — | Evidence manifest (LF-normalized hashing) | `evidence_manifest.json`, `_make_manifest.py` |

## What changed (the six defects)

1. **False `manifest_conflict` from `generated_at`.** The immutable
   `manifest.json` now carries only stable identity/binding fields; all
   mutable data moved to an atomically-written `runtime_status.json`.
   Identical bindings never conflict regardless of elapsed time; a genuine
   binding change fails visibly (field-level diff) without overwriting.
2. **Session/event-unsafe alignment.** `ComparisonRecord` gains
   `run_scope` + `event_identity` + `record_kind`; alignment partitions by
   PIV session and keys events on `(date, stage, symbol, event_identity)`.
   Multiple same-symbol decisions stay distinct; late arrivals re-align
   onto their own key. Original run scope is collector-derived from
   verified `runtime_metadata.json` (or `UNSCOPED` → no event-level
   agreement). Original counters are explicit `AGGREGATE` records.
3. **Swallowed transport failures reported as `NOT_RUN`.** A
   `TransportHealth` state machine per pipeline, snapshot passed into every
   `collect_once`. A failed subscription is `DISCONNECTED`; one pipeline's
   failure never suppresses the other; PIV Pub/Sub health is separate from
   PIV state-file health; reconnects leave recovery evidence.
4. **Non-authoritative PIV Telegram zero evidence.** Durable
   `piv_notification_telemetry.json` written by the PIV runtime at the
   real send / poller boundaries. The archive asserts zero only for
   `VERIFIED_ZERO` (telemetry present for the session + outbound/inbound
   disabled + counters zero); missing telemetry is `UNVERIFIED`.
5. **Non-fail-closed archive integrity.** `verify_archive` detects eight
   corruption classes and never silently drops a malformed record; the
   collector verifies prior integrity before writing and aborts (no hash
   regeneration) on corruption; all mutable writes are atomic; every write
   path runs under the collector lock; dashboards stop treating corrupt
   totals as trustworthy.
6. **Committed evidence-manifest hash mismatch.** LF-normalized hashing +
   `.gitattributes` (`eol=lf` for this dir) + explicit `content_commit`
   (no self-referential SHA), with the generator and manifest excluded.

## Verdict

See `verification_report.md`.
