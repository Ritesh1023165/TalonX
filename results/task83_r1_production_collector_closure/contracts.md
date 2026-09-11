# Task 83-R1 — Contracts

## 1. Stable-manifest / runtime-status contract (§2)

### `manifest.json` — IMMUTABLE

Written once per date, only after the trading date **and** the PIV
session/bindings are resolvable. Contains ONLY these fields
(`talonx_compare.evidence.IMMUTABLE_MANIFEST_FIELDS`):

```
schema_version, trading_date,
original: { redis_url_scheme, redis_db, channels[], stage_modules[], execution_class }
piv:      { session_id, trading_date_et, runtime_sha, config_hash, feed_mode,
            redis_url_scheme, redis_db, redis_namespace, channels[], universe[],
            execution_mode, strategy_approval_status, real_capital_prohibited }
collector:{ namespace, role, publishes, acknowledges, mutates_observed_pipelines }
operational_agreement_only, not_alpha_evidence, evidence_label
```

- **No** `generated_at`, redis reachability, `session_enabled`, `kill_switch`,
  health, counters, or transport state. A programming attempt to write one
  raises `ValueError`.
- A second pass with **identical** bindings is a silent no-op success —
  regardless of elapsed time (this closes the reproduced
  `generated_at`-driven false `manifest_conflict`).
- A second pass with a **changed** `session_id` / `runtime_sha` /
  `config_hash` / `feed_mode` / redis endpoint / channel set / universe /
  `execution_mode` returns `manifest_conflict=True` with a field-level diff
  in `manifest_changed_fields`, emits a `WRONG_SESSION` diagnostic against
  `manifest.json`, and **never overwrites** the original file.

### `runtime_status.json` — MUTABLE, atomic

Rewritten every pass via temp-file + `os.replace`:

```
trading_date, generated_at,
collection: { pass_count, records_appended{original,piv}, duplicates_skipped,
              aligned_pairs, divergences }
transport_health: { ORIGINAL:{...}, PIV:{...} }        # §4 snapshot
original_metrics_redis_reachable,
original_run_scope: { value, derivation, runtime_metadata_present }
piv_lifecycle_status: { session_enabled, kill_switch, entry_admission_blocked }
piv_session_id, eod_status, eod_trading_date_et,
source_health, notification_telemetry_verdict, not_alpha_evidence
```

### EOD

An EOD update writes the `eod` ComparisonRecord under the **archived**
`run_scope` and updates `runtime_status.json` (`eod_status`). The immutable
manifest is byte-unchanged.

## 2. Event / run-scope alignment contract (§3)

`ComparisonRecord` (`talonx_compare.identity`) adds:

| field | meaning |
|---|---|
| `run_scope` | PIV: the session id. Original: a **collector-derived** scope `orig:<sha256[:12] of commit_sha\|started_at\|run_mode\|provider>` from verified `runtime_metadata.json`, or `UNSCOPED`. Never an Original-emitted session id (Original emits none). |
| `record_kind` | `EVENT` or `AGGREGATE` |
| `event_identity` | `decision_id` when present; else `causal:<payload_fingerprint>` (stage + symbol + source_bar_time + outcome + reason codes all fold into the fingerprint; event-time noise excluded); else `agg:<name>` for aggregates |
| `aggregate_name` / `aggregate_value` | for `AGGREGATE` records |

Alignment (`talonx_compare.alignment`):

- partitions PIV records by `run_scope`; **each PIV session is aligned
  independently** — two sessions' records are never paired.
- keys on `(trading_date, stage, symbol, event_identity)`. Multiple
  same-symbol decisions/events on one day have distinct `event_identity`
  ⇒ distinct rows, never collapsed to "latest".
- a late arrival with a new `event_identity` appends onto its own key; a
  re-projection of the **same** `event_identity` in a later state replaces
  only that key (latest event_time wins), never an unrelated record.
- `AGGREGATE` records key on `agg:<name>` (value-independent) so alignment
  keeps the **latest value** per counter; divergence compares aggregate
  **values**, never fingerprints.
- if the Original run scope is `UNSCOPED`, every Original×PIV pair is
  classified `SOURCE_UNAVAILABLE` ("event-level agreement not asserted") —
  `comparison.json.event_level_agreement_assertable=false`.

`per_stage_totals` entries are typed: `kind=EVENT` blocks carry
`original_events`/`piv_events` counts; `kind=AGGREGATE` blocks carry
`original_aggregate_total`/`piv_aggregate_total`.

## 3. Transport-health state machine (§4)

`talonx_compare.transport.TransportHealth`, one per pipeline, owned by
`CollectorService`:

```
                mark_attempt
   NOT_RUN ───────────────────▶ (attempted)
                                   │ mark_error
                                   ▼
                              DISCONNECTED ◀──────────── (drop / ping fail)
                                   │ mark_connected
                                   ▼
   RUNNING ◀── mark_message ── RUNNING ── age > stale_seconds ──▶ STALE
     ▲                                                             │
     └───────────────── mark_message / mark_connected ─────────────┘
```

Tracked: `connection_attempted`, `connected`, `subscribed_channels`,
`last_message_at`, `last_heartbeat_at`, `last_error`, `reconnect_count`,
derived `state`. `mark_connected` after a prior down state increments
`reconnect_count`.

- `snapshot()` returns a **plain dict copy** (thread-safe hand-off).
  `CollectorService` passes `{ORIGINAL:…, PIV:…}` into every
  `collect_once(transport_health=…)`.
