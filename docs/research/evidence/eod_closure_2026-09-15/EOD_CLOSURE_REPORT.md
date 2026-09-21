# EOD Verification and Controlled Development Shutdown — 2026-09-15

**Type**: operational closure, not a development task. No code changed.
Raw operational evidence (checkpoint JSON, V2 ledger copy, lane
accounting) is preserved locally under the existing, gitignored
operational-journal convention at
`results/prospective_2026-09-15/` (not committed, per
`.gitignore:40`) — this document is the sanitized, committed summary.

## 1. Session boundary (verified against the real XNYS calendar, not inferred from UTC date rollover)

- **Inspection time**: `2026-09-15T20:46:35Z` UTC / `2026-09-15T21:46:35+01:00` BST (the shell's own `TZ=Europe/London` conversion was found to be stale/incorrect during this check — it reported GMT+0000 instead of BST; Python's `zoneinfo`, which correctly resolves the IANA database, was used instead and is the source of every UK-local timestamp in this report).
- **Exchange session**: XNYS, 2026-09-15 (Tuesday) — a genuine trading session (`exchange_calendars.get_calendar("XNYS").is_session(date) == True`), no holiday, no early close.
- **Regular close**: `2026-09-15T20:00:00Z` UTC (`16:00 ET`, EDT).
- **`talonx_ingest.session.get_session_state(now)` → `"after_hours"`** — regular trading confirmed ended.
- **`talonx_ops.prospective.checkpoint.eod_state(now)` → `PENDING`** — within the 90-minute post-close grace window (deadline `2026-09-15T21:30:00Z`); EOD reconciliation was genuinely due, not run early and not missed.
- **Run/session identity**: `results/prospective_2026-09-15/` (started `2026-09-15T03:55:47Z`), campaign day 6 (`campaign_start_date=2026-09-08`).

## 2. Obligations inspected BEFORE reconciliation (fresh, not assumed from any prior report)

**V2** (`v2_lane.db`, read directly):
- Cash: `$300,000.00` (unchanged from starting cash — the full amount, not an allocation size).
- Open positions: **0**. Closed positions: 0. `EXIT_UNRESOLVED`: **0**.
- Trades today: **0**. Pending entry intents (`pending_entry_intents` table): **0** rows. Cooldowns: **0** rows.
- `v2_alert_outbox`: **0 rows total** (no state to enumerate — empty).

**Original** (`~/.talonx/paper_trading.db`, read directly):
- Intraday lane: `initial_balance=$10,000`, `current_cash=$10,000` (unchanged), 0 open positions, 0 trade-history rows.
- Long-term lane: `initial_balance=$15,000`, `current_cash=$15,000` (unchanged), 0 positions, 0 trades.
- Both lanes fully inert — consistent with `close`'s own `no_cross_lane_contamination: PASS` assert.

**Intelligence outbox** (`~/.talonx/ingestion_ledger.db::intelligence_delivery`, all-time / last-24h):
- `AMBIGUOUS`: **2** (all-time and last-24h identical — both from `2026-09-14`, error `"send cancelled while possibly in flight"`: `AXP:EXECUTIVE_CHANGE`, `ADI:INSIDER_TRANSACTION`). **Left untouched, no forced retry**, per the outbox's own durable-AMBIGUOUS contract (a human decision, not an automatic one).
- `IN_FLIGHT`: **0** (no unconfirmed in-progress claims at inspection time).
- `PENDING`: **83** (all-time) / 82 (a moment earlier) — a real, persisted, recoverable backlog (mostly older `HIGH`/`MEDIUM`-band insider-transaction cards, some genuinely stale relative to the 6h `IMMEDIATE` cutoff — see the Task 140/140b/140c evidence bundles for their own detailed characterization). Recoverable after restart: **yes** — this is exactly what `DeliveryOutbox.pending()`/the send loop re-derives on every cycle; nothing about this backlog depends on the current process's memory.
- `SENT`: 268 all-time / 262 last-24h.

**No overdue or unresolved price/settlement obligation** was found for either lane. **Earliest required next decision/management time**: none identified — no open position, no pending intent, no reservation with a deadline.

## 3. EOD reconciliation result

