# Task 78I — Architecture and Ownership (Stage 0)

## Baseline
- Branch `research/talonx-strategy-validation`, starting SHA `6f6193f`, clean tree, in sync with
  origin. No conflicting session (`talonx.pids.json` absent, no `python.exe` processes running).
- `.venv/Scripts/python.exe` used throughout (same environment correction as Task 77I).

## The actual runtime — TWO separate products sharing infrastructure

This repository contains two independent applications that must never run against the same
Redis/broker state concurrently:

1. **The general trading pipeline** (`run_talonx.py`): market ingestion (`talonx_ingest`) →
   `talonx_quant.consumer.QuantScanner` (+ `FundamentalScanner`) → `talonx_brain.consumer.
   ResearchAgent` (Gemini) → `talonx_core.consumer.DecisionEngine` (a DIFFERENT class from
   `talonx_piv`'s own `DecisionEngine` — name collision only, no relationship) →
   `talonx_dispatch.consumer.DispatchAgent` → `talonx_paper.consumer.PaperTradingEngine`. Every
   component runs as a named `asyncio.create_task` inside one process; `--skip-*` flags select a
   subset.
2. **The PIV validation harness** (`talonx_piv/cli.py start`): its own `SessionRunner` polling
   Alpaca bars directly → `talonx_piv.decision_engine.DecisionEngine` (drives its OWN, separate
   `QuantScanner` instance) → `talonx_piv.lifecycle.PaperLifecycle` (the hardened, long-only,
   Task 76S/77I-safe PAPER execution boundary this whole multi-task program has been building).

**Confirmed double-evaluation risk**: `run_talonx.py`'s own `QuantScanner` (line 1097) and
`talonx_piv.decision_engine.DecisionEngine`'s `QuantScanner` (`decision_engine.py:84,109-110`)
both use `talonx_quant.config.QuantConfig`'s DEFAULT `signals_channel`/`rejected_candidates_channel`
and the same default `redis_url` (`TALONX_REDIS_URL`, defaulting to `redis://localhost:6379` in
BOTH `talonx_quant/config.py` and `talonx_piv/config.py`). Running both processes concurrently
against the same Redis would cross-contaminate: PIV's own DecisionEngine would also receive
`run_talonx.py`'s live-market-driven signals, and vice versa.

**This is already guarded**: `talonx_ops/preflight.py`'s `FullAppPreflight` has an explicit
`no_duplicate_full_app_or_piv_process` check that greps running processes for
`run_talonx\.py|talonx_piv\.cli` and fails if both patterns are found running. **This task
selects that existing guard as the authoritative mechanism** rather than inventing a second one,
and the new PIV supervisor (Stage 2) explicitly re-runs an equivalent check before starting (see
`supervisor_lifecycle_contract.md`) — belt-and-suspenders, reusing the established pattern rather
than trusting a single check point.

**Selected authoritative ingestion/decision path for THIS task's supervisor**: the PIV-native
path (`SessionRunner` + `talonx_piv.decision_engine.DecisionEngine`) — this is the harness Tasks
76S/77I/78I have been hardening (long-only contract, decision-contract wiring, durable ledgers,
shadow tracking, execution ownership). The supervisor built in Stage 2 launches PIV's own
components ONLY, and refuses to start if `run_talonx.py`'s pipeline is already running (reusing
the preflight check), and vice versa is already true (an operator starting `run_talonx.py` while
PIV is running would also fail that same check, unchanged).

## Components: process vs. module

| Component | Process or in-process module | Required or optional |
|---|---|---|
| `SessionRunner` + `DecisionEngine` (PIV) | in-process (one `asyncio` loop, `talonx_piv/cli.py start`) | required |
| `PaperLifecycle` / `AlpacaPaperClient` | in-process module, same process | required |
| `DecisionLedger`/`NotificationOutbox`/`ShadowLedger` | in-process modules, same process | required (durable decision recording); notification/shadow individually optional-to-succeed (independent branches, Task 77I) |
| Telegram inbound `/ping` listener | in-process `asyncio.create_task`, same process | optional (`--no-telegram-inbound`) |
| `talonx_brain` (Gemini) enrichment | in-process, invoked via a new PIV-side adapter (Stage 3) — the REAL `ResearchAgent`/LLM chain lives in a SEPARATE process today (`run_talonx.py`), never reused directly for PIV | optional |
| Dashboard (`dashboard_web.py`) | SEPARATE process (its own `aiohttp` server) | optional, read-only |
| Redis | external dependency, required only if `decision_path_enabled` | required for the decision path; PIV degrades to plumbing-only (`--no-decision-path`) without it |
| Execution ownership lock | in-process (OS file lock held by the PIV process) | required before any mutating action |

## Dependencies

`talonx_piv` already depends on `talonx_quant` (schemas + the real `QuantScanner`, reused
unmodified per Task 65B's own design) and `talonx_backtest.execution` (reused by `shadow_ledger.py`,
Task 77I). This task adds a dependency on `talonx_brain`'s LLM chain INTERFACE only
(`_BaseResearchChain`'s shape — a dependency-injectable base class), not on `talonx_brain`'s own
Redis-channel-driven `ResearchAgent`/`store.py` (whose key scheme has no `decision_id` concept at
all — see `gemini_authority_boundary.md`).

## Smallest implementation plan

1. Close the four Task 77I gaps in `talonx_piv`'s own modules (shadow independence audit + fix if
   needed, horizon exits, status projections, execution ownership) — Stage 1.
2. One new `talonx_piv/supervisor.py`, reusing `talonx_ops/runtime_manifest.py`'s
   component-table pattern and `talonx_ops/preflight.py`'s read-only-checklist pattern, driving
   the EXISTING `SessionRunner`/`DecisionEngine`/`PaperLifecycle` — no duplicate consumer, no
   second execution writer — Stage 2.
3. One new `talonx_piv/gemini_enrichment.py`, decision_id-keyed, wrapping (not reimplementing)
   `talonx_brain.llm`'s chain interface — Stage 3.
4. One additive, read-only `aiohttp` GET route on the EXISTING `dashboard_web.py` server —
   Stage 4.
5. Offline rehearsal driving the real supervisor with fakes throughout — Stage 5.

## Baseline suites run before editing
`test_task77i_*.py`, `test_task76s_*.py`, `test_task72o_eod_lifecycle.py`, `test_task65b_*.py`,
`test_task64_piv.py` — all passing at the Task 77I end state (2316 passed, 1 skipped, 10 xfailed,
0 failures — see Task 77I's own `test_results.txt`, re-confirmed clean at this task's Stage 0
start via `.venv/Scripts/python.exe -m pytest --collect-only` = 2327 collected, 0 errors, matching
exactly).
