> **Corrections (Task 122, 2026-09-13):** (a) point 7 below calls the
> execution sensitivity "full chronological repricing" — this overstates
> what was computed. It genuinely recomputed shares/P&L from the delayed
> fill price (not a constant subtraction), but held the exit price/reason
> fixed and did not re-derive downstream occupancy/cooldown effects on
> later candidates. Correct label: a **per-trade repricing sensitivity**,
> not a fully chronologically-propagated portfolio simulation. (b) no
> point below reports daily marked drawdown — none was computed. Ending
> equity ($99,155.10, point 6) is a single balance at the window's end,
> **not** a drawdown figure, and must not be read as one. Full detail:
> `docs/research/TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md`. The
> underlying trade-level numbers and the decision are unchanged.

1. **Verdict and SHAs**: Part 1 `RECONCILIATION_VERIFIED_COMPLETE`; Part 2 `ROOT_CAUSE_CONFIRMED_FIX_VERIFIED`; Part 3-6 `RUN_COMPLETE_AS_PREDECLARED`; Part 7 **`INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`**. Release verified `f28986999eec5e313cfc89db24e4dbacfb378891` — unchanged, research-only. Research `2239b21` → **`<this commit>`**, pushed.

2. **First-month reconciliation**: 33 entries = 33 closed trades = **0 open positions** — verified, not assumed, that Task 121A's +$61.92 net figure IS the complete portfolio profit for that month (equity = ending_cash exactly). Decomposed: gross +$103.19, spread cost −$41.27 (matches 33×$1.25 exactly), net +$61.93. 7 wins (avg +$75.66) / 26 losses (avg −$17.99), max hold 6.98 days, 42% overnight-crossing.

3. **Reliability**: root cause CONFIRMED (not assumed) via a controlled 2-week reproduction — an **O(n²)** rejection-summarization pattern in the old adapter (118,112 rejection records × itself ≈ 1.4×10¹⁰ operations on just 2 weeks; tens of billions on a full month). Task 121A's own guess (unbounded published_log — actually only 14 rows) was disproven. Fixed with a new adapter using durable, incremental SQLite telemetry + a single O(n) pass. **Fix verified**: the same 2-week window completed in 2,966.7s (vs. the original's indefinite hang) under the fix. 9 new tests, all pass.

4. **Extended window/continuity/runtime**: full Segment A_broad, **2025-01-24→2025-08-14 inclusive**, all 35 symbols, run as ONE continuous replay from its own start (no checkpoint existed, per Part 4 not resumed/stitched). **2,565,682 bars**, backtest **40,633.7s (~11.29 hours)**, summary **~181s** (bounded — the fix held at full production scale, not just the small verification).

5. **Signal/entry/exit accounting**: 46,905 raw candidates → 1,934 published (261 bullish, 67 bearish) → 229 OPENED, 32 SKIPPED_POSITION_ALREADY_OPEN, 67 BEARISH_PUBLISHED_WHILE_OPEN (no action), 1,606 NO_ACTIVE_POSITION — every published signal reconciled exactly by direction and disposition (no aggregate-count inference, Task 121's original limitation). 227 closed (183 stop_loss, 44 target_exit, fine-grained), 2 open/unresolved (GOOGL, MU — both marked, both included, neither excluded as "open losers" since both are currently small unrealized gains).

6. **Net economics/equity/drawdown**: gross P&L **−$612.92** (negative BEFORE any cost), spread −$283.53, **net −$896.44**, PF **0.764**, win rate **19.4%**, net expectancy **−$3.95/trade**. Equity **$99,155.10** (cash $94,103.56 + marked open value $5,051.54) → total portfolio P&L **−$844.90**. Drop-top-issuer (LRCX): worse, −$5.33/trade. Split-half: first 113 trades −$10.97/trade, last 114 +$3.01/trade (real disclosed heterogeneity).

7. **Execution sensitivity/uncertainty**: next-bar-close fill sensitivity (full chronological repricing, 0 trades dropped) → −$927.91 total (−$4.09/trade), MORE negative, sign unchanged. 95% issuer-block bootstrap CI (5,000 reps, seed 121121, 35 issuers): **[−$8.94, +$1.06]/trade**.

8. **Decision**: **`INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`** — per the protocol's own predeclared, symmetric ±$1.25/trade materiality rule, neither ADVANCE nor REJECT is cleared (CI upper bound $1.06 stays just inside the band despite a clearly negative point estimate/gross P&L/PF). **Exact blocker**: 35 issuer-groups is the ENTIRETY of the available same-population historical data (Segment B is a different, out-of-scope dataset) — further backtesting of this exact question on this exact data is exhausted. **ONE next action**: do not run another historical backtest of this population; if further resolution is wanted, it requires a genuinely new information source (continued live forward-observation under the now-corrected exit lifecycle) — a live-operations decision, out of this research-only task's scope to enact, not automatically proposed as "run it again."

9. **Limitations/production preservation**: the CI's failure to clear the materiality band is a real, named, small-sample-group limit, not minimized. No release-branch change; no application process left running (verified after full-run completion and temp-file cleanup); Redis/production DBs untouched.

10. **Journal/reports**: `entries/2026-09-12_task121b_extended_replay_decision/` + `docs/research/{TASK121B_FIRST_MONTH_RECONCILIATION,TASK121B_RELIABILITY_FIX,TASK121B_EXTENDED_PROTOCOL,TASK121B_EXTENDED_EXPERIMENTAL_RESULTS}.md` + `docs/research/evidence/task121b/*` — all at this commit, pushed.

Priority followed as instructed: reliable fixed run → complete portfolio economics → decision. The completed run's own weight of evidence leans negative; the formal statistical bar it does not quite clear is reported honestly as the reason, not concealed behind either an automatic reject or a false "inconclusive-and-neutral" framing.
