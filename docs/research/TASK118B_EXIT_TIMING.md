# Task 118B Part 1 — VRT exit chronology (2026-09-11)

**Verdict: VALID_UNDER_EXISTING_PAPER_POLICY.** This is a paper-model fill
(a simulated execution against a real, sourced, dated market data point),
**not** evidence of an executable market fill and not presented as one.

## Correlated trace

| field | value | status |
|---|---|---|
| Position id (display log `trade_id`) | `Xb3e23f52268a897f` | directly observed |
| Position id (authoritative `trade_history.id`) | BUY id=1, SELL id=6 (same `experimental_paper.db`) | directly observed |
| Entry state | 9.105526899952618 sh @ $274.5585, opened 2026-09-09T15:03:34.471751Z, stop $273.6548 | directly observed |
| Market event / Redis stream id | **unavailable** | `talonx:market:stream` is plain Redis Pub/Sub (`pubsub()`, not `XADD`/consumer-group streams) — messages carry no persisted, individually-addressable id; none is recoverable after the fact |
| Provider timestamp semantics | `2026-09-11T07:53:51-04:00` = the **last available 1-minute intraday bar's own index/label** from yfinance's historical-bar endpoint for VRT, at the moment of a post-restart re-fetch — a **bar timestamp** (standard yfinance convention: intraday bars are indexed by bar **start**), not a wall-clock publish time or a quote-request time | directly observed (see corroboration below), with the start-vs-end labeling convention **inferred** from documented yfinance behavior, not independently re-derived from raw provider bytes here |
| Ingestion/publication timestamp | not separately logged (plain Pub/Sub, no delivery-id log) | **unavailable** |
| Consumer processing timestamp (wall clock) | `2026-09-11T12:55:28.532+01:00` = **2026-09-11T11:55:28Z** — the experimental component's own log line: `experimental paper SELL VRT @ 251.0872 (stop_loss, ...)` | directly observed |
| Exit decision timestamp used for `closed_at` | `2026-09-11T07:53:51-04:00` (11:53:51Z) — the **tick's own embedded timestamp**, per this fix's own explicit design (`eval_ts = price_ts or now`, preferring causal time over wall-clock) | directly observed (design), confirmed applied |
| DB persistence | atomic within `PaperTradingStore.execute_sell` (one lock, one commit) — `positions` row deleted, `trade_history` id=6 inserted, `portfolio_state` updated, all in the same transaction as the decision | directly observed (source, `talonx_paper/store.py:428-486`) |
| Process PID / start time / revision | experimental component pid 22576 (supervisor.log: `spawned experimental pid=22576 state=STARTING` at `2026-09-11 12:54:28,937` local = **11:54:28.937Z**); loaded revision = deployed SHA `c88f4d4600735dcc65fb5108c73489e877d16ebe` (the process was spawned by `start` AFTER the merge, from the merged worktree) | directly observed |
| Price source, raw input, fill calc | raw last-bar price (yfinance intraday); `apply_spread(price, 5.0bps, "SELL")` → fill = raw × (1 − 0.00025); realized_pnl via `calculate_sell_pnl` | directly observed (source + arithmetic reproduces the recorded fill to 6 decimal places, see below) |
| Stop/target trigger | `check_stop_take`: dollar-anchored stop $273.6548 (ATR-anchored, captured at entry) — a raw price at/below $273.6548 → `STOP_LOSS` | directly observed |
| Session eligibility check | none exists for exits (parity decision with Original's own `_handle_market_tick`, documented in Task 118A's P1 report) — this tick was accepted regardless of premarket/regular status | directly observed (design) |
| Freshness check | `age = evaluation_time − tick_time`; this tick: `11:55:28Z − 11:53:51Z ≈ 97s`, well inside the 300s cutoff → accepted | directly observed |
| Delivery/display record update | `exp_alerts.db.experimental_trades` row `Xb3e23f52268a897f` updated in place via `update_trade()` (exit/exit_reason/net_pnl/closed_at filled in) — **not** a second inserted row | directly observed |
| Duplicate check | `get_position("VRT")` returns `None` after close; two later ticks (BLSH-style monitoring continues) produced no further VRT trade_history rows | directly observed (live `trade_history` has exactly one SELL row for VRT) |

## Reconstructing the fill arithmetic

Recorded fill: `251.0872125`. `apply_spread` with `spread_bps=5.0`:
`raw_price × (1 − 5/2/10000) = raw_price × 0.99975`. Solving:
`raw_price = 251.0872125 / 0.99975 ≈ 251.1499985...` — i.e. the underlying
raw market price this fill was computed from was **≈$251.15**, consistent
in magnitude with VRT's last known 2026-09-10 reference price (~$247.65,
Task 118 Part 4) and a plausible pre-market move, not an outlier or an
obviously-wrong number (e.g. not confused with another symbol's price
scale, not zero/negative, not the stop price itself).

