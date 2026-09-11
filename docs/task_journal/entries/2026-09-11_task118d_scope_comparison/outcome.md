1. **Verdict**: runtime unchanged (no restart, no defect to fix). Research `7551c98` → **`(this commit)`**.

2. **Populations**: A = 39 names (existing artifact, 10 trades). B = 587 names (full panel minus A, fresh matched-runtime replay). C = A∪B = 626 names. **Correction found**: Task 116's published 620-name panel could not be reused verbatim as C — 6 of A's names (ABCL, ACHR, ADC, AGNC, MSTR, SHOP) are absent from it, and Task 116 itself ran under a pre-Task-117 (unmatched) runtime — so B/C were re-run fresh here under the exact matched contract A used. C's episode count (157) = A(10) + B(147) exactly, confirming no leakage.

3. **Economics/uncertainty**: A (10 trades, 6 issuers): −2.926% mean, PF 0.315, 30% win. B (147 trades, 101 issuers): **+2.154%** mean, PF 2.258, 63.9% win. C (157, 107 issuers): +1.831%, PF 1.976, 61.8% win. Issuer-block bootstrap (seed 118118, 5000 reps): A's own CI **[−7.06%, +2.64%]** (includes zero — inconclusive); B's CI **[+0.94%, +3.48%]** (entirely positive); **A−B difference CI [−9.48%, +0.76%]** — includes zero marginally, i.e. **not a statistically decisive separation** despite the negative point estimate, exactly per this task's instruction not to infer relative underperformance from A's own negative interval alone. A's only 6 issuer blocks are stated explicitly as too few for a well-powered inference.

4. **Product meaning**: rare opportunities in A confirmed unchanged (10 trades/19mo). A's negative result and its own inconclusive interval coexist honestly. Whether scope composition explains the A-vs-B gap is **suggestive, not proven** at this sample size. No watchlist expansion is authorized or implied by B's positive result.

5. **Readiness**: 24/43 ready live (up from 18 earlier today), 19 climbing steadily, all with fresh (~same-minute) timestamps. `usable_coverage:1.0` explicitly distinguished from strategy readiness. Suppression counts (24 distinct LOW_VOLATILITY tickers) exactly match the 24 ready symbols.

6. **Experimental reconciliation**: VRT −$213.72, STX −$25.38, AMD −$8.22, BLSH −$77.14 — sum **−$324.4662**, matches the authoritative ledger's `total_realized_pnl_usd` **exactly**. **SPCX confirmed still open**, unrealized ≈ **−$13.11** on a $147.45 mark (~25 min old, timestamped, not fabricated). All four closes flagged as first-live-validation of today's exit-lifecycle fix, not an established track record.

7. **Delivery**: Original 0/0 (correct, LOW_VOLATILITY-dominated), Intelligence unchanged (6 cards = 1 message today), V2 0 (no signal), Experimental 0 external (by design). Incident carryover (heartbeat-lapse locus, "45 candidates" source) **kept unresolved** — no new evidence found.

8. **EOD**: not yet due. Required operator action unchanged: `python -m talonx_ops.prospective close` at/after **2026-09-11T20:00:00Z**, complete by **21:30:00Z**.

9. **Next research action**: compare A's 6 traded issuers' composition characteristics (sector/size/volatility regime) against B's 101, using already-collected data — no new backtest, no live wait. Rejection criterion: if A's issuers show no systematic difference from random 6-issuer draws of B, the "composition explains it" hypothesis is not supported.

10. **Links**: `docs/research/TASK118D_SCOPE_COMPARISON.md`, `TASK118D_LIVE_EVIDENCE.md`; scripts + outputs under `results/task118_profitability/`.

**Operational acceptance**: session healthy throughout, runtime unchanged, evidence verified live. **Profitability evidence**: reported separately above — inconclusive for A at its own sample size; not equated with B's positive broader-panel result, which does not apply to the live 39-name scope.
