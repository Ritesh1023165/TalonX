Saved verbatim, as received. No subsequent steering messages were sent
during execution of this task (single-turn request).

---

TASK119 — ATTRIBUTABLE PAPER-PERFORMANCE DASHBOARD

OBJECTIVE
Implement the selected per-lane paper-performance surface in the existing
dashboard. Make it easy to see what each lane earned/lost, what remains
open, which prices were used, and whether accounting reconciles.

Complete the implementation, tests and rendered acceptance.
Do not stop at a design or another audit.

BASELINE — VERIFY
Release branch: research/talonx-strategy-validation
Last deployed code: 5c0b3f3ccfef45ff8438e75f8f614b738deefc9a
Reported release docs: d4177b3
Research branch: research/talonx-profitability-2026-09
Latest reported research commit: 8829f55

[Full verbatim prompt as sent this turn, covering: PROTECTED STATE
(existing production ledgers/campaign history unchanged, SPCX read-only,
V2 fingerprint/cash/no-positions unchanged, existing strategy/scope/
sizing/thresholds unchanged, Redis retained/untouched, no application
session launch/external messages/broker calls, build against isolated
consistent database copies, no writable store against production); PART
1 (reuse the existing product -- extend the existing paper view and
DashboardReadModel, no second dashboard/ledger/accounting engine/
duplicate tab, authoritative lane-specific sources, Intelligence has no
invented paper ledger, PIV separately labelled); PART 2 (clear per-lane
summary -- lane/strategy identity, session/campaign period, starting
capital + period, cash, open-position count/cost basis, marked value,
realized/unrealized P&L, costs, equity, reconciliation status, valuation
timestamp/source/session; today vs campaign distinct; equity = cash +
marked open-position value; use the ledger's actual cost convention, no
double fee deduction, no inferred starting capital; label
insufficient/unavailable metrics explicitly; no return % without a valid
denominator; no new performance statistic solely for visual completeness);
PART 3 (open positions and closed trades tables -- symbol/lane, entry/exit
times, quantity/cost basis, mark + timestamp/source/session/freshness,
unrealized P&L gross/net, last exit evaluation, pending obligation; exit
reason, recovery-affected flag with plain-language explanation; provenance
CONFIRMED/UNKNOWN, no inferred clean execution, no mutating old trades);
PART 4 (Friday reconciliation fixture -- Original 0 publications, V2
$300,000/0 positions/ABCL stale episode preserved, Experimental 5 campaign
entries Sept 9-10 / 4 Sept-11 exits / 1 remaining position, realized
-324.4662160270568, four recovery-affected closes, SPCX mark $151.2100 @
20:08:00Z ~+$50.30 unrealized labelled POST-CLOSE not an official
regular-session closing price, reconcile against raw ledger values not
copied summary text); PART 5 (reconciliation and empty states -- lane
ledger accounting / price-valuation completeness / session EOD state /
base-PIV reconciliation shown independently, zero positions is valid,
missing mark is unavailable not zero, closed market is not automatically
a feed failure, no trades means win-rate/PF unavailable not 0%/infinity);
PART 6 (validation and real SPA acceptance -- focused tests for lane
separation/session-vs-campaign/equity-with-marks/cost handling/missing-
stale-marks/post-close-vs-regular-close/recovery provenance/reconciliation
states/no production writes or network sends; render the actual dashboard
SPA against isolated copies for 6 named scenarios, inspect screenshots for
readability/clipping/labels/timestamps at a realistic screen size, trace
displayed values to source fixtures in a reconciliation table, label
fixtures isolated, do not claim live acceptance from fixtures, do not
start the production stack for screenshots, avoid broad unrelated
testing -- run changed-surface regressions and disclose unrelated
failures accurately); PART 7 (delivery and next-session candidate --
commit on the appropriate release/hotfix branch, push normally, no main
merge/force-push, the output is a candidate not an automatic activation,
do not restart the closed application or launch Monday's session, provide
exact SHA/migration requirement/rollback procedure/next-session
verification steps/known limitations, preserve SPCX's outstanding
obligation and pending notifications, do not reset campaign capital or
clear old positions); PART 8 (journal and stopping rule -- TASK119 journal
entry with exact prompt/response, starting/final SHA, source mapping and
accounting definitions, changes/tests/rendered evidence,
production-preservation checks, limitations and next-session-candidate
status; publish TASK119_PAPER_PERFORMANCE_ACCEPTANCE.md, field/source
reconciliation table, sanitized screenshots, candidate
activation/rollback notes; no secrets/production databases/bulk private
data in git; complete when the existing dashboard accurately presents the
defined lane outcomes, do not expand into cosmetic redesign or another
series of dashboard tasks; end with the unresolved economic question and
one bounded next research action from the established programme, no new
strategy tuning here) -- exactly as sent this turn in this session. Not
re-transcribed a second time here to avoid a transcription divergence
from the original; see this session's own transcript for the byte-exact
text.]

FINAL RESPONSE
1. Verdict: PAPER_PERFORMANCE_SURFACE_ACCEPTED / PARTIAL / BLOCKED.
2. Starting/final SHA and push result.
3. What users can now see in the actual dashboard.
4. Friday reconciliation, including SPCX's post-close valuation label.
5. Tests and rendered acceptance.
6. Production/Redis/process preservation.
7. Next-session candidate and remaining gates.
8. Economic limitations and next research action.
9. Journal, reports, screenshots and commit links.

Measurement improvement is not evidence of profitability.