## Corroborating evidence the 07:53:51-04:00 timestamp is a real, dated market bar

Two **independent** lanes' own preseed/bootstrap logic, re-fetching VRT
history from yfinance right after their own restart (different processes,
different log files), landed on the **identical** last-bar timestamp:

- Experimental (`_supervisor_logs/experimental.log:35156`, 2026-09-11
  12:54:36 local): `1-min historical pre-seed: loaded 114 bar(s) for VRT`.
- Original (`_supervisor_logs/original.log:151803`, 2026-09-11 12:55:09
  local): `60-minute regime bootstrap: fed 2896 historical 1-min bar(s)
  for VRT (2026-09-04 04:00:00-04:00 -> **2026-09-11 07:53:51-04:00**)`.

Two independently-executing fetches, ~33 seconds apart, both terminating
at the exact same last-bar timestamp is strong evidence this genuinely was
the newest 1-minute bar yfinance had for VRT at that point in time — not
an artifact of one specific code path, a cached/stale value peculiar to
one process, or a coincidence.

## Was this a stale pre-restart event replayed after the fact?

**No — ruled out structurally, not merely by inference.** `talonx:market:stream`
is a plain Redis **Pub/Sub** channel (`redis.asyncio.pubsub()`), which has
no backlog or replay semantics — a message published while nobody is
subscribed is simply never delivered (a durability gap already on record,
see the standing memory note on this exact property). Every producing
process (the "original" market-data component, which publishes to this
channel) was itself torn down by `stop_stack()` and not respawned until
`11:54:28Z` — **nothing was capable of publishing to this channel at all**
during the 11:53:31Z–11:54:28Z gap. It is therefore structurally
impossible for a message published during that gap to have been queued
and delivered later; this tick was necessarily published (and received)
**after** 11:54:28Z, carrying an embedded bar timestamp that legitimately
lagged the publish/consume wall-clock time by ~97 seconds — realistic
pre-market yfinance intraday-bar latency, not a replay artifact.

## Premarket exits under the existing contract

No session-eligibility gate exists for Experimental exits at all (same
parity decision as Original's own live stop/target path, documented in
the Task 118A P1 report) — a pre-market-sourced tick triggering a
stop-loss is consistent with the system as designed, not a violation of
any documented rule. `PreMarketPoller`/premarket price sourcing is
explicitly, by the codebase's own comments
(`talonx_ingest/market_data/yfinance_poll.py:315-324`), "the sole
authoritative price source for the pre-market window" — receiving and
acting on a pre-market price is expected behavior, not an edge case the
system was not designed for.

## Gap/fill policy match

The recorded fill (~$251.15 raw, $251.0872125 after spread) is **not**
the stop price ($273.6548) and **not** the stale 2026-09-10 reference
price ($247.65) — it is the tick's own actual price, exactly matching the
established "fill at the next valid observation's real price" convention
documented in Task 118A's Priority 1 report and Original's own
`talonx_paper.engine.check_stop_take`/`apply_spread` pattern.

## What remains unavailable (stated, not filled in)

- No Redis message id or persisted delivery record exists for the
  specific tick that triggered this exit (Pub/Sub has none).
- The exact yfinance API response (raw bytes/JSON) that produced the
  07:53:51-04:00 bar is not independently re-fetchable after the fact
  (yfinance's live intraday window moves forward continuously; the same
  historical query run now would return different, newer data) — the
  corroboration above (two independent lanes agreeing) is the strongest
  available evidence, not a byte-for-byte replay.

## Remaining positions checked against the same lifecycle

BLSH, AMD, STX, SPCX — inspected via the same live dashboard/authoritative
store read used above (`experimental_paper.db.positions`, unchanged since
Task 118A). All four remain open; none was forced to exit for this
investigation. Per the same policy, each will resolve independently on
its own first qualifying tick (BLSH, also past its recorded stop as of the
last 2026-09-10 reference price, is the next most likely to close on its
own next fresh observation — not forced here).

## Evidence

`results/task100b_runtime_integration/_supervisor_logs/{original,
experimental}.log` (release worktree, read-only); `experimental_paper.db`
direct read (`positions`, `trade_history`, `portfolio_state`);
`exp_alerts.db.experimental_trades` direct read; `talonx_paper/store.py`,
`talonx_paper/engine.py`, `talonx_signals/run.py` (source, unmodified
since Task 118A's deployed `c88f4d4`).
