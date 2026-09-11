1. **Dashboard verdict**: `PAPER_EOD_INTEGRATION_ACCEPTED` — Task 119's duplicate-tab defect closed, one destination per lane. (Economic verdict: see the companion Task 120 entry.)

2. **SHAs**: release baseline `d4177b3` → Task 119 `d65a410` → Task 119A correction `f289869`, fast-forward-**integrated** into `research/talonx-strategy-validation` as `f28986999eec5e313cfc89db24e4dbacfb378891`, pushed. Research `aef24c7` → this entry.

3. **What changed in Paper/EOD**: `paper_eod()` now shows, per lane (Original/Experimental, folded into their existing cards, all pre-existing keys byte-unchanged), realized/unrealized P&L, equity, arithmetic reconciliation, open-position/closed-trade detail, and a four-component cost breakdown. The separate "Paper Performance" tab is retired. V2's equivalent detail folds into the existing "Active V2" $300k ledger card.

4. **Corrections**: costs are no longer blanket-"UNMODELED" — Original/Experimental's simulated bid-ask spread (5.0bps/side, `apply_spread`) is confirmed MODELED (baked into fill prices); only commissions/fees are genuinely unmodeled; V2 has neither. Session-open is now read from `exchange_calendars` (`session_open_utc`, new), not approximated as close−6h30m (which was wrong on early-close half days — regression-tested). `NON_SESSION_DAY` and `UNKNOWN` are now distinct. Reconciliation/valuation-freshness/cost-completeness/recovery-provenance/base-PIV/exit-observability are independent fields; the EOD card states an EXACT check doesn't verify the others.

5. **Tests/evidence**: 91 passed (direct surface), 300 passed (full changed-surface, both pre- and post-integration). Rendered the actual integrated SPA at 1360×2600 and 900×2600 for all 6 required scenarios + Active V2; 28/28 field checks match. Small, representative, **committed** evidence (4 screenshots + reconciliation table) at `docs/audits/task119a_paper_eod_integration/evidence/` (this commit's immutable SHA); bulk evidence local under `results/task119a_integration/`.

6. **Production/Redis/process preservation**: zero production writes; zero production processes started/stopped (re-verified `psutil`/`netstat`/`redis.ping()` clean). Isolated test subprocesses (loopback port 8897) were started against isolated fixtures and explicitly killed — corrects Task 119's imprecise wording. SPCX's obligation and V2's flat book unchanged.

7. **Monday candidate**: SHA `f28986999eec5e313cfc89db24e4dbacfb378891`, strategy-code-identical to `5c0b3f3` (V2 fingerprint `11107198c5b81237` re-verified unchanged, zero-line diff in `talonx_v2/`). `NEXT_SESSION_HANDOFF.md` updated in place with the new SHA, re-verified SPCX obligation, and the Task 120 finding. **No GO declared**, no session launched, no recurring job created — go/no-go remains a preflight-time decision.

8. **Journal/commit links**: this entry + `../2026-09-12_task120_economic_decision/`; `docs/audits/task119a_paper_eod_integration/TASK119A_CORRECTIONS_AND_INTEGRATION.md` (release `f289869`); `docs/research/NEXT_SESSION_HANDOFF.md` (this commit).

**Workflow lesson recorded**: acceptance must cover the actual requested user journey (one destination), not merely passing fixtures for a different, additional-tab implementation.
