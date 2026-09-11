1. **Verdict**: runtime unchanged — no defect proven anywhere in this task. Research `355eb16` → this commit.

2. **Readiness**: live cutoff ~15:22–15:26 UTC — **25/43 ready** (up from 24 at Task 118D's check), 18 not-ready (80–111 bars of 120 required), all with fresh timestamps, steadily climbing. Estimated ETA for the worst laggers (BLK, JNJ): ~60–80 minutes, explicitly labelled an uncertain linear extrapolation from two spaced snapshots.

3. **Recovery**: **no code/config action taken.** Natural live-tick accumulation is already bounded and in progress (estimable ETA under 90 minutes for the worst case); building and safely testing a new backfill mechanism against this task's own strict safety requirements (no retrospective signals, no replayed historical exits, safe buffer merge) could not be done responsibly in the time available. No readiness requirement was lowered to report green.

4. **SPCX**: traced provider→ingestion→consumer→exit-evaluation→valuation — found a **fresh 1-minute bar at 15:21:00Z** and continuous `regime_shadow` evaluation throughout, plus exactly one correctly-rejected stale tick (574s old) at ~15:03:53Z. **Conclusion: the 25-minute-old mark reported in Task 118D was a report-snapshot limitation, not a monitoring gap or defect — nothing was fixed because nothing was broken.** SPCX still open (unchanged); updated unrealized P&L ≈**−$21.88** on the fresh $146.93 mark (~2 min old at report time).

5. **Experimental P&L**: realized total reconfirmed **exactly −$324.4662160270568** (no new trades since Task 118D). All four closes remain flagged as first-live-validation of today's exit fix, not an established track record.

6. **Episode/trade-count corrections**: the reported 10/147/157 are **ENTERED episodes = closed round trips** (all `exit_unresolved: 0`), not all evaluated episodes (the fuller disposition totals are 17/385/402). `C = A + B` verified exactly at both the ENTERED level (157=10+147) and the full-disposition level (402=17+385) — clean, non-overlapping populations. **New**: a predeclared month-of-entry time-block bootstrap sensitivity found the A-vs-B difference significance conclusion is **not robust** to the resampling-unit choice (issuer-block: marginally inconclusive [−9.48%,+0.76%]; time-block: marginally negative [−12.68%,−0.14%]) — reported as an honest divergence, not resolved either way.

7. **Composition result**: one predeclared feature (20-trading-day pre-entry realized volatility, issuer-level, PIT-correct) — A's 6 issuers average **77.6%** annualized vol vs. B's **52.6%**, placing A at the **96.8th percentile** of random 6-issuer draws from B. Sector/market-cap explicitly omitted (no point-in-time source available). Descriptive association only, not causal, not decisive at N=6.

8. **Decision**: **A. ONE_TESTABLE_HYPOTHESIS** (explicitly labelled EXPLORATORY) — elevated pre-entry volatility in A's traded issuers may explain part of the negative expectancy under the frozen (non-volatility-scaled) 10-day hold/20bps cost structure. Confirmation requires genuinely unused **future live** 39-name-scope entries (N≥10), tested **within-scope** (not cross-population). Distinct from Task 95K (opposite-direction risk-filter finding). Explicit rejection criterion stated. No scope/strategy change follows automatically.

9. **Deployment**: **not triggered** — no active defect was found in readiness, SPCX, or anywhere else investigated this task.

10. **EOD/links**: not yet due — `python -m talonx_ops.prospective close` required at/after **2026-09-11T20:00:00Z**, complete by **21:30:00Z**. `docs/research/TASK118E_READINESS_SPCX_DECISION.md` (this branch).

Operational success (healthy session, no defects) and profitability evidence (still inconclusive for A; the composition finding is descriptive) are reported separately, as required.
