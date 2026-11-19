# Alpha programme closeout (2026-11-20)

**Decision (approved 2026-11-19, PDM final report):** stop the edge search under the current constraints (free data, delayed
delivery, manual trading, long-only). TalonX continues as a descriptive **Risk & Event Intelligence** product. Any new lane
(real-time or paid data, automated or cheaper execution, shorting) needs a separate explicit mandate.

The common finding: every intraday or event signal tested shows at most a small real move, and that move is smaller than the cost
of acting on it. Round-trip cost is about 18 bps in the PDM study; the signals sit at roughly 10 bps.

## What was tested

| Study | Question | Result | Source |
| --- | --- | --- | --- |
| V2 insider-buy cluster, development | Do insider-buy clusters beat the market net of cost? | Development mean net -0.15%, PF 0.97, n = 4,009; the S&P 500 subset's gain did not hold beyond market beta | `docs/research/evidence/2026-10-07_v2_verdict_reconciliation.md` |
| V2 forward (`INSIDER_BUY_CLUSTER_V2@1`) | Does that hold on new episodes? | `V2_NO_EDGE_CONFIRMED`: unseen primary (net +10 minus SPY +10) -2.46%, n = 28. 185 episodes after the freeze, 58 eligible, 41 resolved | `docs/research/evidence/2026-11-01_v2_forward_closeout/CLOSEOUT.md` |
| PDM (`POST_DELIVERY_ALERT_MARKOUT_V1`) | Is there a move after an alert reaches Telegram, large enough to trade? | `PDM_NOT_COST_SURVIVING`: +0.107% gross (95% session interval +0.018% to +0.191%), -0.077% after costs (-0.168% to +0.006%); 1,225 alerts, 20 sessions, coverage 96.4% | `docs/research/evidence/2026-11-19_pdm_final_report/FINAL_REPORT.md` |
| TICKER_SCORECARD_V1 | Can a rule-based ranking of about 1,000 liquid names beat SPY at 1D, 1W, 1M or 3M? | No horizon passed. 1D has real but tiny skill (rank IC 0.016, 95% lower bound 0.001) and the top decile earns -2 bp against a 20 bp cost hurdle; 1W, 1M and 3M are inconclusive | `docs/research/closeout/2026-11-04_ticker_scorecard_v1_closeout.md` (on `main`) |

Earlier work in the programme (the Original intraday strategy, Tasks 93 to 95A and the cross-sectional experiments) is recorded in
`docs/research/TALONX_RESEARCH_LEDGER.md` and is not re-summarised here. The PDM report cites Task 94 and 95A as the first time the
programme met the same "drift is about equal to cost" wall.

## What was learned

- **The wall is cost, not data quality.** Two independent studies (PDM, scorecard 1D) found a small, statistically real move that
  trading costs erase. A larger sample would tighten the interval around a number that is still too small.
- **Rules fixed in advance worked.** The V2 forward, PDM and scorecard studies were read once, with decision rules and thresholds written
  before any outcome was opened and no re-runs. That stopped each of them from being tuned into a false positive, and it is why the
  negative results can be trusted.
- **Averages are per alert or per name, not portfolio returns.** None of these studies show executable profit, and none were meant to.
- **Data hazards that bit:** split adjustment (blocked the earlier reversion work), survivorship bias from a current-only symbol list
  (scorecard), delayed free-tier delivery (PDM), and a missed forward day after an unattended reboot (V2).
- **A small effective sample limits every result.** PDM has about 20 independent sessions; the scorecard HOLDOUT has 78 weekly rank
  dates and about six independent 3-month windows.

## Owner decisions recorded 2026-11-19 / 2026-11-20

| Item | Decision | Status |
| --- | --- | --- |
| Review alerts to the Signal bot | Thin out; awareness only, never worded as trade prompts | Decided; implementation not done |
| V2 companion | Keep as a passive, read-only record of insider-buy clusters; no alerts | Decided; implementation not done |
| Programme closeout | Write it (this document) | Done |

## What a future attempt would need

A new mandate, because the current constraints are what the evidence rules out. In rough order of how directly they address the finding:

1. **Cheaper or automated execution**, since cost is the binding constraint. PDM did not test faster delivery or cheaper costs.
2. **Real-time data**, since the 5-minute delivery and entry delay is part of what the move loses before anyone can act.
3. **Paid or survivorship-free data**, including point-in-time listings with delisted names, so a 1M or 3M re-test is credible.
4. **Shorting**, since the long-only constraint removes the Bearish side. In the scorecard, the bottom decile out-earned the top at 1M and 3M, so
   a Bearish view would have lost money there; this is a caution, not a reason.
5. **A pre-registered design with a larger independent sample** than 20 sessions, with decision rules written first.

None of these is a recommendation to continue. Each would start as a new, separately pre-registered study.

## Provenance

- PDM final report: commit `ba2736e` on `feature/continuous-opportunity-engine`, protocol fingerprint `c812a3e65e4018a5`, run once on 2026-11-19.
- Decision rules for V2 forward and PDM: `docs/research/preregistration/2026-10-24_decision_rules_v2_forward_and_pdm.md` (approved 2026-10-27, `370819d`).
- Scorecard: PR #22 merged to `main` (merge commit `4b8eed1`); results in `results/scorecard_v1/`; amendments in
  `docs/research/preregistration/2026-11-04_amendment_1_gate1_scope.md`.
