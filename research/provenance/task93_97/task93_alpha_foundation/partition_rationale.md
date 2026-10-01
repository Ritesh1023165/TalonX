# TASK 93 — Phase 4: Research Partition Rationale

Machine-readable: `research_partitions.json`. Frozen 2026-09-02 at commit
`4b0e5dfa2415afe1dbf423c63c9cc479264106fa`, dataset fingerprint
`796893860a2733b3ffd689c81f2ce68adf96a6096cfcbbc942d7924a34e37474`.

## The partitions

```
2025-01-24 ─────────────── 2025-08-14 │ 2025-08-15 ──── 2026-02-28 │ 2026-03-01 ──── 2026-08-14
        DISCOVERY (Segment A)          │  VALIDATION (Seg B)        │   HOLDOUT (Seg B)
   35 symbols · 2,565,682 bars         │  10 sym · 988,278 bars     │  10 sym · 914,766 bars
   broad universe, 2025 H1 regime      │  mega-cap, 2025 H2         │  mega-cap, 2026 H1
```

| Partition | Dates | Segment | Symbols | Bars | Purpose |
|---|---|---|---|---|---|
| **discovery** | 2025-01-24 → 2025-08-14 | A (broad) | 35 | 2,565,682 | The **only** partition Task 94 hypothesis discovery / feature exploration may use. Broadest universe, so a discovered effect has a chance of being cross-sectional rather than one-symbol. |
| **validation** | 2025-08-15 → 2026-02-28 | B (deep-10) | 10 | 988,278 | Confirm a discovery-period hypothesis on **later, unseen** time on the mega-cap subset before the holdout is spent. |
| **holdout** | 2026-03-01 → 2026-08-14 | B (deep-10) | 10 | 914,766 | **Untouched by Task 94 discovery.** Touched at most once, only after a hypothesis clears discovery + validation, and never re-used. |

Actual first/last bars differ slightly from the nominal boundaries (weekends/holidays): validation
starts 2025-08-15 08:00 UTC, holdout starts 2026-03-02 09:00 UTC — no overlap.

## Why chronological (not random / not k-fold)

Intraday trading signals are strongly autocorrelated within a day and a regime. A random or k-fold
split leaks near-future information into the training set (adjacent minutes / same session on both
sides). Chronological separation with a hard wall is the only split that honestly answers "does an
effect found in early data persist in later, genuinely unseen data." This matches every prior TalonX
protocol (Task 22, 52/53, 56, 59, 74S all used chronological windows with causal pre-roll).

## Why these specific boundaries

1. **Discovery = all of Segment A.** It is the only stretch with the full 35-symbol breadth. Using it
   whole for discovery maximises cross-sectional signal and leaves *both* later partitions on the
   10-symbol deep set, which is the only data that extends past 2025-08-14 anyway.
2. **The 2025-08-14 / 2025-08-15 wall is a natural seam** — it is exactly where the 35-symbol packages
   (task63⧺task61r) end and the 10-symbol task7b package begins. No symbol straddles it with a gap.
3. **Validation / holdout split at 2026-02-28** gives ~6.5 months validation and ~5.5 months holdout —
   both large enough (~900k–990k bars, 10 symbols) to produce a non-trivial trade population *if the
   strategy traded*, and each spanning a distinct market phase (2025 H2 vs 2026 H1).
4. **Holdout is the most recent data** — the hardest, most decision-relevant test, and the least
   likely to have been implicitly seen through prior tasks' summaries.

## Regime coverage (honest accounting)

- **Discovery** — 2025 H1: a rally into February, the April tariff shock and drawdown, then recovery.
  One broad macro arc; both trend and mean-reverting sub-phases; no sustained bear.
- **Validation** — 2025 H2: post-summer chop + Q3/Q4 earnings season + year-end.
- **Holdout** — 2026 H1: distinct from both above.
- **Not covered anywhere:** a 2020/2022-style sustained bear or volatility crisis. No local data exists
  for it. Any Task 93/94 verdict is explicitly conditioned on 2025-01 → 2026-08 conditions.

## Secondary untouched holdout (different symbols)

`task54_extended_windows`, `task56_holdout`, `task46_validation_windows`, `task37_universe_windows` —
25-symbol packages, scattered 2025-09 → 2026-07 windows. **Never** used in Task 94 discovery. Available
as an independent replication set on the *other* 25 names if a hypothesis clears the primary holdout.

## Freeze commitment

These boundaries are **frozen**. Per the task: if Task 94's results are poor, that is a finding — it is
**not** grounds to move a boundary, widen discovery, shrink holdout, or re-partition. Any change
requires a new gatekeeper-authorised task that records the reason.
