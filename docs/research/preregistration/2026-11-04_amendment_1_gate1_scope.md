# Amendment 1 to TICKER_SCORECARD_V1 — Gate 1 scope (2026-11-04)

Approved by the owner on 2026-11-04. Made BEFORE any outcome data (VALIDATE or HOLDOUT labels) was read.

**Finding.** The full data build (panel sha256 39f4ed3d…) listed 2,293 in-sample splits: 1,932 verified adjusted, 257 for
symbols with no bars (mostly OTC ADRs), 88 on or before a symbol's first bar, 9 with no later bar, 2 with a long bar gap,
5 genuinely unadjusted. The literal rule ("every known split in the sample") can never pass because Alpaca lists splits for
symbols it holds no bars for.

**Amendment.** Gate 1 counts only splits for symbols that were in the tradable universe (DTU_V2 floor) on the last session
before or the first session on/after the ex-date. Other splits are reported as NOT_IN_UNIVERSE but not counted.
Inside the universe the gate stays strict: every split must be verified ADJUSTED; any NOT_ADJUSTED or unverifiable
split fails the gate. No symbols are dropped to make the gate pass.

**Unchanged.** All thresholds, features, segments, models, gates G1–G5 and the decision table.
