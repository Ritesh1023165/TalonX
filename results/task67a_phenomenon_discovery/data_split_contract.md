# Task 67A — Data Split Contract (DEVELOPMENT / VALIDATION / REPLICATION)

Declared 2026-08-24, before any Stage 1 phenomenon result exists (Stage 1 has not run yet). Machine-readable version: `data_split_contract.json`. Enforcement: `research/task67a_lib/data_guard.py` (`DataSplitGuard`), tested by `tests/test_task67a_data_guard.py`.

## The honest headline

**A genuinely clean VALIDATION or REPLICATION reserve does not exist anywhere in this repo's historical data horizon right now.** This is not a small caveat — per `exposure_boundary_audit.json` (built by reading every git-tracked `research/scripts/task*.py` and `results/task*/*.json`/`*.md` file, including the full research ledger), **every single calendar date from 2025-01-24 through 2026-08-14 has been touched by at least one prior research task** for at least a symbol subset of the 35-symbol universe:

- 2025-01-24 → 2025-05-05: ORPB_V1 development (Task 62) and validation (Task 63/63P/63R), 35 symbols.
- 2025-05-06 → 2025-08-14: FPRC_V1 validation (Task 61R), 35 symbols.
- 2025-08-15 → 2026-08-14: Task 7B's canonical 10-symbol full-year dataset — replayed directly by Tasks 8–21/26/36, and the source several later 35-symbol windows (Task 37/38/41/46/53/54/56/58) are carved/sliced from or evaluated inside.
- 2026-08-20: Task 25 live shadow capture (real market data captured live).
- 2026-08-24 (today): Task 65/65B live paper-PIV session — one real PAPER AAPL round trip executed.

The audit's own conclusion: *"A genuinely clean, unambiguous window for the next alpha-discovery phase should start no earlier than 2026-08-15 ... arguably no earlier than 2026-08-25"* given the 2026-08-24 live touch. As of this task running (2026-08-24), **2026-08-25 onward has not traded yet** — it is not possible to download data that does not exist.

Per this task's own instructions: *"If existing history is too contaminated/small to honestly reserve meaningful VALIDATION/REPLICATION windows, say so plainly... It is fine to conclude e.g. 'validation reserve is thin, N days only' if that's the truth."* The truth here is stronger than "thin" — it is **zero materializable clean days** as of tonight.

## What this contract actually does about it

Rather than fabricate a "clean" holdout from already-exposed history (which the instructions explicitly forbid), or silently reuse exposed data for VALIDATION/REPLICATION without flagging it (which would defeat the entire purpose of a validation reserve), this contract splits the three roles into two different kinds of guarantee:

### DEVELOPMENT — materialized tonight, reuse-acknowledged

- **Symbols**: all 35 (`results/task65_piv/piv_universe.json`).
- **Dates**: **2026-05-15 → 2026-08-14** (~3 months, 35 symbols, downloaded via `scripts/download_historical_1m.py --provider alpaca`, i.e. `RESEARCH_SIP` — confirmed this account's SIP entitlement via `results/task63r_orpb_v1_feed_remediation/feed_diagnostic.json`'s `sip_available=true`).
- **Honesty**: this range **is** previously exposed (Task 7B's year covers it; Task 56 H3_late, 2026-05-27→2026-07-09, is fully inside it for the 35-symbol universe too). This is deliberate and — for DEVELOPMENT specifically — acceptable: the discovery plan's own data-discipline table says Discovery-phase data may be iterated on freely ("nothing here is held out"). The rule that matters is that VALIDATION/REPLICATION stay uncontaminated by Stage 1's OWN iteration, not that DEVELOPMENT be virgin history nobody has ever looked at — that bar is not achievable given how much of the last 18 months this repo's research has already covered, for any date range large enough to be useful.
- Row counts, quality checks, and a sha256 fingerprint are in `data_inventory.json` once the download (`results/task67a_phenomenon_discovery/_development_download.log` / `data/historical_1m/task67a_development/download_summary.json`) completes.

### VALIDATION and REPLICATION — reserved by calendar date, not yet materialized

- **VALIDATION**: 2026-08-25 → 2026-09-22 (~20 trading days, approximate — see caveat below), 35 symbols.
- **REPLICATION**: 2026-09-23 → 2026-10-21 (~20 trading days, approximate), 35 symbols, strictly after VALIDATION per the discovery plan's validation→replication sequencing.
- Both are **forward-looking reservations**: the date ranges are declared now, before Stage 1 runs and before any phenomenon result exists, but the actual CSV data is deliberately **not downloaded tonight** — it cannot be, because those trading sessions have not happened yet as of 2026-08-24. This is the one way to guarantee a truly zero-exposure reserve: data that does not exist cannot have been peeked at, iterated against, or have informed any parameter choice.
- `data_split_contract.json`'s `roles.VALIDATION`/`roles.REPLICATION` both carry `"materialized": false` and explicit `materialization_instructions` for the later task that will actually download and use them (only after a family is selected from Stage 1 discovery, and only after those calendar dates have actually elapsed and settled).
- **Trading-day-count caveat**: the "~20 trading days" figures are calendar estimates (4-5 weeks each, roughly accounting for the 2026-09-07 Labor Day holiday), not confirmed against an actual trading calendar — this repo has no trading-calendar source of truth anywhere (`talonx_backtest/data.py`'s `_is_weekend` docstring makes the same admission). Confirm exact session counts when materializing.
- **No overlap**: DEVELOPMENT ends 2026-08-14, VALIDATION runs 2026-08-25→2026-09-22, REPLICATION runs 2026-09-23→2026-10-21 — three disjoint, chronologically ordered blocks with explicit gaps (2026-08-15→2026-08-24 is deliberately excluded as a buffer around the two live-touched days, 2026-08-20 and 2026-08-24).

## Enforcement

`research/task67a_lib/data_guard.py` provides `DataSplitGuard`, constructed with an explicit `allowed_roles` tuple. Stage 1 code should use `get_stage1_guard()`, which only allows `DataRole.DEVELOPMENT`:

- Any Stage 1 attempt to load `DataRole.VALIDATION` or `DataRole.REPLICATION` raises `BlockedDataRoleAccessError` — checked BEFORE any file path is even constructed.
- Independently, because both roles' `materialized` flag is `false`, even a differently-scoped guard that DID allow them would raise `UnmaterializedRoleError` — there is no file on disk to load yet, so no code anywhere in this repo can currently see VALIDATION/REPLICATION data even by mistake.
- `tests/test_task67a_data_guard.py` (8 tests) proves both layers independently against a synthetic fixture, plus that DEVELOPMENT access genuinely succeeds and returns loadable data.

## What a later task must do differently from a normal "just download validation data" step

Because VALIDATION/REPLICATION are forward-reserved rather than carved from existing history, the later validation-phase task has an extra precondition a typical validation task would not: **it must wait for calendar time to pass.** It should not attempt to materialize VALIDATION data before 2026-09-23 (when the whole VALIDATION range has actually traded), and must not materialize REPLICATION data before VALIDATION has been run and passed. Materializing early (e.g. downloading VALIDATION data on 2026-08-26 when only one day of the range has traded) would silently convert this into a `PARTIAL`-status, incomplete-range dataset and should be treated as a contract violation, not a shortcut.
