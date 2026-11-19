# V2 forward study closeout: `INSIDER_BUY_CLUSTER_V2@1` (2026-11-01)

**Classification: `V2_NO_EDGE_CONFIRMED`.** On the unseen forward episodes the primary metric (net +10 minus SPY +10)
is **−2.46%** (n = 28), below zero. Under the approved rules this confirms `UNSUPPORTED`.

- **Rules:** `docs/research/preregistration/2026-10-24_decision_rules_v2_forward_and_pdm.md`, Study 1. Drafted at
  `e378b67`, approved by the owner 2026-10-27 07:12Z (`370819d`), before this file was read.
- **Read once:** 2026-11-01 ~09:20Z.
- **Untouched:** no threshold, population, metric or exit was changed. Nothing was rerun, backfilled or fetched, and
  nothing live was changed.

## Run record

| Item | Result |
|---|---|
| 2026-10-15 | **MISSED** (machine at the sign-in screen after a Windows Update reboot; no record, not rerun) |
| 2026-10-16 … 2026-10-31 | 16/16 `SUCCESS`, scheduled 06:00:00Z, every stage exit 0, artifact validated, problems [] |
| Final input | `results/v2_validation/forward/2026-10-31.json` (as_of 2026-10-31, freeze 2026-09-06) |
| Loop | `loop_end` 2026-11-01T06:00:00Z, "stop date 2026-10-31 passed"; no forward process remains |
| Missed day | No data lost: each daily file recomputes every post-freeze episode, so 10-16 onward covers 10-15 |

## Field definitions (from `talonx_paperperf/v2_validation.py`)

| Field | Definition |
|---|---|
| `g10` | Close at entry + 10 sessions ÷ entry-session open − 1 |
| `net10` | `g10` − 20 bps |
| `spy10` | SPY over the same window (exit-session close ÷ entry-session open − 1) |
| `exit_session` | Date of the +10 close |
| Eligible | `liq_reason == PASS` |

## Population

| | Count |
|---|---|
| Episodes after freeze | 185 |
| V2-eligible | 58 |
| Resolved at +10 | **41** |
| Unresolved | 17 (counted, not imputed) |

## Results (resolved, eligible)

| Subset | n | **Primary mean (net − SPY)** | Primary median | Raw net mean | PF (net) | Primary mean without best 3 | Best trade / positive net | Issuers |
|---|---|---|---|---|---|---|---|---|
| ALL | 41 | **−3.03%** | −2.92% | −2.51% | 0.52 | −4.64% | 0.23 | 37 |
| **UNSEEN** (exit > 2026-09-30), classification subset | **28** | **−2.46%** | −1.43% | −2.17% | 0.52 | −4.33% | 0.22 | 27 |
| UNSEEN_STRICT (exit > 2026-10-06), sensitivity | 18 | −1.39% | +1.03% | −1.31% | 0.72 | −4.30% | 0.25 | 17 |
| SP500 ∩ ALL (descriptive) | 4 | −0.83% | −0.24% | −0.35% | 0.81 | n/a | 0.65 | 4 |
| SP500 ∩ UNSEEN | 2 | −0.24% | −0.24% | −0.17% | 0.86 | n/a | 1.00 | 2 |

- Total net is negative in every subset except the n = 1 strict S&P subset, so "best trade / total net" is undefined
  there. The share of positive net points is shown instead.
- The two SP500 ∩ UNSEEN trades:
  - TPL, entry 2026-09-18 → exit 10-02: net −2.35%, SPY +1.09%.
  - SPG, entry 10-02 → exit 10-16: net +2.01%, SPY −0.95%.

## Classification (approved Study 1 table)

| Rule | Result | Verdict |
|---|---|---|
| Row 1: primary mean ≤ 0 or < 10 resolved unseen | UNSEEN primary −2.46%, n = 28 | **Met → `V2_NO_EDGE_CONFIRMED`** |
| Row 3 (S&P follow-up): SP500 subset ≥ 15 resolved | 2 (unseen) / 4 (all) | Not met |
| Sensitivity: UNSEEN_STRICT | −1.39%, n = 18 | Same class |

## Interpretations stated in advance

- **SP500 condition:** applied to SP500 ∩ UNSEEN, since the rules' table header puts classification on UNSEEN. The
  result does not depend on this: SP500 ∩ ALL has n = 4, also below 15.
- **2026-10-07 exposure:** a single aggregate subset summary (n, mean, PF) printed from `forward.log`. No individual
  episodes were shown, so they cannot be listed. Classification uses UNSEEN as defined. The strict variant removes
  every episode resolved by 2026-10-06, which covers anything that aggregate could have included, and gives the same
  class.

## Approved owner action for this class

1. Confirm `INSIDER_BUY_CLUSTER_V2@1 = UNSUPPORTED`. Stop presenting V2 as a candidate or quoting an expected return.
2. Decide only whether the live V2 companion keeps running as a **descriptive record** or is **retired**.
3. No live change and no successor study follow from this result. The S&P-500-only study (row 3) was not earned.

## Limitations

- **Low power.** 28 unseen episodes over about 7 weeks; trades in the same weeks share market moves. This closeout
  establishes "no edge shown" under the rules. It is not a precise estimate of the true effect.
- **Consistent with earlier unseen evidence:** checkpoint 2 (2026-09-30) gave Q3 2026 net −2.47% (n = 99) and
  prospective −2.26% (n = 10). The direction is the same.
- **Population:** the forward population is the runtime's liquidity-gated universe, not the S&P 500 panel where the
  original +1.69% / +1.01% came from. That domain produced only 4 resolved episodes, too few to test.
- Per-episode outputs stay in gitignored `results/v2_validation/`. Aggregates are in
  `results/v2_validation/closeout_20261101/closeout_metrics.json`.

The PDM final report follows after **2026-11-17 22:00Z**, then the programme decision under the same approved rules.
