# PDM_V1 final report: post-delivery price markout (2026-11-19)

**Classification: `PDM_NOT_COST_SURVIVING`.** After Telegram delivery, review alerts show a **small positive move
before costs** (+0.107% per alert; 95% session interval excludes 0; 70% of sessions positive). It does **not survive
costs** (−0.077% per alert; 45% of sessions positive).

**Run:**
- Protocol `POST_DELIVERY_ALERT_MARKOUT_V1` r2 (fingerprint `c812a3e65e4018a5`). `final_report()` was run **once** on
  2026-11-19 ~19:02Z, after the 2026-11-17 22:00Z endpoint, on the owner's "go".
- Classified with the approved rules (`docs/research/preregistration/2026-10-24_decision_rules_v2_forward_and_pdm.md`,
  Study 2; approved 2026-10-27, `370819d`), which were fixed before any return was read.
- The store `pdm.db` is byte-identical before and after the run (sha256 prefix `294461bb1a92d83f`). Integrity was
  verified at load (`require_integrity=True`).

**Label (protocol):** *post-delivery price markout under stated cost assumptions*.
- Alert-level averages, **not** portfolio performance or executable profit.
- Alerts within a session share market moves, so the effective sample is close to **20 sessions**.
- The protocol itself has no PASS threshold.

## Collection

| Item | Value |
|---|---|
| Sessions | 20 (2026-10-19 … 2026-11-13), one segment: `…|c812a3e65e4018a5|4926c12e5eace04e|UNKNOWN|RESEARCH_REVIEW` (policy fp `4926c12e5eace04e`, RESEARCH_REVIEW delivery). The DTU fingerprint is recorded as `UNKNOWN` in the segment key; it is a single segment, so nothing is pooled across segments |
| Delivered alerts registered | 1,320 (all delivered cleanly with a trace) |
| Selected / measured | 1,271 selected; 1,226 gross-measured, 1,225 cost-measured → **coverage 96.4%** (gate ≥ 80%: passed) |
| Not selected | 49 `SESSION_INELIGIBLE`: entry or +30-min exit outside the session |
| Missing (kept in the denominator) | 22 missing entry bar, 23 missing exit bar |
| Acquisition errors | 0 |
| Concentration | 543 symbols; largest session = 9.7% of measured alerts |

## Results (per alert: entry 5 min after Telegram acceptance, exit at +30 min)

| | n | Mean | Median | Positive fraction | p05 | p10 |
|---|---|---|---|---|---|---|
| Gross | 1,226 | **+0.107%** | +0.064% | 55.1% | −1.07% | −0.71% |
| Cost-adjusted (two-sided half-spread + 5 bps) | 1,225 | **−0.077%** | −0.094% | 42.8% | −1.29% | −0.92% |

**Decision metrics** (method fixed before reading: whole-session bootstrap, B = 10,000, seed 20261119):

| | Mean | **95% session interval** (primary) | 90% (sensitivity) | Sessions with mean > 0 | Mean without top 5 alerts |
|---|---|---|---|---|---|
| Gross | +0.107% | **[+0.018%, +0.191%]** | [+0.032%, +0.177%] | 14/20 (70%) | +0.093% |
| Cost-adjusted | −0.077% | **[−0.168%, +0.006%]** | [−0.153%, −0.006%] | 9/20 (45%) | −0.090% |

## Classification (approved Study 2 table)

| Row | Condition | Result |
|---|---|---|
| Coverage gate | measured ÷ selected ≥ 80% | 96.4%: passed |
| Gross mean ≤ 0 → `PDM_NO_VALUE_AFTER_DELIVERY` | +0.107% | not met |
| **Gross > 0, cost-adjusted mean ≤ 0 or its interval includes 0 → `PDM_NOT_COST_SURVIVING`** | −0.077%; 95% interval includes 0 | **met** |
| Worth testing: cost-adjusted > 0 and lower bound > 0 and ≥ 60% sessions and > 0 without top 5 | −0.077%, 45% | not met |
| Clearly negative: cost-adjusted upper bound < 0 | 95%: +0.006% | not met at the primary level |

**Sensitivity.** At the 90% level the cost-adjusted upper bound is −0.006%, which would also meet "clearly negative".
The approved actions for the two classes overlap: alerts are descriptive only, and pausing or Lab-only delivery are
options.

## Approved owner action for this class

- Alerts stay **descriptive awareness only**: never trade prompts.
- Decide whether to **keep, thin or stop** Signal-bot review delivery.
- **Optional:** a research note on whether faster delivery could change the result. No live change.

## What this says, and what it doesn't

- **Says.** On average there is real post-delivery continuation: about +11 bps over the 30 minutes after a 5-minute
  reaction delay, in 70% of sessions. It is smaller than the round-trip cost of acting on it (spread + 5 bps), so an
  alert-taker at these costs loses about 8 bps per alert. This is the same "drift ≈ cost" wall the programme found
  for intraday signals since Task 94/95A.
- **Doesn't say.**
  - That faster or cheaper execution would profit: different delays and costs were not tested, and
    re-thresholding here is not allowed.
  - Anything about portfolio returns or other horizons.
  - Anything beyond 20 sessions.

## Programme decision (approved table)

| Study | Result |
|---|---|
| V2 forward | `V2_NO_EDGE_CONFIRMED` (`docs/research/evidence/2026-11-01_v2_forward_closeout/CLOSEOUT.md`) |
| PDM | `PDM_NOT_COST_SURVIVING` (this report) |

**Approved decision: stop the edge search under the current constraints** (free data, delayed delivery, manual,
long-only). TalonX continues as a descriptive Risk & Event Intelligence product, and the programme closeout is to be
written. Any new lane (paid data, real-time data, automated or cheaper execution, shorting) needs a separate explicit
mandate.

**Files:**
- Method: `run_final_report.py` (this directory).
- Full output: `results/post_delivery_markout/final_report_20261119.json` (gitignored).
