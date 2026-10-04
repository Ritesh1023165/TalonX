# EVENT_RESPONSE_MAP_V1: Gate D report (accepted by the owner, 2026-10-04)

## Run

**Run type:** the one allowed re-execution. Phase D attempt 2: scoring-only, lock revision 3.2.

| | |
|---|---|
| Fingerprint | `12a909e795986ff3abeac9ca92906a64c3387a5e3c64734f2b72031b781cb8ad` |
| Commit | sha `44112d5` |
| Network | refused (offline guard, active in the run) |
| Archive | verified against the guard audit |
| Duration | START 13:00:01Z → END 13:22:24Z |
| Task result | 0 |
| Crash / re-run | none |
| Marker | `trial_ledger.json` written last (13:22:22.886Z, after `cells.csv` and `report.md` at .837) |

**Processes after the run:** the runner logs the job's process count only on a timeout, so it was not logged here. An external check afterwards found 0 processes from the run still alive.

**Dataset hashes:**

| Dataset | sha256 |
|---|---|
| Main archive aggregate | `4f6aa4c19184afe48fd2713b20e2e28a64773434dcd86decfad183d30c449587` |
| Diagnostic archive aggregate | `6a9e6f121cd321bb7c8dad2bfca8e8650e9c55efd4ede8db365cc36c90c7018d` |
| Candidates (LF) | `a865fce26673a4fbf5df3819c1456fb100d2bfb53432af632bc8ef69e1e1f61c` |
| Candidates_r3 (LF) | `a7095779e32ad0aa3530410f5a5d238dd8a1005a873ca09bd7d9350f488502ad` |

**Trial count:** 390 cells. LONG and SHORT cells are mirrors, so this is 195 independent sign tests.

**Outputs, committed byte-exact** (sha256 of the bytes on disk):

| File | Bytes | sha256 |
|---|---|---|
| `cells.csv` | 270,357 | `bd8fd486cbc05733ed3f747c4c8aee438bfc112432075afb348ca0350196ebab` |
| `report.md` | 3,838 | `534a55c4b1670a93166afbbad6cdcfec528071a6d3d7dffe6c7cc9b3d11beace` |
| `d0_coverage.json` | 3,977 | `9025581276f181ac1ef91dae962c14300fd776ed0fae144aff9d3221357b8855` |
| `trial_ledger.json` | 880,600 | `6c987f6742075a22be6f1a4b152d3228641f523aa60e6702413ea17790833997` |
| `phase_d_runner.log` | 2,256,827 | `adb81613ac10fb48cdf6b05e3b7f34dc1a34ca142b9cf7157635ad2e5b490aba` |
| `phase_d_run.out.log` | 3,681 | `66893c4f5c6221c9bfd3c223b3dacf658677e8055194ffce7a790503bbf23fbf` |
| `phase_d_run.err.log` | 295 | `9c9b5579ae666f44319abbba77afd8fc1165eac8e5d6e1072b91d966b9b9c8ca` |

`phase_d_runner.log` is large because of a runner serialization bug (below). Its content is unedited.

**Progress-log timings:**

| Stage | Time |
|---|---|
| Load | 2 m 29 s |
| Eligibility | 1 m 38 s |
| SEC/Form 4 inputs | 1 m 20 s |
| 8-K attribution | 3 m 13 s |
| Gaps, joins and NO_EVENT | 44 s |
| Outcomes + d0 | 1 m 6 s |
| Evaluate, 390 cells (4 workers) | 7 m 16 s |
| Survivorship diagnostic | 4 m 35 s |
| **Total** | **22.4 min** |

## a) NO_EVENT calibration

**NO_EVENT SCREEN_PASS: 0 of 30 → NULL_CALIBRATION_CLEAN.** Nomination is allowed.

## b) Screen, missing exits, coverage, survivorship

**SCREEN_PASS: 21 of 390**, all labelled DISCOVERY:

| Group | Passing cells |
|---|---|
| SHORT, gap-up fade | 14 |
| SHORT, gap-down fade | 3 |
| SHORT, 8-K 2.02 | 3 |
| LONG, 8-K 5.02 H3 L3 | 1 |
| FORM4_CLUSTER baseline | 0 |
| NO_EVENT control | 0 |

The screen criteria are columns in `cells.csv`; no `screen.csv` exists in either revision.

**Missing-exit gate:** no cell exceeds 2 %. The maximum is 1.28 % (`8K_8.01|SHORT|H10|L1`).

**Integrity counts:**

