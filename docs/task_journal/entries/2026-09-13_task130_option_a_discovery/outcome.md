1. **Economic, statistical, and integration-review verdicts**:
   Statistical (Track B) — CI excludes zero, entirely positive, under
   BOTH predeclared uncertainty methods. Economic/integration-review —
   **`PASS_FOR_INTEGRATION_REVIEW`**. Not a deployment recommendation.

2. **SHAs**: release verified `f28986999eec5e313cfc89db24e4dbacfb378891`
   unchanged. Research: resolved current HEAD
   `2542e1210a3a6a46001f1508f4ae0c642bd10042` (the later documentation-
   only correction, inspected and recorded, not reset) →
   protocol-freeze checkpoint `9a484a4` → final **`<this commit>`**,
   pushed to `research/talonx-profitability-2026-09` only.

3. **Exact discovery population and eligibility rule**: Discovery
   Universe v1 = Task 118D's own matched-post-117-runtime 626-name
   population (Task 116's 620-name panel ∪ Tier 1's 39 SEC-resolved
   names), reused directly, not reconstructed. Eligibility, resolved
   from actual code (not the documented label): LIQUIDITY-ONLY —
   trailing-20-session causal median dollar volume ≥ $5,000,000 AND
   last close ≥ $5.00; the documented membership-OR-liquidity branch is
   not implemented anywhere in the codebase.

4. **Changes from the old research/runtime contract**: a genuine,
   documented policy change (not "unchanged behavior") — this task's
   Track B requires a pre-existing durable `pending_entry_intents` row
   before an entry counts as prospective; the current runtime instead
   permits labelled "cold-start backfill" entries without one. Track A
   (historical, unfiltered, matches every prior V2 replay's own
   convention) is reported alongside Track B for direct comparison.

5. **Prospective-entry and capacity-policy acceptance**: Track B
   excluded 4 of 157 closed trades (2.5%) as cold-start; its own
   reconstructed $300k campaign never touches cash for those 4. The
   $300k/$10k/20-slot capacity rule was **not binding** in this
   evaluation (minimum cash observed $181,392.76 of $300,000) —
   disclosed explicitly, not implied to have been meaningfully stress-
   tested by this run.

6. **Net economics, uncertainty, concentration, stability**: Track B
   N=153, 106 distinct issuers, net mean **+2.0219%**/round trip
   (clears the +0.50% primary criterion), win rate 62.75%, PF 2.1399.
   Issuer-block bootstrap 95% CI **[+0.7222%, +3.3989%]**; date-block
   (19 monthly blocks) 95% CI **[+0.5723%, +3.4573%]** — both exclude
   zero, both agree. Top-1/3/5-issuer-removal sensitivity never
   reverses sign (+2.16%/+1.99%/+1.95%). Calendar half-year stability:
   3 of 4 half-years independently positive; **2026H1 is negative
   (−0.50%, n=33)** — disclosed as an active-monitoring concern, not
   smoothed over.

7. **Marked-equity risk and unresolved positions**: Track B's
   reconstructed realized-equity max drawdown **−2.25%** (cost-marked
   open positions; explicitly does NOT include intra-holding unrealized
   fluctuation — no daily bar marks wired into this reconstruction, a
   disclosed limitation). 0 open positions and 0 `EXIT_UNRESOLVED` at
   window end (natural completion, not forced). SPY buy-and-hold over
   the same window returned +20.28% — exceeds Track B's own +10.31% —
   reported as context only, per the frozen protocol's explicit
   separation of the per-trade expectancy criterion from portfolio-
   level market-exposure comparison.

8. **Timestamp/data limitations**: no intraday dissemination timestamp
   is manufactured anywhere — every causal-timing claim operates at
   trading-session granularity, matching the historical data's own
   resolution. Track C (operational latency) is `UNAVAILABLE_REQUIRES_LIVE_OBSERVATION`
   by definition. 35/626 symbols have an ambiguous CIK mapping, 12/626
   (including SHOP) have zero Form 4 coverage, 1/626 has zero price
   coverage — all disclosed in the universe manifest, none silently
   dropped. Two implementation-correctness issues (wall-clock vs.
   simulated dates; a capital-deployment artifact mislabeled as
   drawdown) were found and fixed within this task before any result
   was used for the decision — see the journal record for detail.

9. **One next action and production preservation**: the integration
   handoff (`TASK130_OPTION_A_ECONOMIC_DECISION.md` Part 8) specifies
   the minimum implementation delta for a LATER, separately-authorized
   integration-review task — design only, nothing implemented here. No
   release-branch change; no application process started; Redis
   `talonx:*` key count 0 throughout; the isolated replay ledger is a
   fresh file under `results/`, never the live `v2_lane.db` (hard
   safety check enforced and passed).

10. **Journal/reports**: `entries/2026-09-13_task130_option_a_discovery/`
    + `docs/research/{TASK130_OPTION_A_CONTRACT,TASK130_FROZEN_EVALUATION_PROTOCOL,TASK130_OPTION_A_ECONOMIC_DECISION}.md`
    + `docs/research/evidence/task130/*.json` +
    `research/scripts/task130_{universe_manifest,discovery_evaluation}.py`
    + `tests/test_task130_discovery_evaluation.py` — protocol freeze at
    `9a484a4`, remainder at this commit, both pushed.

Success criterion met: one defensible decision about this exact V2
expansion (Discovery Universe v1, $300k/20-slot capacity, timestamp-
proven prospective policy) — `PASS_FOR_INTEGRATION_REVIEW`, with every
limitation (capacity not stress-tested, recent half-year negative,
coverage gaps, SPY context) carried forward explicitly, not a bare
"more alerts" or "fingerprint preserved" claim.
