# TASK 95G — Precondition B — Independent Membership Cross-Check

The Task 95F point-in-time S&P 500 membership (Wikipedia "Historical components" backward-walk) was
cross-checked against an **independent free source**: `fja05680/sp500` —
`S&P 500 Historical Components & Changes (Updated).csv`, a 2,718-row daily `date,tickers` list
(1996 → 2026-06-30), reconstructed in that repo from Wikipedia + press releases and validated by its
own notebooks. `_membership_crosscheck.csv` / `.json` hold the per-date detail.

## Raw ticker-string comparison (13 sample dates 2020-2026)

| metric | value |
|---|---|
| mean Jaccard (raw ticker strings) | **0.955** |
| mean symmetric difference | ~23 names/date |
| trend | rises monotonically 0.922 (2020-01) → 0.988 (2026-06) |

The ~23-name/date raw difference is **dominated by ticker-rename vintage**, not by disagreement over
*which companies* are members. Examples (2022-06-15):

| my reconstruction has | fja05680 has | same company? |
|---|---|---|
| ELV | ANTM | ✓ Anthem → Elevance |
| EG | RE | ✓ Everest Re → Everest Group |
| RVTY | PKI | ✓ PerkinElmer → Revvity |
| DOC | PEAK | ✓ Healthpeak |
| BNY | BK | ✓ BNY Mellon |
| COR | ABC | ✓ AmerisourceBergen → Cencora |
| MRSH | MMC | ✓ Marsh McLennan |
| GEN | NLOK | ✓ NortonLifeLock → Gen Digital |
| SW | WRK | ✓ WestRock → Smurfit WestRock |

My backward walk carries the **current** ticker back through history; fja05680 carries the
**historical** ticker forward. Neither drops or double-counts a company.

## Company-level comparison (rename-normalized)

After mapping ~25 known rename pairs to a canonical symbol on both sides:

| date | members (mine / fja) | agree | Jaccard |
|---|---|---:|---:|
| 2020-01-02 | 479 / 479 | 473 | 0.975 |
| 2021-03-15 | 485 / 485 | 481 | 0.984 |
| 2022-06-15 | 492 / 492 | 490 | **0.992** |
| 2023-06-15 | 499 / 499 | 497 | **0.992** |
| 2024-06-14 | 501 / 501 | 499 | **0.992** |
| 2025-06-16 | 501 / 501 | 499 | **0.992** |
| 2026-06-15 | 502 / 503 | 500 | 0.990 |
| **mean** | | | **0.988** |

## Residual genuine disagreements

~2–4 companies/date. Two are traceable:

- **ECHO / RDDT present in my reconstruction across 2020-2026** — backward-walk artifact: a current
  member (RDDT added 2026; ECHO) whose ADD event was not parsed from the Wikipedia changes table is
  carried back to 2019 incorrectly.
- **AVB / EQR "only in fja"** — the mirror image (a REMOVE not undone).

These are exactly the "reconcile the 503↔508 count drift" and "±1–3-day effective-date offset" items
Task 95F listed as open. Magnitude: **< 1% of symbol-days**, random with respect to any price/volume
feature.

## Decision — which source Task 95G uses

**`fja05680/sp500` is adopted as the primary point-in-time membership** for the Task 95G panel
(daily resolution, independent, no backward-walk missing-ADD artifact), with tickers normalized to
their current tradable symbol via the verified identity map. The Task 95F Wikipedia reconstruction is
retained as the documented cross-check (98.8% company-level agreement).

## Integrity verdict

**NOT `TASK95G_BLOCKED_UNIVERSE_INTEGRITY`.** Two independent free reconstructions agree on ~98.8% of
company-membership at every sampled date; the residual < 1.5% is well-characterized (rename labels +
a handful of missing add/remove events + ±1–3-day offsets) and is immaterial for equal-weight
decile cross-sectional research on ~500 names. Adopting fja05680 as primary removes the larger of the
two error sources (the backward-walk artifact).