- A failed subscription ⇒ `DISCONNECTED`, **never** `NOT_RUN`.
  `source_health.original_redis` and `.piv_pubsub` reflect it, with
  `trustworthy_zero=false`.
- One pipeline's `DISCONNECTED` never changes the other's health and never
  suppresses its evidence. PIV **Pub/Sub** health (`source_health.piv_pubsub`)
  is separate from PIV **state-file** health (`piv_session_identity`,
  `piv_events`, `piv_lifecycle_state`).
- Buffer swap is atomic (`_Buffer.swap`): a message appended during a pass
  lands in the fresh list and is retained for the next pass.
- On reconnect the subscribe loop injects a `TRANSPORT_RECONNECT`
  breadcrumb; `reconnect_count` in `runtime_status.json` is the recovery
  evidence. No buffered message is dropped.
- Original metrics reads: the collector issues only `ping`/`scan_iter`/
  `mget`; a `FakeRedis.write_calls == []` assertion proves read-only. A
  read failure is recorded as `SOURCE_UNAVAILABLE` + `DISCONNECTED`.

## 4. Notification telemetry contract (§5)

`<PIV state_dir>/piv_notification_telemetry.json`
(`talonx_piv.notification_telemetry`), atomic read-merge-write:

```
session_id, trading_date_et,
ownership: { outbound_enabled, sender_constructed,
             inbound_poller_constructed, inbound_poller_started }
outbound:  { attempts, successes, failures, last_attempt_at }
inbound:   { poll_starts, poll_attempts, last_start_at }
updated_at
```

- `EventBus.__init__(telemetry_path=…)` writes `ownership.outbound_enabled`
  / `sender_constructed` (= `telegram_send is not None`).
- `EventBus.emit` persists `outbound.attempts += 1` and
  `successes`/`failures` **at the actual send boundary**, in a `finally`
  — an attempt that raises or returns falsey still counts.
- `cli.runtime` passes `telemetry_path` + writes
  `inbound_poller_constructed`; `cli.run_session` writes
  `inbound_poller_started` + `inbound.poll_starts += 1`.
- `talonx_compare.notification.assess_piv_notification` verdicts:
  `MISSING` (no file), `WRONG_SESSION`, `ATTEMPTS_RECORDED`
  (any counter > 0), `VERIFIED_ZERO`, `UNVERIFIED`.
- The archive's `piv_zero_attempt_assertion` is `true` **only** for
  `VERIFIED_ZERO` = telemetry exists for the archived session **and**
  outbound + inbound disabled **and** every counter zero. Otherwise
  `false` with the verdict shown. Missing telemetry is **UNVERIFIED**,
  never zero.
- PIV outbound stays disabled by default (`PivConfig.telegram_enabled` is
  `False`); no test performs a real Telegram request. Original notification
  ownership is unchanged (no diff in `talonx_dispatch/`, `talonx_core`,
  `run_talonx.py`).

## 5. Archive-integrity specification (§6)

Required file set (`talonx_compare.evidence.REQUIRED_FILES`):
`manifest.json, runtime_status.json, original_events.jsonl,
piv_records.jsonl, comparison.json, divergences.json, telegram.json,
diagnostics.json`. `file_hashes.json` hashes the required set and is the
only allowed extra.

`EvidenceWriter.verify_archive()` returns `ArchiveIntegrity(state, ok,
problems, checked_files, session_scope_notes)` and detects:

| condition | detection |
|---|---|
| required file missing | name not present ⇒ `UNREADABLE` |
| unexpected file / stray `.tmp` | present, not required, not allowed-extra |
| malformed JSON | any `_JSON_FILES` entry fails `json.loads` ⇒ `UNREADABLE` |
| malformed JSONL record | per-line `json.loads` failure (never skipped silently) |
| missing / duplicate `_id` | per-line `_id` check across the stream |
| hash mismatch | recorded vs recomputed **LF-normalized** sha256 |
| truncated append-only stream | file non-empty and not `\n`-terminated |
| wrong-date record | `record.trading_date != <dir>` |
| incomplete hash inventory | a present required file absent from `file_hashes.json.hashes` |

- Multiple same-**date** PIV sessions legitimately coexist (separated by
  `run_scope`); a changed session id is a **manifest binding conflict**,
  not record corruption — surfaced via `session_scope_notes`, never `ok=False`.
- Before modifying an **existing** archive the collector calls
  `verify_before_write`; if `ok` is false it **aborts the write phase**
  (`CollectResult.write_aborted=True`), records an `UNREADABLE` diagnostic
  ("write phase ABORTED, hashes NOT regenerated"), and leaves
  `file_hashes.json` untouched.
- All mutable writes (`manifest`, `runtime_status`, `comparison`,
  `divergences`, `telegram`, `diagnostics`, `file_hashes`, cursors) are
  atomic (`_atomic_write` = temp + `os.replace`, `newline="\n"`).
- Every write path — including `python -m talonx_compare collect-once` —
  runs inside `CollectorLock` (`acquire_wait=15s`, `stale_after=120s`).
  Integrity metadata (`file_hashes.json`) is regenerated **after**
  successful writes only.
- `CompareArchive.day` / `compare_view` / `streamlit_piv_comparison_payload`
  set `trustworthy=false` when integrity fails, move `per_stage_totals` to
  an empty dict, and expose the raw comparison under
  `untrusted_comparison` clearly labelled.
- Committed evidence manifest: `_make_manifest.py` hashes **git-normalized
  (LF) bytes** and records `content_commit` explicitly (not a
  self-referential final SHA); it excludes itself and
  `evidence_manifest.json`. `.gitattributes` pins the R1 evidence path to
  `eol=lf`.