| Count | Value |
|---|---|
| DATA_MISSING_ENTRY | 1,677 |
| DATA_MISSING_EXIT | 1,943 |
| BENCH_MISSING | 0 |
| BEYOND_DEV_END | 2,354 |
| SUSPECT_ADJUSTMENT | 1,551 (retained, flagged) |
| SIC-6770 symbol-days masked | 370 |

**Bar coverage:** the PIT S&P 500 has bars for 99.62 % of its members in 2019 and 99.81 % in 2020–2023. Only FBHS, STI and FI are missing.

| Bucket | Eligible symbol-days per year | Distinct symbols per year | ALL-bar present | Missing-exit rate |
|---|---|---|---|---|
| L1 | 217k–259k | 1,620–2,309 | ≥ 99.97 % | 0.07–0.17 % |
| L2 | 136k–175k | 897–1,353 | ≥ 99.97 % | 0.07–0.10 % |
| L3 | 8k–18k | 67–173 | ≥ 99.97 % | 0–0.13 % |

**Survivorship diagnostic:**
- 764 removed symbols have bars, yielding 1,222 extra events.
- The removed names are eligible on 1.4k–2.2k symbol-days per year in L1 and 0.1k–0.6k in L2.
- **EXCLUSION_DEPENDENT: 0 of 21.**

## c) Nomination (protocol: MAP_MISCALIBRATED → ZERO_PASS → NO_ELIGIBLE → NOMINATE)

**Order checks:** the map is not miscalibrated, and the result is not ZERO_PASS. All **21 passes are eligible**: each passes the screen, is not EXCLUSION_DEPENDENT, is labelled DISCOVERY and has same-sign neighbour support.

**Ranking** by LB = date-cluster CI low − bucket cost:

| Rank | Cell | LB |
|---|---|---|
| 1 | `GAP_UP_10|SHORT|H10|L1` | **+1.121 %** |
| 2 | `GAP_UP_10|SHORT|H5|L1` | +0.886 % |
| 3 | `GAP_UP_10|SHORT|H10|L2` | +0.713 % |
| 4–21 | the rest | lower |

The tie window (≥ max − 0.05 pp) holds only the top cell, so the exposure tie-break is not needed.

### NOMINEE: `GAP_UP_10|SHORT|H10|L1`

The rule: a gap-up of at least +10 %; short at the D+1 open; exit at the close 10 sessions later; ADV20 between $20M and $100M.

| Metric | Value |
|---|---|
| n | 2,695 events, 898 dates, 1,370 symbols |
| Mean sector-relative (directional) | **+2.85 %** (median +2.08 %); net of 30 bps **+2.55 %** |
| Mean raw / vs SPY | +1.54 % / +2.90 % |
| 95 % CI | **[+1.42 %, +4.23 %]** |
| Hit rate | 58.4 % |
| Dispersion (SD) | 22.1 % |
| By year | 2019 +0.41 % (n=276) · 2020 +2.08 % · 2021 +4.47 % · 2022 +1.83 % · 2023 +4.89 % (5/5 stable) |
| Without the top 1 / 3 / 5 | +2.82 % / +2.76 % / +2.70 % |
| Missing exits | 0.30 % (8). Bounds: +2.54 % (short −100 %) / +2.84 % (0 %), both still passing |
| Excluding suspect adjustments (24) | +2.85 % |
| With the R1-removed symbols added | +2.94 %, still passing |
| Mirror LONG cell | does not pass |

### Exposure (ledger §5)

The **GAP_UP family is heavily exposed**:
- **LARGE_GAP_REVERSION_V1** tested the same trigger (≥ +10 % gap) in the same direction (fade), with an intraday entry at +30 min, on **2024-01..2026-09**. It was **UNSUPPORTED** (gross +0.23 %, net −1.12 %).
- The **Sep 28–30 2026 forensics** looked at gap-driven candidates.
- **Task 97** (catalyst × gap, discovery 2020–23, **overlapping the development window**) found a mean-reverting response.
- **Task 95B** may also have touched gaps.
- The result is consistent with the mean-reversion findings of 95D, 97 and 95G.

### Caveats for the pre-registration

- The trade shorts small and mid caps straight after a +10 % spike and holds for 10 sessions. **The 30 bps cost excludes borrow fees, locate availability and squeeze risk.**
- The universe is not survivorship-free.
- **Discovery multiplicity:** 21 / 195 independent tests passed, versus 0 / 30 NO_EVENT cells. The passes are coherent, clustered in one family.

**Next (protocol):** freeze and pre-register this single nominee in a separate task **before any 2024 data is read**. 2024 stays guard-locked until then.

**Runner logging gaps** (runner only; they do not affect results):
1. The END line serialized `report_first_line` as a whole PowerShell object, which inflates `phase_d_runner.log`.
2. The job's process count is not logged on normal completion.
