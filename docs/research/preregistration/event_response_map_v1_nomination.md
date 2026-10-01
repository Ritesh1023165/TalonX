# EVENT_RESPONSE_MAP_V1: nomination protocol and exposure ledger

**Committed before Phase D.** No price data for this program existed at commit time.

This protocol governs how, and whether, ONE hypothesis may leave the event-response map. It changes nothing in the design lock: the screen, metrics and data rules stay those of lock revision 3 (fingerprint `94013b3e…`, commit `ed16b69`). The map is discovery only, and nothing it produces is validated.

## 1. Decision order (applied once, at Gate D, to `trial_ledger.json`)

The steps run in this order. The first one that applies ends the protocol.

1. **MAP_MISCALIBRATED.** At least one NO_EVENT cell is SCREEN_PASS (lock R2). Nothing is nominated until the control failure is explained. The explanation is a separate task, and this protocol does not resume on its own.
2. **ZERO_PASS.** No cell is SCREEN_PASS. **This is a valid, final result.**
3. **NO_ELIGIBLE_NOMINEE.** SCREEN_PASS cells exist, but none satisfies §2. This is also a valid, final result.
4. **NOMINATE.** Exactly one cell is chosen by §3.

The screen is **never loosened** after outcomes exist. That covers thresholds, n, the CI level, costs, the cell grid, the event definitions and the universe. A result of ZERO_PASS or NO_ELIGIBLE_NOMINEE is not followed by a "relaxed" map.

## 2. Eligibility (every condition must hold)

- The cell is SCREEN_PASS under the locked screen, with all seven criteria including R3's missing-exit rate ≤ 2 %.
- The cell is **not EXCLUSION_DEPENDENT** under the R1-FIX c survivorship diagnostic. A cell that was not checked because the diagnostic archive is missing is **not** eligible.
- The cell's label is DISCOVERY. FORM4_CLUSTER (known unsupported baseline) and NO_EVENT (control) are never eligible.
- **Neighbour support.** At least one **neighbour cell** has the same strict sign of its mean directional sector-relative gross return and n ≥ 1. A neighbour has the same event family, the same direction and the same liquidity bucket, and differs in exactly one of two ways:
  - **Adjacent horizon:** H0↔H1↔H3↔H5↔H10, one step.
  - **Adjacent threshold:** within the same gap family, GAP_UP 3↔5↔10 or GAP_DOWN 3↔5↔10, one step.

  Each 8-K item is its own family, so 8-K cells have horizon neighbours only. A neighbour does not need to pass the screen.

## 3. Ranking (at most ONE nominee)

1. For each eligible cell, compute **LB = CI low of the date-cluster bootstrap on directional sector-relative gross − bucket cost**. This is the lower bound on **net** (L1 30 bps, L2 20 bps, L3 12 bps).
2. The candidate set **T** is every eligible cell with LB ≥ max(LB) − **0.05 percentage points (0.0005)**.
3. If T has more than one cell, the **less-exposed family** is preferred, using the exposure order in §5. Remaining ties go to the higher LB, and then to the **larger n**.
4. Exactly one cell is nominated. Every other eligible cell is listed in the Gate D report with its LB and exposure, and is **not** carried forward.

## 4. After nomination

- The nominee's **prior researcher exposure** (§5) is disclosed in the Gate D report and in its pre-registration.
- The nominee is then **frozen and pre-registered in a separate task, before any 2024 data is read.** The freeze covers the exact event definition, horizon, direction, bucket, costs and gates. The 2024 year stays locked by this program's guard until that pre-registration is committed and pushed.
- The nominee is a hypothesis, not a strategy. No paper or live deployment follows from the map itself.

## 5. Exposure ledger (prior researcher exposure by event family × period)

"Overlaps development" means the prior work looked at returns inside 2019-01-02 to 2023-12-29.

