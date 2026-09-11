# Task 118D Part 5 — remaining live evidence, read-only (2026-09-11, cutoff ~14:55–15:00 UTC)

Regular session (open since 13:30 UTC). All reads read-only (SQLite
`mode=ro`, live dashboard API); no production writes, no Redis mutation,
no external send by this investigation.

## A. Readiness

Live snapshot, `quant.db.bar_buffer` (1-minute, `min_bars_required=120`):
**24/43 symbols READY**, 19 not yet — all 19 actively climbing (64–105
bars, latest timestamps within the same minute as the check, ~14:50–14:53
UTC) — steady live accumulation during the regular session, several close
to threshold (e.g. CVX 105/120, UNH 95/120), consistent with continued
recovery from this morning's preseed gap (Task 118A/B), not a stalled
process.

`usable_coverage: 1.0` (dashboard) measures **price availability**
(`latest_prices` row count), **not** 1-minute-bar strategy readiness —
this distinction is stated explicitly, not inferred as "43/43 ready."
Today's `suppression_counts` (live): `LOW_VOLATILITY 983 across 24
distinct tickers` — **exactly the 24 currently-READY symbols**, cleanly
corroborating that the 19 not-yet-ready symbols have zero suppression
rows because they have not reached the gate yet, not because they were
evaluated and passed. No claim of a missed profitable opportunity is
made — no causal candidate/price evidence was sought for that claim.

## B. Experimental outcome — exact ledger reconciliation

Authoritative `experimental_paper.db` read directly (not the display log):

| ticker | side | exit | net_pnl | exit_reason | closed_at (ET) |
|---|---|---:|---:|---|---|
| VRT | SELL | $251.0872125 | **−$213.7186** | confirmed_bearish | 2026-09-11T07:53:51 |
| STX | SELL | $862.1094 | **−$25.3838** | confirmed_bearish | 2026-09-11T08:30:51 |
| AMD | SELL | $503.7540 | **−$8.2224** | confirmed_bearish | 2026-09-11T08:30:56 |
| BLSH | SELL | $34.1515 | **−$77.1413** | confirmed_bearish | 2026-09-11T08:59:27 |

Sum: **−$324.4662** — matches `portfolio_state.total_realized_pnl_usd`
(**−324.4662160270568**) **exactly**, and matches the reported −$324.46
figure. `win_count: 0, loss_count: 4` — all four are real, distinct SELL
rows (ids 6–9), no duplicates; `trade_history` has exactly 9 rows total
(5 BUY + 4 SELL), matching 4 closed + 1 still open.

**SPCX — confirmed still open** (authoritative `positions` table: exactly
one row, SPCX, unchanged since entry). **Unrealized P&L, timestamped**:
last observed reference price **$147.4500** (bar timestamp
`2026-09-11T14:34:18Z`, ≈25 minutes old at time of this check — reported
as such, not claimed fresh-to-the-second) vs. entry $148.2276 →
**unrealized ≈ −$13.11 gross** (no cost applied — position not closed).
This is a genuine, sourced observation, not a zero substituted for an
unknown value.

**Recovery-affected flag**: VRT, STX, AMD, BLSH are each the **first-ever
real exit** through the Task 118A exit-lifecycle fix (deployed today,
~11:54 UTC) — none existed as a working, tested-in-production path before
today. **These four closes should be read as first-live-validation of the
repaired mechanism, not as an established, multi-cycle track record of
the strategy's exit economics** — flagged explicitly, not presented as
clean prospective validation. All four are losses; no profitability claim
is made from them.

## C. Delivery — reconciled by domain

| domain | today's counters | note |
|---|---|---|
| Original/trading (`dispatch_audit.db`) | 0 alerts, 0 Telegram sends | correct — LOW_VOLATILITY-dominated funnel, 0 published upstream (unchanged since Task 118C) |
| Intelligence (`ingestion_ledger.db.intelligence_delivery`) | `SENT: 6` card rows = **1** actual Telegram message (`messages_sent_today: 1`) | unchanged since this morning's digest (message_id 720); no new sends this cycle |
| V2 (`v2_active_strategy.service.alert_outbox`) | `total: 0` | no V2 entry/exit signal today — nothing to deliver |
| Experimental | 0 external sends (structural boundary, confirmed) | 4 real exits + entries today, zero Telegram — by design |

The ping/dashboard's generic health label reflects the **Original**
domain specifically (matching Task 118C's finding) — this is documented
here again, not changed; no application code was touched to "fix" the
label, per this task's own instruction.

## D. Incident carryover — kept unresolved

Task 118C's two open items are **not** resolved by anything found in this
task: the exact producer-write-vs-reader-read locus of the 14:29:18Z
heartbeat lapse, and the historical "45 candidates" counter's source
query. No new preserved evidence surfaced either. Per instruction, no
arithmetic residual is assigned to an assumed category.

## Evidence

Live `:8787` API reads (`overview`, `v2_active_strategy`, `intelligence`,
`validation`), `quant.db` (`bar_buffer`, `suppression_counts`),
`experimental_paper.db` (`positions`, `trade_history`, `portfolio_state`)
— all read-only, this session, cutoff ~2026-09-11T14:55–15:00 UTC.
