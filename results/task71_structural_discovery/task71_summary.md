# Task71 Summary — Forensic Reset + Structural Discovery

## Result: ONE candidate nominated — PRIMARY_CANDIDATE_READY_TO_FREEZE

**IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG** — see
`primary_candidate_draft.md` for the full writeup.

## Part 1 — Forensic audit (before any new outcome was computed)

Reviewed legacy Quant (Tasks 8/26/36/37), FPRC_V1, ORPB_V1, F1-F5
(Task67A/67B), and F6_FADE_V1 (Task68A/70). See `failure_forensics.{csv,md}`
for the full evidence trail. Headline finding: **the program's biggest
failure mode was promoting a candidate on statistical criteria alone,
without adjusting for how many definitions/families had already been
tried** — F6 was 1 of 18 Stage-1 definitions and failed replication with a
reversed sign; F3's apparent win was 1 isolated definition its own
researchers flagged as cherry-pick risk. No prior conclusion was
retroactively relabeled — every classification preserves the original
task's own verdict.

## Part 0/2-4 — Design lock, broadened development, universe/provider audits

Locked a 4-family, 72-cell predeclared grid **before** computing any new
outcome (`research_design_lock.json`, committed and pushed first).
Broadened DEVELOPMENT to 4 non-adjacent regime slices (2025 Q1/Q3/Q4 +
the existing 2026 summer slice) — 2,979,608 bars, all drawn from
already-contaminated 2025-01-24..2026-08-14 history, **zero clean-2024
territory touched**. Documented `CURRENT_UNIVERSE_BACKCAST_BIAS` (today's
liquid universe applied retroactively) and per-family provider
portability (AVWAP/gap: sensitive; residual-momentum/failed-break:
portable with caveat) without normalizing SIP research to IEX.

## Parts 5-20 — The four families

| Family | Result |
|---|---|
| **A — AVWAP flow-state** | Near-zero gross expectancy in all 24 cells, net negative everywhere. No edge, either direction. |
| **B — Overnight gap continuation** (not "PEAD" — no verified historical earnings-timestamp data exists, see `event_data_audit.json`) | 18/20 cells net-negative; the 2 positive cells are each adjacent to a strongly negative cell at a neighboring horizon — isolated-winner pattern, downranked. |
| **C — Idiosyncratic residual momentum** | **LONG side: positive in all 8 of its own cells**, stable sign across 3 time segments and 3 regimes, friction absorption 1.1-2.8×. SHORT side fails cleanly. |
| **D — Failed structural break** | Never clears 10bps cost in any time segment or regime, either side. |

Premarket analysis (`premarket_feature_analysis.csv`): 91-99% premarket bar
coverage (data quality is fine) but no reliable premarket-return-vs-
regular-session-return relationship found in a simple correlation check —
reported honestly, not stretched into a feature.

## Part 21 — Nomination

All 15 of the task's own pre-declared nomination criteria checked
individually against Family C LONG in `primary_candidate_draft.json` — 13
clear passes, 2 explicit, undisguised caveats: the day-clustered
(weaker, per Part 14) bootstrap CI crosses zero at every cell even though
the symbol-clustered one mostly doesn't, and no stop/risk rule is frozen
(`STOP_UNRESOLVED`, explicitly Task72's job). No second family qualifies
even as a research lead.

## Part 22 — Holdout budget

Zero 2024 outcomes computed. Task70's two consumed blocks
(2024-02-01..03-15, 2024-09-03..10-18) were not touched again. Remaining
clean 2024 territory is only **inventoried** (see `task71_summary.json`),
never accessed.

## Part 23/24 — Portability and deployment gate

`product_portability.json`: the candidate's core mechanism is price-only
and plausibly IEX-portable, but this was NOT verified against real IEX
data. Runtime worktree untouched. Nothing from Task71 goes live — per the
mandatory pipeline, Task72 must freeze + fingerprint + pre-register before
any validation, and validation must pass before replication, before any
PAPER integration.

## Tests

21 focused tests (causal feature construction, no-lookahead, direction-
sign correctness, holdout-guard, and the cluster-CI weaker-interpretation
logic — including a real bug this task found and fixed in that logic
before reporting any result) — all pass, run once before final
interpretation.

## Next

Task72 — freeze `IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG`, design/freeze a
stop rule from DEVELOPMENT data only, pre-register an 8-criterion-style
validation protocol, and lock a genuinely untouched holdout (not any part
of 2024, and not the 2025-01-24..2026-08-14 range now used as this
candidate's own development data).