| # | Prior work | Event family exposed | Horizon / entry | Period | Overlaps development? |
|---|---|---|---|---|---|
| 1 | LARGE_GAP_REVERSION_V1 (prereg `7b06ff3`, result `86f7375`) | GAP_UP (≥ +10 % at the open) | intraday, short reference +30 min | 2024-01 to 2026-09 | no |
| 2 | V2 validation (Tasks 107/112R/115-116, checkpoint 2 `92cd03e`) | FORM4_CLUSTER (≥ 2 insider code-P) | +10 sessions (+5/+15 telemetry) | 2019 to 2026 | **yes** |
| 3 | Sep 28–30 2026 forensics | GAP_UP / GAP_DOWN (gap-driven live candidates) | intraday / live session | 2026 | no |
| 4 | Task 95D earnings alpha (35 names) | 8K_2.02 | reaction continuation, 1–5 days | 2020 to 2026 | **yes** |
| 5 | Task 97 catalyst displacement (35 names) | 8-K catalyst × GAP_UP / GAP_DOWN (+RVOL) | 09:35 entry, up to +3 days | discovery 2020 to 2023 | **yes** |
| 6 | Task 95I filing events (35 names) | 8-K items (taxonomy and co-occurrence), Form 4 family (n=15) | 1–5 days | 2020 to 2026 | **yes** |
| 7 | Task 95B swing study (35 names) | price/volume features at 1–5 days; gap features not itemized, so treated as **possible** GAP exposure | 1–5 days | 2020 to 2026 | yes (possible) |

Entries 1–3 were named by the owner. Entries 4–7 come from the research record and are added for completeness. Their exact periods are as stated in each task's record.

**Exposure order used in §3**, least exposed first:
- (a) No exposure entry overlaps development, before any that does.
- (b) Within (a), fewer entries.

Under the ledger above:

| Family | Overlapping entries | Total entries |
|---|---|---|
| 8-K items 1.01, 5.02, 7.01, 8.01 | 2 (95I, 97) | 2 |
| 8K_2.02 | 3 (95D, 95I, 97) | 3 |
| GAP_UP | 2 (97, 95B possible) | 4 (with 1 and 3) |
| GAP_DOWN | 2 (97, 95B possible) | 3 (with 3) |
| FORM4_CLUSTER | not eligible | — |

**Order: 8-K 1.01/5.02/7.01/8.01 < GAP_DOWN < GAP_UP < 8K_2.02.** GAP_DOWN and GAP_UP both have two overlapping entries, so (b) decides between them: GAP_DOWN has three entries in total, GAP_UP four, and 8K_2.02 has three overlapping entries.

## 6. Restart and re-execution rules (Phase D)

- **Download (D1).** The locked downloader (`data.py`, fingerprinted) is **not** symbol-resumable. On a restart it re-requests every batch and rewrites the manifest. Changing that would change the fingerprint, and the owner ruled out a re-lock. So the runner (`run_phase_d.ps1`, not fingerprinted) retries a failed download **once, from scratch**:
  - the partial Alpaca archives are moved aside to `_failed_download_<UTC>/` and never loaded;
  - the SEC archive is reused, because it is file-level cached by design.

  A full single-pass archive also keeps all-adjusted prices from a single download date.
- **Scoring (D2).** In the locked code, the one-shot marker `trial_ledger.json` is written **before** `cells.csv` and `report.md`. The runner therefore treats the pass as complete only when **all of** `trial_ledger.json`, `cells.csv`, `report.md` and `d0_coverage.json` exist. **A scoring pass that crashed before writing its outputs may be re-executed once.** The crash and the restart are recorded:
  - in `phase_d_runner.log` (CRASH and RESTART lines, with partial outputs moved to `_crashed_run_<UTC>/`);
  - and in a "Run history" section appended to `report.md`.

  A second failure is an ABORT, and the owner decides what happens next.
- The runner never pushes to git. The owner reviews and pushes after Gate D.

### §6 note, 2026-10-01 (lock revision 3.1; append-only, §6 above is kept as written)

The "Scoring (D2)" rule above is **superseded** for Phase D by lock revision 3.1, a mechanical change:
- `phase_d.py` now writes the one-shot marker `trial_ledger.json` **last**, after `cells.csv` and `report.md` are complete.
- The run-once check (refuse when the marker exists) is unchanged.

The runner no longer moves partial scoring outputs aside. Its rule is now:
- **Marker absent after a crash:** re-run **once**. The re-run overwrites the partial outputs, and the crash and restart are recorded in `phase_d_runner.log` and appended to `report.md`.
- **Marker present:** **never** re-run.

The "Download (D1)" rule above is unchanged: the downloader is not modified, and a failed download is still retried once from scratch with the partial Alpaca archive moved aside.
