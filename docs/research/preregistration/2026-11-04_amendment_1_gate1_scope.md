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

---

# Amendment 2 — Gate 1 verification method (2026-11-04)

Approved by the owner on 2026-11-04, before any outcome data was read.

**Finding.** After Amendment 1 only two in-universe splits failed: OUT (ex 2025-01-17, ratio 0.976) and TAOP (ex 2020-07-30,
ratio 0.1667). The adjusted/raw price factor stepped by exactly the split ratio for both (0.9760 and 0.1667), so Alpaca
had adjusted them. The price-return test misread a tiny ratio (OUT) and a genuine ~4x price spike (TAOP).

**Amendment.** Gate 1 verifies a split by the change in adjusted/raw close across the ex-date: ADJUSTED if the factor change
is closer to the split ratio than to 1 and within 0.05 in log terms of the ratio. Scope (Amendment 1) and strictness are
unchanged: any in-universe split that is NOT_ADJUSTED or unverifiable fails the gate.
