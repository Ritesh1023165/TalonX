# Task 66B-PREP — Full application E2E readiness audit + deterministic startup hardening

Branch `research/talonx-strategy-validation`, starting SHA `c431901f69f55ca12e94c366129e6f5dbe1d8f71`.

## Objective change acknowledged

Tomorrow's validation target moved from the narrow `talonx_piv` runtime to the **normal**
`run_talonx.py` application (Market -> Quant -> Brain -> Core -> Dispatch -> Paper -> Telegram).
The cron job scheduled at the end of the previous task (targeting a PIV session tomorrow morning)
was removed as part of this task's cleanup authority, since it would have launched the wrong
runtime and this task explicitly forbids scheduling tomorrow's run itself.

## A) Full application runtime audit

Traced `run_talonx.py`'s `main()` directly (not docs) — 20 runtime components documented in
`talonx_ops/runtime_manifest.py` / `full_app_runtime_manifest.json`, with the human-readable graph
in `full_app_runtime_graph.md`, including an explicit table of how this runtime differs from PIV
(market-data provider, broker/paper execution path, Brain/Core/Dispatch participation,
readiness/staleness architecture, reconciliation architecture) — the two runtimes are **not**
merged by this task.

## B) Deterministic Quant preseed ordering

Closed a real startup race: `WatchlistDrivenQuantPreseed`'s own initial preseed previously ran as
an `asyncio.create_task()` in the same batch as the market-data and `quant_scanner.run()` tasks,
with no ordering guarantee against preseed's real yfinance network I/O. `talonx_quant/
preseed_ordering.py::run_initial_preseed()` is now awaited directly in `main()`, before any task
exists — reusing `QuantScanner.preseed_symbols()` completely unmodified, verifying per-symbol
readiness against the scanner's own real buffer state and its own configured thresholds
(`min_bars_required`, `htf_sma_period` — never hardcoded/duplicated). `WatchlistDrivenQuantPreseed`
gained an `already_preseeded_symbols` parameter so its own initial pass doesn't repeat that work;
its reactive loop for tickers added after startup is completely unchanged. Fail-closed per symbol,
zero-ready reported but never fatal to startup (a policy decision left to the caller/preflight, not
this module). Verified against real yfinance data for AAPL/MSFT (`initial_preseed_report.json`) —
both reached full 120/200 bar hydration. 12 focused tests.

## C) Full-application preflight (`talonx_ops/preflight.py`)

Deliberately **not** PIV's `PIV_READY` terminology — `FULL_APP_E2E_READY`/`FULL_APP_E2E_BLOCKED`,
23 checks covering git state, no duplicate process, Redis, watchlist, every store (Quant/Core/
Dispatch/Paper), ChromaDB, Brain (hard requirement — see below), Telegram in/outbound, market-data
provider identification, pre-market/preseed capability, EOD report capability, no-real-capital
proof, and no-secrets-printed. Read-only throughout. 11 focused tests plus one real, live run saved
as evidence (`full_app_preflight.json`) — every check passed except `tracked_tree_clean` (this
task's own uncommitted work).

Caught two real things on its first live run: (1) a genuine `SyntaxError` in
`generate_eod_report.py` introduced while adding Part 10's metadata section (unbalanced list
literal), fixed immediately; (2) a false-negative from running the checker under the wrong Python
interpreter (`python` resolved to a bare 3.14 install missing `psutil`/`langchain-google-genai`,
not this project's real `py -3.12`) — corrected, documented rather than hidden.

## D) Brain hard requirement (Part 4)

`run_talonx.py`'s own "Brain degrades gracefully" production philosophy is **unchanged**. The
preflight adds a stricter, separate bar on top: `brain_operational_hard_requirement` constructs a
real `ResearchAgent` (same call `main()` already makes) and fails the whole preflight if that
raises — refusing `FULL_APP_E2E_READY` for tomorrow's validation specifically if Brain would
silently degrade. Verified operational in this environment (Gemini provider).

## E) Market-data provider / paper execution path explicitness (Parts 5/6)

`talonx_ops/provider_status.py` states plainly which provider is configured (`YFINANCE_POLLING`
here — no `POLYGON_API_KEY` set) and that `talonx_paper` is always a local simulated ledger, never
Alpaca — surfaced in startup logs, the preflight report, and (new) `runtime_metadata.json`, which
`generate_eod_report.py` now optionally reads into a new "Run metadata" section (commit SHA,
provider, execution path, run mode) — degrading to "unknown" if absent, same pattern every other
optional store in that script already uses.

## F) Cross-path comparator (Part 7)

`talonx_ops/comparator.py` — read-only, never changes a runtime decision. Reuses
`generate_eod_report.build_report()` for the full-app side rather than re-querying stores by hand.
13 stages tracked; only 4 can ever come from PIV (`quant_signal`, `paper_decision`,
`paper_execution`, `final_position_state`) since PIV has no Brain/Core/Dispatch — the rest are
reported `NOT_APPLICABLE_TO_PIV`, not silently dropped. Smoke-tested against today's real PIV
evidence: correctly reports zero `MATCH` (no full-app run has happened yet — the honest answer,
not a defect). Found and fixed a real bug during its own smoke test: the full-app loader initially
attributed hollow "evidence" to all 39 watchlist tickers just for being tracked, regardless of
actual pipeline activity — fixed to only attach a symbol when it has genuine stage data. 12
focused tests. Full contract documented in `cross_path_comparator_contract.md`.

## G) Telegram /ping precheck (Part 8)

No restoration work needed — unlike PIV (Task 66A), `run_talonx.py`'s `DispatchAgent` already
constructs `TelegramReplyListener(..., dispatch_agent=self)` internally and starts it in `.run()`
whenever Telegram is configured, so `/ping` already reports real uptime/CPU/RAM/pipeline-funnel
metrics — verified by reading the code, not built. Zero duplicate-listener risk confirmed: zero
active TalonX/PIV processes at task end.

## H) Tomorrow's start contract (Part 9)

Documented in full in `tomorrow_full_app_handoff.md` — target ~07:00 ET/12:00 UK, exact commands,
verification checklist for 07:00-09:30 ET, and explicit success criteria. **Not scheduled, not
started, by this task.**

## I) Repository/cleanup authority

Zero active TalonX/PIV processes found. One scheduled job found and removed (the previous task's
market-open cron, now targeting the wrong runtime per the objective change) — recorded in
`cleanup_inventory`-equivalent detail in `task66b_prep_summary.json`. Redis left untouched
(no ownership question — it's the shared broker, not a TalonX-owned temporary instance).

## Tests

45 new focused tests, all passing. 101 pre-existing PIV/Task66A tests re-verified unaffected. Full
regression: **2029 passed, 1 known pre-existing failure (unchanged), 1 skipped, 15 xfailed** —
exactly 45 more passing tests than the previous 1984-test baseline, matching the 45 new tests added
today with no other drift.

## Safety and integrity at task end

Zero active runners, zero scheduled TalonX jobs, zero PAPER/PIV broker open orders/positions.
Protected `talonx_quant/*` files have zero diff; ORPB/FPRC fingerprints unchanged. No alpha tuning.
No real-capital adapter introduced. No live session started. No scheduler created. PR #10 remains
draft/open/unmerged.

## Conclusion

Full-application readiness: **FULL_APP_E2E_READY** once this commit lands (the only blocker at
dirty-tree time was the tracked-tree-clean check on this task's own uncommitted work). Alpha
remains **UNPROVEN** — this is infrastructure/readiness work only. Next action: **one clean, full
end-to-end PAPER validation session using `run_talonx.py`** (see `tomorrow_full_app_handoff.md`) —
not started or scheduled by this task.
