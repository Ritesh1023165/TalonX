Saved verbatim (condensed), as received. Single-turn request.

---

TASK120A–C — OVERNIGHT ECONOMIC BASELINE CORRECTION AND NEXT DECISION

OBJECTIVE
A. Correct Task120's factual, coverage and cost errors.
B. Produce a reproducible chronological V2 baseline using the existing
   replay engine and available historical data.
C. Close the exact-contract evidence question for Original/Experimental
   and select ONE next economic action.

Dashboard work is accepted and closed. Do not reopen it. Prioritize
computed evidence and a decision over extensive documentation.

[TASK A summarised: A1 correct the historical/live confusion -- the
earlier N=10 -2.926% result is a historical replay 2024-09-01..2026-03-31,
NOT live trades; Friday's live ledger had zero trades; preserve original
claims with explicit superseding corrections. A2 distinguish episode
studies (runtime_episodes/build_returns) from chronological portfolio
replay (V2Service.tick()) -- label accordingly, withdraw unsupported
"first properly powered"/"fully representative"/exact-runtime claims. A3
freeze scope and data windows -- frozen 39-name manifest with provenance,
no re-resolving inside each replay, determine actual usable filing/price
coverage, distinguish before-listing/missing-ticker-mapping/missing-
price-file/missing-sessions/missing-filing-history/incomplete-horizon.
A4 resolve coverage before downloading -- inspect ALL existing sources
(not just _daily), reconcile ABCL/ACHR/ADC/AGNC/MSTR/SHOP specifically
(MSTR occurred in the earlier baseline -- explain), produce a
symbol|source|interval|missing-sessions|corporate-action-basis|action
table, no fabricated bars, no silent exclusions. A5 reconcile costs --
trace headline/CI code paths, verify the 2x20bps fallback, use one
explicit 20bps-round-trip convention matching Task118, publish
gross|entry-cost|exit-cost|total-cost|net, verify applied once, add
focused tests.]

[TASK B summarised: B1 reuse the established talonx_research replay path
driving V2Service.tick() chronologically, record exact
versions/hashes of service/adapter/store/calendar/pricing/scope/frozen-
strategy modules, five-file fingerprint equality alone insufficient, no
broad branch merge, narrow reproducible synchronization only. B2
establish the overlap regression first (2024-09-01..2026-03-31 vs the
earlier ten-trade baseline, episode IDs/dispositions/BUY-SELL
pairs/dates/prices/costs/net P&L/open-unresolved, row-level explanation
if it differs, no tuning to force agreement). B3 run the longest
supported historical window once overlap is understood, preserving
causal filing availability/lookback, eligibility/liquidity/cooldown/
position-limit/holding-period rules, date-only filing limitations,
realistic incomplete-terminal-horizon treatment; use $300,000 campaign
capital as primary, retain $10m only to isolate capital constraints;
reference-model fills are not proof of executable prices, keep explicit,
do not rewrite the trading contract. B4 publish complete accounting
(records/clusters/evaluated/eligible/entered/closed/BUY/SELL/open/
unresolved), sanitized episode-disposition table, trade table, coverage
exclusions, gross/cost/net reconciliation, daily marked equity where
supported (equity = cash + marked open value, never portfolio_cash_after
or a cumulative-return sum), trade frequency/zero-entry periods, net
expectancy/win-rate/PF, dollar P&L/marked drawdown, distinct
issuers/concentration, data completeness/unresolved valuations. B5
dependence-aware uncertainty fixed before seeing results, N is not proof
of adequate power, report effective independent groups, this history has
already been investigated (do not relabel an untouched holdout), no
automatic V2 promotion or scope expansion.]

[TASK C summarised: C1 verify prior-study equivalence narrowly for the
EXACT current Original/Experimental contract after costs (candidate
trigger/indicators, gates/timeframe, configured-universe coverage, entry
timing/price, stop/target/holding/session-exit policy, costs/portfolio
constraints/data window, live runtime vs reconstructed logic) -- Task95A's
opening-drift finding does not automatically prove every current contract
evaluated; conversely do not rerun a genuinely equivalent rejected study.
C2 complete one bounded outcome: ROUTE1 (exact/sufficiently-equivalent
evidence exists -- cite, don't rerun), ROUTE2 (material gap, existing
data/replay support available -- run ONE frozen baseline for the lane
best able to advance the product, chosen before inspecting outcomes, no
threshold grid/new signal family/post-hoc removal), ROUTE3 (essential
data/capability missing -- identify exact gaps, prepare the smallest
reproducible next action, do not build a new framework overnight). Keep
research separate from the four recovery-affected live exits. C3 return
ONE of ADVANCE_ONE_CANDIDATE_TO_FURTHER_VALIDATION /
REJECT_CURRENT_CONTRACT_FOR_THE_REQUESTED_USE_CASE /
INSUFFICIENT_EVIDENCE_WITH_ONE_SPECIFIC_NEXT_ACTION, explaining user
requirement/opportunity frequency/net evidence/unknowns/why the next
action is informative/acceptance-rejection conditions -- no new
volatility filter off the same ten trades, no automatic Experimental
Telegram enablement, no claim every free-data strategy is exhausted, no
years-long-wait-only recommendation.]

[PRODUCT CONTRACT/DOCUMENTATION small update; JOURNAL/PUBLICATION one
overnight parent entry with Task120A/B/C outcomes; STOPPING RULE as
specified -- see full prompt for exact text, not re-transcribed a second
time to avoid divergence.]

MORNING RESPONSE (required, 10-point)
1. Separate verdicts for A, B and C.
2. Starting/final SHAs and push results.
3. Corrections to the N=27 study.
4. Six-name coverage reconciliation and actual historical window.
5. Overlap comparison against the earlier ten trades.
6. Expanded chronological results: trades, costs, net P&L, equity and uncertainty.
7. Original/Experimental exact-contract evidence decision.
8. ONE next task with acceptance criteria.
9. Production state preserved; no application session launched.
10. Journal, reports and immutable commit links.

A negative or inconclusive result is an acceptable research outcome. An
unreconciled number presented as a definitive baseline is not.
