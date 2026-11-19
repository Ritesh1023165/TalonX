# Decision rules for the two open studies (V2 forward, PDM): APPROVED 2026-10-27

**Written 2026-10-24, before either study's outcomes are read.** Neither the V2 forward outputs
(`results/v2_validation/forward/*.json`) nor any PDM return value was opened to write this.

This changes **nothing** in either study. It records, in advance, how the owner will act on each possible result, so
the decision cannot be fitted to the numbers afterwards. **Status: APPROVED by the owner, unchanged from the draft committed at `e378b67`
(2026-10-24 07:16Z).** Approval is recorded below.

## Ground rules (both studies)

- **No real money** under any outcome. Both studies are too small to justify it: V2 forward is expected to resolve a
  few dozen episodes, and PDM has about 20 sessions.
- **Read once, at the endpoint.** No interim peeks. No re-running a window, no changing a threshold, cost,
  population or exit to rescue a result.
- **Negative or inconclusive means "no edge shown".** It is not proof the idea can never work. Inconclusive is
  treated as **no edge** for decisions.
- **A positive result earns at most one new pre-registered paper study** with a stated sample-size target and end
  date. It never earns a live change on its own.

## Study 1: V2 forward (`INSIDER_BUY_CLUSTER_V2@1`, ends with the 2026-10-31 06:00Z run)

**Input.**
- `results/v2_validation/forward/2026-10-31.json` only. It is cumulative: every episode activated after the
  2026-09-06 freeze.
- If the 10-31 run is not SUCCESS, use the last SUCCESS file and record the gap. No rerun or backfill.

**Population.**
- V2-eligible (`liq_reason == PASS`) episodes with a resolved +10-session outcome (`net10` present).
- Unresolved episodes are counted and reported, not imputed.

**Reported subsets.**
- **ALL**: every resolved eligible episode.
- **UNSEEN**: episodes whose exit session is **after 2026-09-30**. These were unresolved at checkpoint 2, which
  unblinded the first 10. Episodes touched by the recorded 2026-10-07 accidental exposure are listed and also shown
  excluded.
- **SP500**: `sp500_panel == true`, the domain where the original +1.69% / +1.01% result came from.

**Metrics.**
- Primary: mean of **net +10 minus SPY +10** (`net10 − spy10`). Market-excess, because the earlier "edge" was largely
  market beta.
- Also: raw net mean, profit factor, mean without the best 3 trades, the largest single trade's share of total net
  points, and the issuer count.

| Result (on **UNSEEN**; ALL shown alongside) | Classification | Owner action |
|---|---|---|
| Primary mean ≤ 0, **or** fewer than 10 resolved unseen episodes | `V2_NO_EDGE_CONFIRMED` / `V2_INSUFFICIENT` | Confirm `UNSUPPORTED`. Stop presenting V2 as a candidate. Decide only whether the companion keeps running as a descriptive record or is retired. |
| Primary mean > 0 on UNSEEN, but the SP500 subset has < 15 resolved, or is ≤ 0, or ≤ 0 without its best 3, or one trade > 40% of its net points | `V2_UNCONFIRMED` | Same as above. No live change. A new study is optional and explicit only. |
| **SP500 subset**: ≥ 15 resolved, primary mean > 0, still > 0 without the best 3, no single trade > 40% of net points | `V2_SP500_SIGNAL_WORTH_TESTING` | May approve **one** new pre-registered prospective study, **V2 restricted to S&P 500 issuers**: market-excess primary metric, a target of ≥ 100 episodes, and a fixed end date set before it starts. The live V2 ledger is not changed by this result. |

## Study 2: PDM (`POST_DELIVERY_ALERT_MARKOUT_V1`, endpoint 2026-11-17 22:00Z)

**Input.**
- The protocol's `final_report()`, run once after the endpoint, per segment (protocol §7).
- Metric: cost-adjusted markout from 5 minutes after Telegram acceptance to +30 minutes, with an interval that
  resamples **whole sessions**.

**Coverage gate.**
- If measured ÷ selected < 80% in the main segment, the result is `PDM_INCONCLUSIVE_DATA`, treated as no edge.
- The data-collection failure is fixed before any successor study.

| Result (main segment) | Classification | Owner action |
|---|---|---|
| **Gross** mean ≤ 0 | `PDM_NO_VALUE_AFTER_DELIVERY` (the premise fails even before costs) | Alerts stay **descriptive awareness only**. Decide whether to keep, thin or stop Signal delivery. Never reframe them as trade prompts. |
| Gross > 0 but **cost-adjusted** mean ≤ 0, or its session interval includes 0 | `PDM_NOT_COST_SURVIVING` | Same as above. Optional: a research note on whether faster delivery could change it (no live change). |
| Cost-adjusted mean > 0 **and** session-interval lower bound > 0 **and** positive in ≥ 60% of sessions **and** still > 0 without the top 5 alerts | `PDM_POST_DELIVERY_VALUE_WORTH_TESTING` | May approve **one** new pre-registered paper study of an executable version: exact entry rule, costs, sessions and end date fixed in advance. No live change from this result alone. |
| Cost-adjusted session-interval upper bound < 0 | `PDM_CLEARLY_NEGATIVE` | Strong evidence the alerts arrive after the move. Consider pausing Signal-bot review alerts or keeping them Lab-only. |

## Programme decision (after both, from 2026-11-18)

| V2 | PDM | Decision |
|---|---|---|
| No edge / unconfirmed | No value / not cost-surviving / negative / inconclusive | **Stop the edge search under the current constraints** (free data, delayed delivery, manual, long-only). TalonX continues as a descriptive Risk & Event Intelligence product. Write the programme closeout. |
| `V2_SP500_SIGNAL_WORTH_TESTING` and/or `PDM_POST_DELIVERY_VALUE_WORTH_TESTING` | | Run **only** the approved successor study for that item. Everything else stays stopped. |

**Any other lane** (paid consensus, options, short interest, real-time data, automated execution, shorting) needs a
**separate explicit mandate** with its own budget and pre-registration, and is never a reaction to these results.

## Owner approval

- [x] **Approved as written** (no changes), owner instruction in session: "Approved".
- Approval date/time (UTC): **2026-10-27 07:12Z**.
- At approval: no V2 forward output (`results/v2_validation/forward/*.json`) and no PDM return value had been read. The final forward run (2026-10-31) and the PDM endpoint (2026-11-17 22:00Z) are still in the future.