Command: `python -m talonx_ops.prospective close --no-shutdown` (first, to review before committing to shutdown), then `python -m talonx_ops.prospective close` (the actual close, reconciliation + shutdown together — the tool's own default, per its current `--help`).

- Start: `2026-09-15T20:47:xxZ`. End: `2026-09-15T20:48:47+01:00` (`21:48:47` BST as reported by the tool). Exit code: `0` for both invocations.
- **Verdict: `PASS_WITH_FINDINGS`** (identical on both runs — confirmed idempotent).
- All 15 asserts `PASS` except **`base_reconciliation: PARTIAL`** — the ONE finding: *"base eod_reconciliation PARTIAL (typically: no PIV reader) -- mismatches=[]"*.
  - **Intentionally unchecked component, explicit**: PIV (Alpaca paper) is not part of this dev deployment — `talonx_ops.eod_reconciliation.run_and_persist()`'s own `component_status` confirms `piv_paper: NOT_CHECKED, "no piv_reader injected (offline / not opted in)"`. **`mismatches: []`** — zero actual mismatches among everything that WAS checked (`original_paper`, `experimental_paper`, `alert_stores`, all `CHECKED`).
  - A successful exit code is not treated as sufficient proof on its own here — the assert-by-assert breakdown and the explicit PIV disclosure are what this report relies on, not the exit code alone.
- V2 near-miss funnel: 4 historical `>=2`-distinct-insider clusters, all **stale**, 0 fresh-eligible — nothing pending entry.

## 4. Effective configuration snapshot (captured from live child-process state, BEFORE shutdown)

Captured via `eod_final_checkpoint.json` and `v2_service_status.eod.json` (both written by `close` while the stack was still live, at `2026-09-15T20:48:3x–4xZ`):

| | value |
|---|---|
| Repository HEAD at close | `bdefb164cca81132917b03fc2b0aa53805595736` (tree clean) |
| **Original's actual running commit** | `12be1bd7424e37792c33c8e95b88a79a83beb67b` — **not** current HEAD; Original was last restarted `2026-09-15T10:40:07Z` and no change since then touched any module it imports, so it correctly never needed another restart. Repository HEAD and running-component version are explicitly kept distinct here. |
| V1 (Original) fingerprint check | `v1_fingerprint_ok: true` |
| V2 fingerprint | `11107198c5b81237` — `v2_fingerprint_ok: true` (unchanged from the long-established frozen baseline) |
| GATED admission | `durable_store_gate_enabled: true` (confirmed both live, in `v2_service_status.eod.json`, AND persistently in `.env`: `TALONX_V2_DURABLE_STORE_ENABLED=true`) |
| V2 execution scope | `execution_scope_enforced: true`, `execution_scope_count: 626` |
| V2 broad discovery | enabled (`--enable-broad-discovery` in the live launch argv) |
| Intelligence delivery enablement | not set in `.env` (`TALONX_INTEL_DELIVER_CARDS` absent) — running on its established code default (cards ON); **V2's own** `delivery_enabled: true` confirmed directly |
| Routine digest | `TALONX_INTEL_DELIVER_DIGEST_ENABLED` absent from `.env` — running on its code default, **`False`/OFF** (established this session's earlier Task 140 work; not re-toggled here) |
| **V2 pricing mode / provider** | `pricing_mode: "csv"`, `pricing_adapter` label `"csv:frozen_bar_dirs"` — **see the explicit freshness-gap finding below; this label is a fallback string, not a real adapter name, in "csv" mode** |
| Latest usable V2 price date (direct inspection, not inferred) | **`2026-08-14`** (last row of `results/task95g_broad_cross_sectional/_daily/AAPL.csv`, the default `--bar-dir` source with no override in the live launch argv) — **~22 trading days / 32 calendar days stale relative to today (2026-09-15)** |
| Intelligence collection scope (effective symbol count) | **not captured in this session's checkpoint** — this specific field was not part of `eod_final_checkpoint.json`'s `intelligence` section; not re-verified at this exact close moment (a genuine, disclosed gap in this report, not a claim of "unknown forever" — the figure was independently verified as 569 earlier in this project's history, not re-confirmed here) |
| Persistent config source | `.env` (repo root) — survives restart; runtime env-var overrides do not, by design |
| Original's own market feed at close | `state: HEALTHY`, `symbols_priced: 51`, `coverage_ratio: 1.0`, `newest_tick_age_seconds: 12` |
| Telegram listener ownership at close | `telegram_get_updates_owners: 1`, `telegram_poller.logical_owners: 1` (pid 13616) — single-owner confirmed |

### Explicit freshness-gap finding — V2 pricing (not silently accepted, not silently changed)

`talonx_v2/service.py`: in `pricing_mode == "csv"` (the mode actually running), `self._resolver` is **never constructed** (`if pricing_mode != "csv": self._resolver = ...`) — so the `pricing_adapter` status field's `"csv:frozen_bar_dirs"` value is a **hardcoded fallback string** used whenever the resolver is `None`, not a real registered adapter name, and the `pricing_unavailable_recent` tracking list is **structurally always empty** in this mode (it reads from `self._resolver.last`, which doesn't exist) — meaning this mode has **no live visibility into stale/unavailable prices at all**, unlike the newer resolver-based modes.

Direct inspection of the actual default bar directory (`results/task95g_broad_cross_sectional/_daily/`, used because the live launch argv passed no `--bar-dir` override) shows `AAPL.csv`'s last row is dated **`2026-08-14`**. `CsvBarAdapter.session(symbol, date)` returns `None` (not a stale/incorrect price) for a date it doesn't have — so this gap does **not** create a silently-wrong-price risk; it would correctly manifest as "no price found" if a real qualifying cluster required a fill on any date after 2026-08-14. It has not yet been exercised this campaign (0 trades to date). **Per the closure task's own explicit instruction, this is disclosed here and not silently fixed, switched, or worked around** — it is the operator's decision whether the current "csv" pricing mode (a frozen historical snapshot, "byte-identical to the pre-Task-117 behaviour" per the code's own comment) remains appropriate, or whether a resolver-based mode (`--pricing-mode candidate`/similar) should be adopted for genuinely live paper execution.

## 5. Shutdown

`stop_stack()` (bounded: 45s grace per component, 120s overall budget) completed in **3.5s**, `controlled_shutdown_complete: PASS`, `residual_talonx_processes: []`.

| component | result |
|---|---|
| checkpoint_daemon (pid 14960) | stopped, 0 residual |
| v2_companion (pid 6380) | stopped, 0 residual |
| supervisor (pid 8596, owns Original/Intelligence/Experimental/dashboard) | stopped, 0 residual |

**Independently re-verified** (not just the tool's own self-report):
- `Get-CimInstance Win32_Process` — no process matching `talonx_v2`, `talonx_ops.supervisor`, `intelligence.service`, `run_talonx.py`, or `talonx_ops.prospective` remains.
- Ports `8787`/`8760`/`8770`/`8501` — all closed.
- `v2_lane.db.startlock` — removed (lock correctly released, gated on zero residuals per the tool's own ownership-token discipline).
- `.run/talonx.pids.json` — cleared.
- `v2_lane.db` — present, `69,632` bytes, cash still reads `$300,000.00`; `v2_lane.db-wal` is `0` bytes (cleanly checkpointed); no WAL/SHM file was deleted by this closure.
- `ingestion_ledger.db` / `paper_trading.db` — both present, untouched.
- **Redis** (`talonx-redis` Docker container) — left running, untouched, `Up 18 hours (healthy)` — not part of this application's own lifecycle.
- Original's terminal AMBIGUOUS/PENDING Intelligence rows — unchanged by shutdown (verified by re-reading the same counts after stop).

## 6. Next-start procedure (not executed, not scheduled)

1. Candidate SHA to start from: **`bdefb164cca81132917b03fc2b0aa53805595736`** (current HEAD at closure time) — or whatever HEAD is current at actual start time, verified fresh, not assumed from this report.
2. Same paths: `--db C:\workspace\TalonX\v2_lane.db`, `--status-path C:\workspace\TalonX\v2_service_status.json`, `~/.talonx/ingestion_ledger.db`, `~/.talonx/paper_trading.db` — none moved or altered by this closure.
3. Required configuration: `.env` (repo root) already carries `TALONX_V2_DURABLE_STORE_ENABLED=true` (GATED) persistently — no manual re-set needed. Preflight: `python -m talonx_ops.prospective preflight` (existing supported command; not run as part of this closure — confirm no residual stack first).
4. **Verify no stack already exists** before starting: `python -m talonx_ops.prospective status` (expect a clean read or a "not running" indication) + a process/port check identical to §5 above.
5. Checkpoint/session initialization: `python -m talonx_ops.prospective start --deliver --transport telegram` (the same flag set as today's `session.pids.json` launch argv: `--mode live --form4-source insider --pricing-mode csv --execution-scope resolved-active-watchlist --enable-broad-discovery`), which creates the day's own `results/prospective_YYYY-MM-DD/` session directory.
6. **Earliest required start time, based on actual obligations found in this closure**: no persisted obligation requires an earlier-than-preferred start (no open position, no pending intent, no reservation deadline). The preferred **08:00 UK local** window is genuinely safe to use as the next start time — tomorrow's XNYS session (2026-09-16, a normal trading day) opens `13:30 UTC` = **14:30 BST**, comfortably after 08:00 UK, leaving time for premarket/backfill before the open.

**Not started now. No automatic start scheduled** — this automation is not authorized.

## 7. Evidence index

- This document (sanitized, committed).
- `results/prospective_2026-09-15/` (local, gitignored, raw): `eod_final_checkpoint.json`, `v2_service_status.eod.json`, `v2_lane.db.eod-copy`, `lane_accounting_eod.json`, `session.pids.json` (the day's original launch record), `preflight.json`/`preflight_poststart.json`, `events.jsonl`, `checkpoints/`.
- Prior, unrelated evidence in this repository (`docs/research/evidence/task140/...`) is unaffected and unreferenced-as-modified by this closure.

## 8. Review note (appended 2026-09-15, Session 2 documentation pass — not a re-litigation of §1-7 above)

This section is appended, not edited into, the original report above —
same append-only discipline as `docs/product/DECISION_LOG.md`. Full
detail and the linked open issue live in `docs/product/
OPERATIONAL_FINDINGS.md` (`OPS-001`, `OPS-002`); this is a short pointer
plus the two qualifications the original report did not itself state.

**Scope qualification**: EOD accounting and controlled shutdown were
supported by this report — the reconciliation was genuinely clean
(zero mismatches among checked components) and the shutdown was
genuinely graceful (zero residual processes). **This does not
establish readiness for current-session V2 paper execution.** See
`OPERATIONAL_FINDINGS.md` `OPS-002` for the specific gap this refers
to: V2's `"csv"` pricing mode never constructs its own freshness-
tracking resolver, so its price-staleness telemetry is structurally
always empty, and the actual default bar directory's latest usable
price (`2026-08-14`) is materially stale relative to this closure's
session date. This does not mean price lookups don't happen (the real
lookup, `CsvBarAdapter.session()`, is separate from the missing
diagnostic resolver and fails safely — returns `None`, never a wrong
price) — see `OPS-002` for the full, careful distinction.

**Next-start qualification** (appends to §6 above, does not replace
it):

- No persisted obligation was reported to require an earlier-than-
  preferred start — that finding in §6 stands.
- This is **not proof of complete trading readiness** — see the scope
  qualification above.
- Monitoring-only operation and execution-capable V2 acceptance are
  **distinct** claims; §6's clean next-start procedure is a claim about
  the former (the process/accounting lifecycle can safely restart on
  the existing schedule), not the latter.
- The `csv` launch command recorded in §6 step 5 must **not** be
  presented as fully execution-ready until `OPS-002` is resolved, or
  is explicitly shown as running in a degraded/monitoring-only mode.
- Starting at 08:00 UK, as §6 concludes is safe relative to obligations,
  leaves an **intentional monitoring gap overnight** — this was true
  of §6's own conclusion and is restated here for visibility, not newly
  discovered.
- **No launch is scheduled or authorized by this documentation task**,
  same as §6's own closing statement.
- No supported monitoring-only switch is prescribed here — none was
  confirmed to exist in the code/runbooks inspected during this
  documentation pass; inventing one is out of scope.

**Evidence reference**: `docs/product/OPERATIONAL_FINDINGS.md`
(`OPS-001`, `OPS-002`); `docs/product/DECISION_LOG.md` (Session 2);
`docs/product/REQUIREMENTS_TRACKER.md` (`S2-12`).
