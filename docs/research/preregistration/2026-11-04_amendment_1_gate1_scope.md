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

---

# Amendment 3 — Gate 1 counts plain splits only (2026-11-04)

Approved by the owner on 2026-11-04, before any outcome data was read.

**Finding.** Under Amendment 2, three in-universe items still failed: TT (ratio 1.289, factor change 1.1375), HON (ratio 0.5,
factor change 0.954) and QGEN (ratio 0.97, factor change 0.9992). They look like spin-off, merger or immaterial events that
Alpaca's splits feed reports as splits, not plain splits.

**Amendment.** Gate 1 counts only plain splits: ratio n:m with the smaller side <= 3, the larger side <= 100 (within 1%), and a
price effect of at least 10%. Other events are reported as NON_SPLIT_EVENT with their details, not counted. Plain splits that
were not adjusted still fail the gate. All other rules unchanged.

**Implementation note (same day).** The first implementation of Amendment 3 capped the larger side at 100 and hid
168 events that were in fact correctly adjusted (including legitimate 1:200 reverse splits). Corrected before any outcome
data was read: the larger side cap is 100,000, and an event that verifies as ADJUSTED is always counted as verified.
NON_SPLIT_EVENT applies only to events that fail verification and are not plain splits.

---

# Amendment 4 — Named exclusion: HON (2026-11-04)

Approved by the owner on 2026-11-04, before any outcome data was read.

**Finding.** After Amendment 3, one in-universe item still failed Gate 1: HON, ex-date 2026-06-29, listed ratio 0.5, adj/raw
factor change 0.954. It is a spin-off of Honeywell Aerospace bundled with a reverse stock split, not a plain split.

**Amendment.** HON is excluded from the study panel for every segment. It is recorded in `talonx_scorecard.config.EXCLUDED_SYMBOLS`
and in the gate report. No other symbol is excluded. Any future exclusion needs its own dated amendment.

---

# Amendment 5 — Universe capped at the 1,000 most liquid names (2026-11-04)

Approved by the owner on 2026-11-04, before any outcome data was read.

**Reason.** The floor (close >= $5, 20-session average dollar volume >= $20M) yields about 1,560 names a day. The owner wants about
1,000 for tradability and run cost.

**Amendment.** Each day the universe is the `UNIVERSE_TOP_N = 1000` names with the highest 20-session average dollar volume among
those that pass the floor, using only data known at that day's close (no look-ahead). Ties break by column order. The floor itself is
unchanged. Decile views therefore hold about 100 names. Amendments 1-3 (Gate 1 scope) now apply to this smaller universe. All
gate thresholds, features, segments, models and the decision table are unchanged.

**Known cost.** Fewer names make each ranking test noisier (about 25% noisier than at 1,560), so a small real edge is harder to detect.

---

# Amendment 6 — V1 runs without F11 (2026-11-04)

Approved by the owner on 2026-11-04, before any outcome data was read.

**Reason.** F11 (risk-factor change) needs the text of every 10-K and 10-Q for about 2,500 companies over 8 years. Filing text is
not in the SEC bulk files, so building it would break the "SEC bulk files only" rule and need thousands of per-filing requests.

**Amendment.** V1 runs with F11 missing for every name. Under the locked rule a missing feature takes the neutral value 0.5, a constant
that does not change any ranking or the ridge fit, so V1 is equivalent to an 11-feature model. The report states this. F11 may be added
later only as a separate pre-registered V1.1.

**Also (data note).** SEC moved its newest insider data sets (2026 Q2 onward) to a different URL path; the downloader now tries both.
Insider data is still blank after the last published quarter (2026 Q3 is published; Q4 is not).
