# TASK 95G — Sector Robustness (Diagnostic)

Diagnostic only — no sector-neutral portfolio construction. GICS sector is available (causally, as a
slow-moving attribute) from the Wikipedia current-constituent table for present members; for
historically-removed names it is approximate. So this is a **coarse** read.

## Is any apparent effect just "technology outran the index"?

The question is moot for a *positive* interpretation: **no family has a positive pooled
`top_decile_excess`** on the broad universe. But the sector composition of the buckets is worth
noting because it explains the contrast with Task 95E:

- Task 95E's 35-name universe was ~60% technology, and its `rel_10d` top-20% bucket (7 names) was
  effectively "the hottest 2–3 mega-cap tech names" — a concentrated sector/dispersion bet that
  happened to keep winning in 2020/2023.
- Task 95G's ~500-name universe is full-GICS. The top decile by relative strength (~50 names) each
  date spans many sectors and rotates; it is **not** a persistent tech bet. Once the bucket is
  sector-diversified and 7× larger, the "momentum" it was expressing collapses into the broad
  short-term reversal (`momentum_replication.md`).

## Contribution check

- Best single symbol ≤ 1.5% of the (negative) top-decile excess-R; top-3 ≤ 4.3%. The effect is
  diffuse across names and, by extension, sectors — it is not one sector driving it.
- The reversal is present in the removed-constituent subset as strongly as in current members
  (`survivorship_control.md`), and removed names span sectors (energy, financials, healthcare,
  industrials over-represented in the 2020-2024 departures) — so it is not a single-sector artifact.

## Verdict

No sector-concentration rescue and no sector-concentration artifact. The broad-universe negative is
diffuse across sectors. (A full sector-neutralised study is not warranted — there is no candidate to
neutralise.)
