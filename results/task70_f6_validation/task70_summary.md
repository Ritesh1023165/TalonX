# Task70 Summary — F6_FADE_V1 Historical Validation

## Result: F6_ALPHA_REJECTED

The frozen F6_FADE_V1 candidate does **not** have a credible, cost-adjusted
profitable edge outside its development data. `VALIDATION_PASS` was
achieved narrowly, but `REPLICATION_FAIL` — on a broader, more powerful
sample, with the gross edge's sign reversed and a bootstrap 95% CI entirely
negative — is the decisive, disqualifying result. Per the task's own
non-negotiable instruction, this is reported as a rejection, not rescued,
re-litigated, or explained away.

## What was verified before anything else (Part 1)

- Research worktree: `research/talonx-alpha-phenomenon-discovery`,
  HEAD `d9dd42123790ad73ab9cc93cef5bafc351737b72`, tree clean.
- F6 fingerprint independently recomputed from
  `results/task68_f6_freeze/f6_fade_v1_spec.json` and matched exactly:
  `6beb8eebe50053aae27cab90226534b5d4392c46bd6e9c094873f7ad37466084`.
- Frozen implementation unchanged since Task68A (HEAD *is* the freeze
  commit; tree clean — trivially confirmed).

## Historical exposure audit (Part 2)

Built on Task67A's own pre-F6, ledger-wide exposure audit. Resolved two
loose ends it left open (both turned out to be non-issues: pure calendar-
arithmetic references and data-quality-only documentation examples, never
a real strategy outcome). **Conclusion: calendar year 2024 is
EXPOSED_DATA_ONLY at worst — the defensible unseen window.** Everything
2025-01-24 onward is genuinely outcome-contaminated by prior research; the
pre-existing forward-reserved plan (Aug–Oct 2026) cannot be materialized
because it hasn't traded yet. See `historical_exposure_audit.{json,md}`.

## Holdout lock (Part 3) — locked before any F6 outcome existed

`VALIDATION = 2024-02-01..2024-03-15`, `REPLICATION = 2024-09-03..2024-10-18`,
committed and pushed (`TASK70 HOLDOUT SELECTION LOCK`) before any
`evaluate()` call touched real price data. Selection used only pre-outcome
factors: cleanliness, live-confirmed data availability (read-only API
checks across all 35 symbols), adequate session count, temporal separation,
calendar diversity. See `holdout_selection_lock.{json,md}`.

## Data materialization (Part 4)

Both windows downloaded via the existing canonical mechanism (Alpaca,
account-default feed confirmed SIP), all 35 universe symbols, 35/35 FULL
each, zero duplicate/out-of-order/NaN/Inf/invalid-OHLC/negative-volume/
future-timestamp rows. No interpolation, no forward-fill, no synthetic
bars. See `validation_data_quality.json` / `replication_data_quality.json`.

## Validation (Parts 5-7): VALIDATION_PASS (narrow)

43 trades / 20 symbols / 10 days. Net expectancy @10bps = **+0.338%**,
gross expectancy = +0.438% (fade-consistent direction), PF=2.05, bootstrap
CI [−0.071%, +0.694%] (clustered by symbol, Task68A's pre-registered
method). All 8 pre-registered pass criteria from
`results/task68_f6_freeze/validation_protocol.json` are satisfied — none
loosened after seeing the numbers. Two honesty notes: `session_coverage`
sits exactly at the 10-day minimum floor, and the bootstrap CI lower bound,
while inside the pre-registered floor, sits close to zero. See
`validation_summary.md`.

## Replication (Part 8): REPLICATION_FAIL

182 trades / 33 symbols / 34 days — a **broader** sample than validation.
Net expectancy @10bps = **−0.224%**, gross expectancy = **−0.124%**
(direction reversed vs. both development and validation), PF=0.56,
negative at every cost level including 0bps, bootstrap CI **entirely
negative** ([−0.319%, −0.123%]), not concentrated (top1_symbol=16.2%,
top1_day=20.4%), removing the best 3 winners makes it worse. Zero causal/
integrity violations; data clean. No rescue is available in this evidence.
See `replication_summary.md`.

## Development vs. validation vs. replication (Part 9)

| | Development | Validation | Replication |
|---|---|---|---|
| Net expectancy @10bps | −0.040% | **+0.338%** | **−0.224%** |
| Gross expectancy | +0.060% | +0.438% | **−0.124%** |
| Trades / symbols / days | 735/35/63 | 43/20/10 | 182/33/34 |
| Profitable side | short | long | neither |

The profitable side of the trade **flips** across all three independent
periods — itself evidence against a stable structural effect, not just an
unlucky replication window. See `profitability_evidence_matrix.csv` /
`profitability_evidence_summary.{json,md}`.

## Final classification (Part 10): F6_ALPHA_REJECTED

Per the task's own definition, `F6_ALPHA_CREDIBLE` would mean *only* that
historical evidence justifies live PAPER testing — not that it's
guaranteed profitable. That bar is not met: two of three independent
periods are net-negative, and the one larger holdout test (replication)
decisively and broadly contradicts the hypothesis. **F6_FADE_V1 is
rejected as a research candidate.** No further time is spent trying to
rescue it.

## Production gap (Part 11) — recorded regardless of outcome

`F6_FADE_V1` has **no stop_rule** (frozen as `NONE`). This is now moot for
F6 itself (rejected), but the gap is recorded per instruction: any future
fade-family candidate intended for production needs a defensibly-derived
stop/risk rule (bias + entry + stop + exit/horizon), developed and frozen
using **DEVELOPMENT data only** — never derived from validation/replication
outcomes, and never derived from F6's own now-rejected results.

## Live PAPER plan (Part 12)

**F6 failed — do not deploy it.** Per the task's own instruction, work
returns immediately to DEVELOPMENT-phase phenomenon discovery for a new
candidate. Failure analysis (the long/short flip across periods, the
gross-direction reversal in replication) is used diagnostically only —
none of it is used to tune F6 itself on the holdout data.

## Runtime warmup note (Part 13) — carried forward, not acted on

Runtime warmup remains YFINANCE (17/35 ready); Task69Q's verified
`ALPACA_HISTORICAL` (feed=iex) prototype showed 650+ bars on previously-
failing symbols. This remains a separate, recommended runtime task — not
mixed into this task, and the runtime worktree was not touched.

## 10-day plan (Part 14) — F6-failed branch

- **Day 1** (this task): F6 historical alpha decision — REJECTED.
- **Days 2-4**: new DEVELOPMENT-only phenomenon/candidate discovery
  (Task67-style family screening), informed diagnostically by F6's
  failure mode (directional instability across periods) but not
  re-litigating F6 itself.
- **Day 4-5**: freeze the strongest surviving candidate (same
  pre-registration discipline as F6: frozen spec, frozen fingerprint,
  pre-registered pass_logic, before any holdout is touched).
- **Day 5-6**: historical validation (same protocol as this task).
- **Remaining days**: PAPER evidence collection only if a candidate
  survives validation+replication.

## Tests (focused, run once, per Part 5)

`tests/test_task68_f6_fade_v1.py`, `test_task67a_family06_opening_later.py`,
`test_task67a_data_guard.py`, `test_task67a_research_stats.py`,
`test_task67a_screening_framework.py` — **89 passed, 0 failed.**

## Integrity

F6 changed: **NO**. Runtime changed: **NO**. Validation outcome inspected
before the holdout lock: **NO**. Replication run before validation passed:
**NO**. Synthetic data: **NO**. Real capital: **NO**.
