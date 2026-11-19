# Forward alpha validation — CONTROL vs pre-registered SHADOW (SQF_V1)

Append-only. Each session section is added once by `python -m talonx_paperperf.forward append <date>` after that
session's EOD forensic; existing sections are never rewritten. Paper only: no capital, no orders, no live Signal
change.

## Registration (frozen before any 2026-09-30 Signal existed)

| Item | Value |
|---|---|
| CONTROL | Unchanged live PAPER_SIGNAL policy (OPPORTUNITY_PROMOTION_V1: REGULAR-only, BULLISH-only, 3 per 5 min, 30-min queue expiry, one promotion per candidate). Every Signal is observed as before. |
| CONTROL_POLICY_FINGERPRINT | **2a9c14d678b54a4d**, composed of PROMOTION_POLICY 4926c12e5eace04e, promotion component f0c3b237b589, CONTINUOUS_RESEARCH 2ef115ee19f99574 and PREMARKET_RESEARCH_V1 62ba413daf85e674 |
| SHADOW_HYPOTHESIS_ID | **SQF_V1** (fingerprint **460ee466c5ae8d6f**, `talonx_paperperf/hypotheses.py`) |
| HYPOTHESIS_SOURCE | IN_SAMPLE_DERIVED_FROM_2026-09-28_TO_2026-09-29 (exploratory strata of `2026-09-30_profitability_forensic.md`) |
| REGISTERED | 2026-09-30T08:10Z. The git commit adding it precedes the 13:30Z open; 0 Signals existed for 2026-09-30 at registration. |
| VALIDATION_START | 2026-09-30 (first unseen session) |
| Window | ≥ 10 complete forward sessions; no filter change during the window |

**Filter:** PASS only if every condition below holds. Each failure is recorded by name, and missing data is recorded
as `UNKNOWN_DATA`, never dropped.
- An actionable entry exists.
- The measured SIP NBBO spread at the actionable entry is ≤ 25 bps.
- The Signal's ADV20 is ≥ $20M.
- The catalyst is **not 8-K-only**, meaning not every `;`-separated catalyst segment is an `8-K…` segment. 6-K,
  other filings and insider evidence are not 8-K-only. This is slightly narrower than the forensic's "contains 8-K"
  bucket, and is recorded here before any validation data.

**Evaluation:**
- **Entry:** long, at the actionable entry: the open of the first 1-minute SIP bar at or after the Telegram SENT time.
- **Exit:** a fixed +30-minute exit. Other horizons are descriptive only.
- **Cost:** max(V2 20 bps round-trip friction, measured spread).
- **Portfolio:** $100k, $10k per position, at most 10 concurrent, no leverage. It is the same for CONTROL and SHADOW.

**Pre-registered gates:**
- **Pass (only after ≥ 10 sessions):**
  1. gross expectancy > 0;
  2. net expectancy > 0;
  3. profit factor > 1;
  4. the mean remains > 0 without the best 3 trades;
  5. performance persists across sessions.
- **Fail:** any of gross ≤ 0, net ≤ 0 or PF ≤ 1 with adequate sample → `SHADOW_FILTER_FAILED`. No rescue by
  re-thresholding on the same period.
- **Early failure:** with ≥ 60 SHADOW trades, mean gross + 2·SE < 0 → `EARLY_FAILURE_CANDIDATE`.
- **Escalation:** if CONTROL and SHADOW are both gross ≤ 0, escalate to `PREMISE_FAILURE_CANDIDATE`. The premise
  under test is *buying bullish continuation opportunities after they are observed through the 15-minute-delayed
  data pipeline*. A different causal hypothesis is then proposed instead of more filters.

## Sessions

### In-sample reference, 2026-09-28 + 2026-09-29 (NOT validation; the data the hypothesis came from)

| | CONTROL | SHADOW SQF_V1 |
|---|---|---|
| Signals | 307 | 113 pass |
| Resolved at +30m | 274 | 104 |
| **Gross +30m** | **−0.055%** | **−0.000%** |
| Net +30m | −0.573% | −0.204% |
| Win rate / profit factor | 30.3% / 0.28 | 40.4% / 0.52 |
| Paper P&L (+30m, $100k / $10k) | −$11,279 | −$1,951 |

**SHADOW fail reasons (CONTROL signals):**

| Reason | Count |
|---|---|
| `SPREAD_GT_25BPS` | 154 |
| `ADV20_LT_20M` | 147 |
| `CATALYST_8K_ONLY` | 10 |
| `SPREAD_UNKNOWN_DATA` | 7 |
| `NO_ACTIONABLE_ENTRY` | 6 |

**Read-out, recorded before validation:** even in-sample, SQF_V1 only removes *cost*. Its gross expectancy is ~0,
the same as CONTROL. Because the first gate is gross > 0, the hypothesis needs future sessions to show a gross edge
that the derivation sample did not show. If they don't, the premise escalates as registered.


<!-- boundary:DTU_V1@2026-09-30T09:40:04Z -->
### BOUNDARY — DTU_V1 activated 2026-09-30T09:40:04Z (`DTU_V1@2026-09-30T09:40:04Z`)

`TALONX_DTU_MODE=ACTIVE`: CONTROL Signals are now produced from the effective active universe (Core 1,200 +
event-promoted + V2/operator + protected), not the full universe.
- **Unchanged:** the CONTROL promotion policy (4926c12e5eace04e), SQF_V1 (460ee466c5ae8d6f), scoring and lifecycle.
- **Segmentation:** every Signal row carries `dtu_boundary` = `PRE_DTU` | `POST_DTU:<id>` and its production DTU
  state at decision time. All session and cumulative reports are split PRE_DTU / POST_DTU and never aggregated
  across the boundary.
- **Today:** 0 Signals existed before activation (09:40Z, premarket), so the entire 2026-09-30 validation session
  is POST_DTU.
