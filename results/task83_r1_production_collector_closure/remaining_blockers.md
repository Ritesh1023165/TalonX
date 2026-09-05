# Task 83-R1 — Remaining Blockers vs Backlog

## Blockers to the separately-authorized shadow pilot: none from this task

Task 83-R1 closes the verified Task 83 collector defects (false
`manifest_conflict`, session/event-unsafe alignment, swallowed transport
failures reported as `NOT_RUN`, non-authoritative PIV Telegram zero
evidence, non-fail-closed archive integrity, committed-manifest hash
mismatch). It reopens no Task 81/82 work and launches nothing.

## Carried forward (surfaced, not resolved here)

| Item | State | Why not in scope |
|---|---|---|
| Durable PIV `QuantStateStore` | `NOT_IMPLEMENTED` (still surfaced as a capability limitation in the projection and both dashboards) | Task 83-R1 is a collector-correctness closure; the honest limitation is unchanged and sufficient |
| IEX receipt-time vs source-time | `UNRESOLVED` — `ComparisonRecord` still carries both `event_time` and `source_bar_time`; `FEED_INPUT_DIFFERENCE` keys on `source_bar_time` | needs an authorized raw per-bar source-`t` log; no data acquisition permitted |
| Original does not emit a run/session id | by design — the collector derives `orig:<hash>` from `runtime_metadata.json`, labelled collector-derived; `UNSCOPED` when metadata is absent | changing Original to stamp a session id is Original-side scope, explicitly out of bounds |
| `warmup_df` wiring for the backtest CLI | carried from Task 81-R2 — makes `test_backtest_*` ~36 min | unrelated to the collector |
| Live `CollectorService` operation | provided and unit-exercised against async fakes; not started against real Redis | needs a running Redis + operator authorization (a pilot) |

## Notes for the shadow-pilot operator

- Start the collector read-only: `python -m talonx_compare run`. It holds
  only `<collector state_dir>/collector.lock`; never an Original/PIV lock;
  never publishes; never writes to Redis.
- `manifest.json` per date is immutable. If the PIV session id / runtime
  SHA / config hash / feed / redis / channel / universe / execution mode
  changes mid-day, the next pass reports `manifest_conflict` (with a
  field-level diff) and keeps the original manifest; the new session's
  records still land, separated by `run_scope`.
- `runtime_status.json` is the live mutable view (transport health,
  collection stats, EOD status). Read it, not the manifest, for "what is
  happening now".
- If `runtime_status.transport_health.ORIGINAL.state == DISCONNECTED`,
  Original comparison is `SOURCE_UNAVAILABLE` — do not read PIV-vs-Original
  agreement as meaningful until it recovers. PIV-only evidence is still
  valid.
- `telegram.json.piv_notification_telemetry.verdict` must be
  `VERIFIED_ZERO` for a clean pilot. `MISSING` means the PIV runtime did
  not write telemetry (start it via `talonx_piv.cli`, which now does).
- If a dashboard shows `trustworthy: false` / empty `per_stage_totals`,
  the archive failed integrity — investigate `archive_integrity.problems`;
  the collector will refuse to write further passes for that date until
  the corruption is resolved.
