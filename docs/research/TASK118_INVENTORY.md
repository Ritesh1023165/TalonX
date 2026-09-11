# Task 118 profitability baseline — dataset inventory & prior-rejection summary

Isolated research worktree `C:\workspace\TalonX-task118-profitability`, branch
`research/talonx-profitability-2026-09`, forked from
`research/talonx-strategy-validation-framework` @ `a3b6f58` (carries
`talonx_research/`, the permanent validation infra). The 5 frozen V2 strategy
files (`talonx_v2/{config,cluster_engine,liquidity,quant_bridge,brain_bridge}.py`)
were verified **content-identical** to the accepted release (fingerprint
`11107198c5b81237`) — see "Fingerprint verification" below. No parameter
tuning, no promotion, no broad optimisation performed here.

## 1. Fingerprint verification (done, not a merge)

`v2_release_fingerprint()` on this worktree initially returned
`ea2c686ed5ecda37` — different from the release's `11107198c5b81237`. Root
cause: a `diff` with `\r` stripped from both sides showed the 5 frozen files
were **byte-identical in content**; the only difference was line endings
(`git worktree add` checked this worktree out LF, the release worktree CRLF,
despite `core.autocrlf=true` in both) — a checkout artifact, not a strategy
divergence. Per this task's explicit guidance ("do not broadly merge
release/research branches merely to synchronize a fingerprint"), the fix was
a **narrow, explicit copy** of the 5 frozen files' bytes from the release
worktree (not a git merge). Re-verified: fingerprint now
`11107198c5b81237`, matching exactly. `git status` shows nothing to commit
(the tracked content was never actually different at the git level — only
the on-disk checkout was).

## 2. Existing datasets (isolated, already built — no new collection needed for baseline A)

| dataset | coverage | source task |
|---|---|---|
| `results/task116_*` frozen V2@1 2-yr replay | code-P clusters, 2024-09-01→2026-03-31 (price side ends here), N=170 episodes, chronological portfolio | Task 116 |
| `results/task111_v2_e2e_replay/*` whole-universe replay | 188,448 code-P records → 15,842 episodes → 2,158 entries | Task 111 |
| Task 107B/109 discovery+holdout panel | Form4 code-P open-market buy clusters, prereg `a9ceefc`, eval `625325a` | Task 107B |
| `talonx_research/` immutable `StrategyRegistry` + `replay_engine` | drives the REAL `V2Service.tick()` chronologically; physically refuses to open `v2_lane.db` | Task 115 |
| `%USERPROFILE%\.talonx\ingestion_ledger.db` (isolated copy required — NEVER the live file) | full SEC Form 4 ingestion history (InsiderStore), same source `V2Service(form4_kind="insider")` reads live | Task 96B/96D |
| Original intraday candidate/rejection history | `dispatch_audit.rejected_candidates`, `dispatch_audit.alerts` — 5 real gates only (volatility/us_session/opening_blackout/confluence/trend); NO throttle/cooldown/revalidation records exist anywhere (Task 117 §4 finding) | Task 100B onward |
| Experimental paper trades | `exp_alerts.db` / `experimental_trades` — isolated validation-only, no real capital | Task 99A |

## 3. Prior-rejection history (do NOT repeat without a new justified hypothesis)

| task(s) | family | verdict |
|---|---|---|
| 93 | frozen-strategy baseline edge | `CURRENT_STRATEGY_EDGE_WEAK_OR_UNPROVEN` |
| 94 | intraday alpha discovery (49 studies) | `ALPHA_DISCOVERY_NO_CANDIDATE_PASSED` |
| 95A | expanded-regime intraday | `INTRADAY_ALPHA_NOT_SUPPORTED_ACROSS_EXPANDED_REGIMES` |
| 95B | swing (3-10d) | `SWING_ALPHA_NO_CANDIDATE_PASSED` |
| 95D | earnings-event alpha | `FREE_EVENT_ALPHA_NO_CANDIDATE_PASSED` — post-earnings reaction MEAN-REVERTS |
| 95E/95G | cross-sectional / broad cross-sectional | `NO_CANDIDATE_PASSED` — relative momentum INVERTS negative |
| 95I | deterministic filing-event alpha (101 exp) | `NO_CANDIDATE_PASSED` — only signed effect is NEGATIVE |
| 95K | risk-filter (63 exp) | `NO_CANDIDATE_PASSED` — every flagged-name forward return is POSITIVE (TalonX not better at avoidance than entry) |
| 97 | catalyst-displacement (8-K × gap/RVOL) | `NO_CATALYST_LONG_EDGE_FOUND` — reproduces 95D's inversion |
| 106A | "V2"-shaped catalyst×multi-day | `ABORT_ALREADY_TESTED` — exactly Task 97 + materially Task 95D |
| **107B/109/112R/115/116** | Form4 ≥2-distinct-insider open-market buy cluster | **the one candidate that cleared the paper bar** — frozen as `INSIDER_BUY_CLUSTER_V2`, this is the strategy being baselined here |

**9 free-data alpha spaces closed** (95J synthesis). The only surviving
candidate is the frozen V2 rule itself — deliverable A below measures it, it
does not search for a replacement.

## 4. Frozen 39-name membership manifest

Resolved via `python -m talonx_ops.watchlist_coverage` (read-only,
`intelligence.service.scope.resolve_watchlist`) on **2026-09-11** (this
resolution date, from the release-branch worktree — the research worktree has
no independent watchlist config, it reads the same live `~/.talonx` config as
production, read-only):

```
AAPL ABCL ABT ACHR ADC ADP AFL AGNC AMAT AMD AVGO BAC BLK C CSCO CVX DELL
GOOGL IBM INTC JNJ JPM KO MA MCD MSFT MSTR NUE NVDA ORCL PG PYPL SHOP STX
TSLA UNH V VRT WMT
```
(39 names, alphabetical.) 4 configured-active names are resolved but
**excluded** (non-SEC-filers): BABA (20-F/6-K foreign filer), BLSH (no
domestic filing history), SKHY (Korean issuer, no SEC domestic filings), SPCX
(private, no SEC reporting). CIK-per-ticker cross-reference is deterministic
via the same `scope.py::resolve_watchlist(watchlist_store, directory)` call
— not re-derived by hand here to stay within tonight's bound; the first
deliverable-A run should capture it alongside the replay for full
attribution.

**This is the CURRENT watchlist, applied here as of today's resolution — a
`DIAGNOSTIC — RETROSPECTIVE WATCHLIST` when used against historical episodes
(selection / survivorship bias), never the headline number** per the
contract's promotion criteria.

## 5. What deliverable A (exact 39-name baseline) needs, not yet run

- Frozen membership list above (done).
- The isolated `ingestion_ledger.db` copy (a fresh `shutil.copy2`, never the
  live file, never re-used across sessions without re-copying).
- `talonx_research/replay_engine` driving `V2Service.tick()` chronologically,
  `form4_kind="insider"`, `execution_allowlist=<the 39 names>`, 20 bps
  round-trip cost, discovery/holdout split re-stated from Task 107B/112R.
- Price history: parquet side currently ends 2026-03-31 (state this limit,
  do not extrapolate).

Not run tonight — this file is the inventory step only, per the contract's
ordering (inventory → frozen membership → *then* the baseline run).
