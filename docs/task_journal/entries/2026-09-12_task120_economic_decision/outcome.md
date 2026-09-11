1. **Economic verdict**: **NO_SUPPORTED_STRATEGY_CHANGE.** (Dashboard verdict: see the companion Task 119A entry — `PAPER_EOD_INTEGRATION_ACCEPTED`.)

2. **Analysis run**: predeclared protocol written first (`TASK120_PROTOCOL_39NAME_SCOPE_REPLAY.md`), then executed (`research/scripts/task120_39name_scope_replay.py`) — a full-history replay of the frozen `INSIDER_BUY_CLUSTER_V2@1` contract restricted to the **39-name live execution scope** (resolved live via `talonx_ops.watchlist_coverage`, not hardcoded), reusing the tested Task 112R/116 primitives unmodified. Fingerprint `11107198c5b81237` verified unchanged before running.

3. **Result**: N=27 priced episodes (14 distinct issuers), full window 2019-01-01→2026-09-12, net@20bps=**−0.863%**, PF=0.782, win=55.6%, issuer-block bootstrap 95% CI=**[−7.507%, +2.312%] — includes zero**, drop-top-1 sensitivity +0.761% (sign doesn't flip). Genuinely inconclusive — neither confirms nor rules out a real 39-name-scope effect, exactly one of the four outcomes the protocol predeclared in advance.

4. **A real, newly-identified limitation, not hidden**: 6 of the 39 live-scope names — **ABCL, ACHR, ADC, AGNC, MSTR, SHOP** — have no local historical price coverage. **MSTR is among them**, the same name Task 118E/F already found dominates the live sample's composition. No historical replay of the 39-name scope to date, including this one, has been fully representative of what's actually traded live.

5. **Decision (B4)**: **NO_SUPPORTED_STRATEGY_CHANGE** — no threshold, universe, sizing, or holding-period change is supported. **Smallest concrete evidence-acquisition task named** (not performed here): backfill price coverage for the 6 missing names using the existing `composite-yf` adapter already used live (no new provider), then re-run this exact, already-written script unmodified. Effort estimate (honest, not a target): **small** — a data-backfill + unmodified re-run, not new research design.

6. **Explicitly not done**: no threshold grid, no new signal family, no name removed, no watchlist expansion, no filter derived from this result, no win rate promised. Intelligence's informational functionality is preserved and not relabelled as a recommendation anywhere.

7. **Live observation is not the sole programme**: the coverage-completion task above is concrete and bounded, independent of how many more live V2 trades occur.

8. **Journal/evidence links**: this entry + `../2026-09-12_task119a_corrections_integration/`; `docs/research/{TASK120_PROTOCOL_39NAME_SCOPE_REPLAY,TASK120_ECONOMIC_DECISION}.md` (this commit); `results/task120_39name_scope_replay/` (local).

Measurement improvement (Task 119/119A) is not evidence of profitability — this task's dashboard work created no edge and is not cited as if it did.
