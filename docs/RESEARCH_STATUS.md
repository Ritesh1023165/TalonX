# TalonX — Research Status

*Consolidated conclusions. Detailed evidence lives under `results/task*/` (mostly local-only,
gitignored) and `docs/research/TALONX_RESEARCH_LEDGER.md` (the append-only chronological history).
Nothing here is re-derived; this is a pointer index.*

## Headline

**No robust, cost-survivable free intraday *price/volume* structural-long alpha was found**
(Tasks 93–101B). The current Original strategy is deliberately selective and **UNPROVEN** — it
is not a profitability claim. The free intraday structural-long research lane is **CLOSED**.

**One non-price signal cleared the paper bar (Task 107B, 2026-09):** causally-observed
episodes of **≥ 2 distinct insiders buying on the open market** (SEC Form 4 code P, ≤ 10
trading-day window) → `TASK107B_FORM4_PAPER_CANDIDATE`. On a liquid / index-membership-grade
universe: +1.69 % mean net@20bps over 10 trading days, PF 1.67, discovery +1.81 % / holdout
+1.46 %, issuer-block **and** week-cluster 95 % CIs both strictly positive, SPY-excess +0.92 %.
This is a **paper** candidate, not a proven real-money edge. Frozen as `INSIDER_BUY_CLUSTER_V2`
(Task 109). The system's other realised value remains a descriptive human-in-the-loop **risk &
event intelligence** product.

## Task-by-task (chronological)

