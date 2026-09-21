# D4 (startup) + D6 (accounting) — bounded verification

## D4 — startup verdict + repeated-start protection

### First-class verdict

`talonx_ops.prospective.proc.startup_verdict(info, verify, *, heartbeat_fresh, within_grace)`
returns exactly one of:

| verdict | condition | `prospective start` exit |
|---|---|---|
| `READY` | supervisor + V2 companion both alive **and** a fresh companion heartbeat | 0 |
| `STARTING` | a mandatory component (supervisor OR companion) not yet confirmed, still inside the 120 s grace | 0 |
| `NOT_STARTED` | nothing spawned / both mandatory components dead, no residuals | 2 |
| `FAILED_WITH_RESIDUALS` | a mandatory component missing after grace **and** owned processes remain (or both dead + residuals) | 4 (+ ownership-safe `stop_stack` cleanup, `start_cleanup.json`) |

`cmd_start` derives the verdict from the **actual process + heartbeat state**
(`verify_running` + a bounded heartbeat wait), **not** from the post-start
preflight snapshot that races the `:8787` bind. A missing mandatory component is
**never** downgraded to a cosmetic warning — it forces `STARTING` or
`FAILED_WITH_RESIDUALS`.

### Repeated / concurrent start

`start_stack` calls `assert_no_live_prior_stack()` first: a running
`talonx_v2.run --mode live` (a second `v2_lane.db` writer), `talonx_ops.supervisor
run`, or `prospective session-loop` → `ConcurrentStartError` → `cmd_start`
prints `START REFUSED`, writes `start_verify.json` `{"verdict":
"REFUSED_ALREADY_RUNNING"}`, exits **3**. **Nothing is spawned.** `--force`
overrides (`allow_when_running=True`).

### Tests — `tests/test_task117_startup_verdict.py` (11)

- `test_startup_verdict_matrix` — all 6 state combinations.
- `test_missing_mandatory_is_not_a_cosmetic_warning` — supervisor up / companion
  down / grace elapsed → `FAILED_WITH_RESIDUALS`, never `READY`/`STARTING`.
- `test_concurrent_start_is_refused` / `test_start_stack_guard_blocks_a_second_spawn`
  — a live prior stack → `ConcurrentStartError`, `spawned == []`.
- `test_start_stack_force_overrides_the_guard` — `--force` spawns anyway.

### Bounded — what this does NOT do

`verify_running` already polls with a retry budget; `cmd_start`'s heartbeat wait
is a fixed 120 s grace. No new supervision framework; the ownership-safe reap on
failure reuses the existing `stop_stack`.

## D6 — lane-scoped candidate / evaluation accounting

### The snapshot

`talonx_ops.prospective.lane_accounting.build_lane_accounting()` (read-only)
writes `lane_accounting_eod.json` into the session dir during `prospective close`
(`asserts["lane_accounting_snapshot"]`). It:

- keeps **Original / Experimental / V2** in separate blocks, each read from its
  own durable store (`dispatch_audit.rejected_candidates` / `exp_alerts.db` /
  `v2_lane.db`);
- records the **off-counter disposition class** explicitly
  (`THROTTLE / COOLDOWN / failed-revalidation` — "`in_metrics_quant_counter: false`");
- lists **in-flight** work (`v2_pending_entry_intents`, `v2_alert_outbox_pending`)
  with the note that reconciliation must account for it before a lane is
  declared closed;
- captures the comingled `metrics:<date>:quant:*` Redis family verbatim, tagged
  `lane_attributable: false` (D6: the keys carry no lane suffix — lane-suffixing
  them is a change to the hot quant path, **proposed not made**).

### Funnel closure — the "94-candidate gap"

The S3 Redis `metrics:2026-09-10:quant:*` counters **were retained** (Redis was
never flushed). `build_lane_accounting` reconciles them:

```
evaluated                 = 158
  failed_confluence        104
  published                  8   (== the 8 Experimental WOULD_PASS; Original 0, V2 0)
  dropped_opening_blackout  30
  failed_trend_gate          4
  dropped_closing_blackout   4
  failed_rr_gate             2
  dropped_us_session_closed  2
  -------------------------------
  terminal-with-counter    154
  residual                   4   = THROTTLE / COOLDOWN / failed-revalidation (off-counter)
```

pre-evaluation drops excluded: `dropped_duplicate_bars` 45,318,
`failed_min_volatility` 22,634.

**The S3 funnel closes exactly (residual 4 = off-counter class) — the same
mechanism that closed Sep-9 exactly.** The published audit's "94" was the
16:24:25Z ping's `126 candidates − 18 − 10 − 1 − 3` measured against the EOD
**displayed 3-gate breakdown**, not against the EOD **comingled `evaluated`
counter**. With the retained counter the gap is `RESOLVED_WITH_EVIDENCE` (see
`../task117_output_closure/` correction in `remaining_gaps.md`). This is not a
"rewrite without evidence" — the evidence (the counter family) is preserved and
cited.

### Tests — `tests/test_task117_lane_accounting.py` (5)

- lanes are separate; V2 read from its own DB.
- gap is `UNRESOLVED` when no metrics snapshot is reachable.
- funnel `CLOSED` (residual 4) when the comingled counter is present;
  `historical_94_candidate_gap.status == RESOLVED_WITH_EVIDENCE`.
- in-flight (`pending_entry_intents`, `v2_alert_outbox` PENDING) is reported.

### Bounded — what this does NOT do

No lane-suffixed Redis keys (hot quant path), no new metrics platform. This is
an **additive EOD snapshot** built from the durable per-lane stores, plus a
verbatim capture of the comingled counter.