| task(s) | question | verdict |
|---|---|---|
| pre-90 (15-63, FPRC_V1 / ORPB_V1) | earlier candidate architectures | retired; evidence + freeze protocols kept (`results/task55…63r`) |
| **93** | is there any assessable edge in the frozen strategy across all available history? | `CURRENT_STRATEGY_EDGE_WEAK_OR_UNPROVEN` — 1 trade across 35 sym / 4.47M bars / 2025-01→2026-08; vol gate rejects 92.8% of bars |
| **94** | alpha discovery — 49 pre-registered event studies (volatility / volume / momentum / regime / intraday) | `ALPHA_DISCOVERY_NO_CANDIDATE_PASSED` — 0/49; volatility is not the lever; Task 93's confluence signal was an April-2025 artifact; best (opening drift +0.048 R@5bps) is sub-threshold ≈ round-trip cost |
| **95A** | do more regimes (2020-2026 Alpaca SIP, 25.8M bars) rescue the opening drift? | `INTRADAY_ALPHA_NOT_SUPPORTED_ACROSS_EXPANDED_REGIMES` — 0/5; opening drift *weakened* to +0.007 R@5bps; only `vol_low` regime helped but fails the cost burden; **binding wall = intraday drift ≈ 5 bps ≈ round-trip cost across ALL regimes / 6.6y** |
| **95B** | swing horizon (3-10d), split-adj daily | `SWING_ALPHA_NO_CANDIDATE_PASSED` — economics fine (drift ÷ cost 2.8-9.2) but 68 studies → 0; momentum & breakout NEGATIVE-excess (mean-revert at 2-3d); oversold/gap = 2020/2023 V-bottom artifact |
| **95C-D** | free earnings-event alpha (EDGAR `acceptanceDateTime` + XBRL first-filed) | `FREE_EVENT_ALPHA_NO_CANDIDATE_PASSED` — post-earnings reaction MEAN-REVERTS; actual EPS/rev growth adds no incremental info; point-in-time consensus (the untested high-evidence dimension) is not reachable free |
| **95E / 95G** | cross-sectional ranking (35-name survivor set → 620-name point-in-time S&P panel) | `BROAD_CROSS_SECTIONAL_ALPHA_NO_CANDIDATE_PASSED` — relative momentum INVERTS to significantly negative; breadth + survivorship control *strengthened* the negative |
| **95F** | free point-in-time universe feasibility | `FREE_BROAD_UNIVERSE_DATA_FEASIBLE` — S&P historical membership 2019-2026 from Wikipedia MediaWiki API (£0); 99.3% delisted-name coverage with correct exit-date truncation |
| **95H-I** | free deterministic filing-event alpha (no NLP) | `DETERMINISTIC_FILING_ALPHA_NO_CANDIDATE_PASSED` — 101 experiments / 0; the one solid signed effect (big Risk-Factors change → −67 bps @k5) is bad-news / risk info, not long-only entry |
| **95K** | can the deterministic NEGATIVE signals improve an independently-selected long book by exclusion? | `RISK_FILTER_NO_CANDIDATE_PASSED` — 63 experiments / 0; every flag's flagged-name forward return is still POSITIVE; **TalonX is not better at risk-avoidance than long-entry** |
| **95J** | alpha-program synthesis | 8 hypothesis spaces CLOSED; `FREE_ALPHA_SPACE_LARGELY_EXHAUSTED` · `AUTONOMOUS_ALPHA_STOP_CURRENT_MANDATE` · product = `RISK_AND_EVENT_INTELLIGENCE_SYSTEM` (human-in-the-loop, no autonomous-profit claim) |
| **96 (A-H)** | build the descriptive intelligence product | `DECISION_SUPPORT_PRODUCT_DESIGN_COMPLETE` → implemented: EDGAR event store, deterministic filing comparison, insider pipeline, explainable Information Significance, Telegram delivery, dashboard, MVP qualification. No predictive claim anywhere (CI-linted). |
| **97** | catalyst-displacement long lane | failed — no edge |
| **99 (A-L)** | restore & harden the live alert surface | Experimental lane restored (`TASK99A`); live intelligence bridge (`99B`); forward-outcome live wiring fix (`99G`); Telegram Markdown/entity escaping fix (`99H`); post-fix canary (`99I` — `PASS_NO_NATURAL_SETUP`); Task100 readiness audit + design closure (`99K`/`99L`) |
| **101A** | event-first structural candidate backtest & gate-expectancy | `EVENT_FIRST_GATE_INSIGHT_FOUND` — observability improved, but no net alpha; gate-expectancy insight recorded |
| **101B** | 15-min trend-gate counter-trend dip-reclaim | `TREND_GATE_LEAD_REJECTED` · `CLOSE_FREE_INTRADAY_STRUCTURAL_LONG_RESEARCH` |
| **106A** | is a catalyst × gap × RVOL × multi-day "V2" lane new? | `TASK106A_ABORT_ALREADY_TESTED` — it IS Task 97 Stage A Group A (`EXACTLY_TESTED`) + Task 95D (`MATERIALLY_EQUIVALENT`), both already rejected; audit only, no backtest run |
| **107A** | is a broad insider open-market buy-cluster study feasible on free data? | `TASK107A_FORM4_FEASIBLE_WITH_LIMITATIONS` — SEC Form 3/4/5 bulk 2019Q1-2026Q1 (£0): 207,864 code-P purchases / 7,113 issuers; 16,511 causally-datable ≥2-distinct-owner episodes; 810 in the survivorship-correct panel, ~14,822 priced broad. 95I's n=15 was a 35-mega-cap filter artifact, never a rejection |
| **107B** | do ≥2-distinct-insider open-market buy clusters predict positive +5/+10/+15d long returns? | **`TASK107B_FORM4_PAPER_CANDIDATE`** — pre-registered (`a9ceefc`) before outcomes. In-panel +10D: net@20 **+1.69 %**, PF 1.67, disc +1.81 % / hold +1.46 %, bootstrap CI [+1.0 %, +2.4 %] **and** week-cluster CI [+0.17 %, +2.0 %] both > 0, SPY-excess +0.92 %, all 10 frozen gates pass. Broad universe corroborates sign (net +0.60 %, bootstrap CI lower > 0) but is ≈ small-cap beta with a −80 % P&L drawdown → V2 is scoped to the liquid universe |
| **109** | freeze the paper V2 spec | `TASK109_V2_FROZEN_READY_FOR_INTEGRATION` — `INSIDER_BUY_CLUSTER_V2`, long-only paper, entry next-session-open after the 2nd insider's filing, exit +10 td, liquidity-gated universe, max 20 concurrent. V1 preserved as `ARCHIVED_BASELINE`. No code implemented; Task 110 not started |
| **110** | integrate V2 into the Original paper flow | `TASK110_V2_INTEGRATION_PASS_WITH_FINDINGS` (`8b69f8e`) — new isolated `talonx_v2/` package = `INSIDER_BUY_CLUSTER_V2@1` selectable profile through Quant→Brain→Original-paper-engine→official-dispatch→dashboard→EOD on `talonx:v2:*` + `v2_lane.db`. V1 preserved bit-for-bit (zero diff to the 5 frozen services); only 1-line touch = `external_boundary.py` OFFICIAL family. Default profile still `ORIGINAL_V1` |
| **111** | offline end-to-end replay qualification | `TASK111_V2_E2E_REPLAY_PASS_WITH_FINDINGS` (`cc09211`) — integrated path proven; whole-universe replay 188,448 code-P records → 15,842 episodes → ~2,158 entries/exits at real +10td holds; Redis wire round-trip; Original fingerprint `2ae6216bca70` byte-identical; restart-under-load + dispatch-dedup + dashboard pass |
| **112** | final safety, release freeze & Tuesday prep | `TASK112_TUESDAY_RELEASE_READY_WITH_FINDINGS` (`1840e8c`) — frozen release: V2 fp `11107198c5b81237`, V1 fp `2ae6216bca70` unchanged, $300k local paper, no V2 EOD flatten, bounded exit fall-forward (`TASK112_EXIT_FALLFORWARD_SAFE`), `talonx_v2.run --mode live` companion + supervisor `include_v2` opt-in + read-only `:8787` V2 section. 104 V2 tests + 1,557 regression pass. `TASK103_SUPERSEDED_BY_V2_FULL_DAY_QUALIFICATION`; successor `TASK113` (Tuesday 2026-09-08) prepared, NOT started |
| **112R** | frozen release rehearsal & research↔runtime parity | `TASK112R_TUESDAY_RELEASE_CONFIRMED_WITH_FINDINGS` — Tuesday SHA **`d78faa0` unchanged**, no runtime/strategy code touched. 11 gates: G2a reproduces the frozen `analysis.json` bit-for-bit; **G1 P1** — the Task 107B research code (`build_episodes`) enters after the *last* window filing while the Task 109 contract / runtime fire at the *2nd distinct insider*. Runtime is contract-correct; **re-evaluated on the exact runtime semantics (G2b) the paper-candidate gate still fully passes**: net@20 **+1.01 %** (was +1.69 %), PF **1.34** (was 1.67), disc +0.64 % / hold +1.66 %, issuer-block CI **[+0.31 %, +1.75 %]** & week-cluster CI **[+0.44 %, +2.17 %]** both > 0. **Operator-facing expectancy corrected to +1.01 %/10 td.** G3–G11 (full-day E2E, +10 lifecycle, restart campaign, capacity, failure isolation, Experimental isolation, runbook ×2, 800-tick soak, observability) all PASS. P0 = 0, open P1 = 0 |
| **112S/T** | Sunday readiness audit + final operator readiness | `TASK112S_TASK113_PREFLIGHT_READY_WITH_FINDINGS` + `TASK112T_TUESDAY_OPERATOR_READY_WITH_FINDINGS` — read-only, no commit, HEAD stays `1686d1f`, Tuesday release stays `d78faa0`. Delivered `TUESDAY_OPERATOR_SHEET.md` (A→U) + 14 supporting files, 47 commands validated (0 invalid). Key finding **T1 (P2)**: the supervisor `include_v2` path reads the stale 2026-03-31 research parquet — V2 live **must** run as the companion `talonx_v2.run --mode live --form4-source insider`. P0 = 0, P1 = 0 |
| **113** | Tuesday full-day V2 live paper qualification (2026-09-08) | **`TASK113_FULL_DAY_PASS_WITH_FINDINGS`** — Operational `TUESDAY_V2_OPERATIONAL_PASS_WITH_FINDINGS`, Prospective `NO_NATURAL_V2_SIGNAL` (0 code-P open-market insider filings all session → no cluster candidate). Full XNYS session: 178 companion ticks, 0 unplanned restarts, market feed HEALTHY through close, ending V2 cash **$300,000.00** (0 buys/sells/positions). **A P1 was found during setup and fixed before open**: `d78faa0` replayed a ~3-week-old historical ABCL cluster into the fresh $300k ledger on tick 2 (`V2Service.tick` staleness guard self-disarmed after its own tick-1 `SKIPPED_ENTRY_STALE` record; `process_episode` only treated `ENTERED` as terminal). Fix **`54c9b40`** (pushed, replaces `d78faa0`): stale episode always excluded every tick + `SKIPPED_ENTRY_STALE` terminal — plumbing only, **V1 fp `2ae6216bca70` + V2 fp `11107198c5b81237` unchanged**, `max_entry_staleness_sessions` stays 3; full pytest 4,225 pass / 0 fail. Mid-day P2 (companion `heartbeat_ttl_s 180` < `--tick-seconds 300` → dashboard flap) fixed by restarting the companion with `--tick-seconds 150`. Open P0 = 0, P1 = 0 |
| **114** | unified V2 dashboard + autonomous Day-2 operator | `TASK114A_PASS_WITH_FINDINGS` + `TASK114B_PASS_WITH_FINDINGS` → `TASK115_AUTONOMOUS_DAY2_READY_WITH_FINDINGS`. Operational/observability only — **no strategy semantics, no fingerprint change, dashboard read-only, `v2_lane.db` never reset**. **114B** new `talonx_ops/prospective/` deterministic operator: `python -m talonx_ops.prospective {start\|close\|status\|checkpoint}` — morning one-command (preflight + start supervisor + V2 companion `--form4-source insider` + 30-min checkpoint daemon), unattended day (machine-readable checkpoints + `events.jsonl`, CRITICAL-only alerting on locked-invariant breaches), evening one-command (reconcile + report + graceful shutdown, `v2_lane.db` **copied never moved**). Ledger-continuity guard **fails closed**. **B5** health heartbeat decoupled from the strategy tick in `talonx_v2/service.py` (`--heartbeat-seconds`, lightweight write every 30 s) — fixes the Task 113 P2 without touching trading semantics. **B6** logical Telegram-owner check (network PIDs, shim-aware). **114A** dashboard: Active V2 first-class on the Overview, V2 paper ledger + lifecycle on the V2 section, near-miss funnel (Form 4 → code-P → clusters → stale/fresh-eligible → BUY/SELL, observational only), health/data/activity separated, EOD `NOT_DUE_YET` vs `STALE`. Offline rehearsal: 9/9 scenarios PASS. Tests: `test_task114_prospective.py` 32 pass + 263 broad targeted. Deferred (P3): full nav re-org, Intelligence table, Experimental forward-outcome audit, 1-min warm-up classes, :8770 parity. `<FINAL_SHA>` |

## What is preserved for future work

The backtest engine, replay tooling, causal pre-roll, cost/friction models, point-in-time
universe reconstruction, delisted-name handling, survivor-bias controls, forward-outcome tooling,
and every dataset + preregistration + final report — see `results/task105_repository_cleanup/backtest_preservation_manifest.md`.
`docs/BACKTESTING.md` explains how to run a materially new hypothesis without leaking future
information.

## What is NOT reopened

Free intraday structural-long alpha (cost wall). Broad price/volume cross-sectional ranking
(signal wall). Autonomous-profit framing (product decision `95J`). Reopening any of these
requires a **materially new data or feature class** (point-in-time paid consensus, options,
non-price information) and a separate authorised mandate — not a parameter sweep.

The **non-price-information lane** was exercised under that clause in Task 107B (SEC Form 4
insider open-market buying) and produced the `INSIDER_BUY_CLUSTER_V2` **paper** candidate.
That is a paper-validation result, not a real-money edge; it does not reopen the price/volume
lanes above.
