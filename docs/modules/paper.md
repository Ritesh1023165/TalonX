# `talonx_paper` — Module 6: Live Paper Trading Engine

```
Redis: talonx:alerts:dispatch ──┐
                                 ├──► talonx_paper.consumer
Redis: talonx:market:stream ────┘         │
                                           ├─ ticker has paper trading enabled?
                                           │  (talonx_watchlist -- see below) no -> skip
                                           │
                                           ├─ market tick (BAR)? -> update_latest_price
                                           │  (mark-to-market source for the dashboard,
                                           │  a SEPARATE process with no access to this
                                           │  one's in-memory state)
                                           │
                                           └─ alert -> engine.decide_trade (pure):
                                                CONFIRMED_BULLISH + flat        -> BUY
                                                CONFIRMED_BEARISH/CONTRADICTED
                                                  + long                       -> SELL
                                                repeat signal, same state       -> ignored
                                                                                    (logged only)
                                                DEGRADED_QUANT_ALERT            -> no action
                                                          │
                                                          ▼
                                        PaperTradingStore.execute_buy/execute_sell
                                        (SQLite -- positions, trade_history,
                                        portfolio_state all updated atomically)
                                                          │
                                                          ▼
                                        Redis: talonx:paper:trades (PaperTradeExecution)
                                                          │
                                                          ▼
                                        talonx_dispatch.consumer -- its OWN short
                                        Telegram push (see dispatch.md), decoupled
                                        from the triggering alert's push
```

- **Not what the original requirement doc specified, and why**: the doc
  asked for a PostgreSQL ledger and one combined Telegram message (alert +
  execution card together) -- both deliberately NOT built that way here.
  SQLite matches every other store in this project (no new database
  technology, no new docker service) and two DECOUPLED short pushes
  preserve the alert-shortening work from the session before this one,
  rather than reintroducing a long combined message. Position sizing is a
  FIXED dollar amount per trade (default $2,500, `TALONX_PAPER_TRADE_ALLOCATION`)
  rather than "100% of cash" -- since the one-position-per-TICKER limit is
  per-ticker, not portfolio-wide, "100% of cash" would let the first BUY
  signal claim the entire balance and starve every other tracked ticker.
- **Trigger mapping**: the doc's own action names (`BUY_SIGNAL`,
  `BEARISH`, `VALUE_TRAP_WARNING`) don't exist in the real `AlertAction`
  enum -- mapped onto the real one in `engine.py`: BUY on
  `CONFIRMED_BULLISH`, SELL on `CONFIRMED_BEARISH` **or** `CONTRADICTED`
  (the doc's own Telegram example shows `CONTRADICTED` triggering a
  SELL), no action at all on `DEGRADED_QUANT_ALERT` (no research backing,
  not worth trading on).
- **`engine.py`** -- pure functions, no I/O, same testability philosophy
  as `talonx_core.decision`: `decide_trade` (the state machine above),
  `calculate_buy` (spends `min(allocation, cash)`, so a low balance
  partially fills rather than erroring), `calculate_sell_pnl` (exact
  formulas from the requirement doc, verified against its own worked
  example in `tests/test_paper_engine.py`).
- **ATR-anchored stop-loss/take-profit** — `check_stop_take()` accepts
  optional `stop_price`/`target_price` (the exact ATR-anchored dollar
  levels `talonx_quant` computed at signal time, threaded through
  `talonx_core` and persisted on the position at entry). When both are
  present they OVERRIDE the static percentage bands entirely; when
  either is missing (an older alert, or a `DEGRADED_QUANT_ALERT` with no
  ATR data) it falls back to the static
  `TALONX_PAPER_STOP_LOSS_PCT`/`TALONX_PAPER_TAKE_PROFIT_PCT` bands
  (default 0.50%/1.00%). The levels are captured once at entry, not
  recomputed live from a fresh ATR reading each tick — the trade was
  sized against the levels that existed at signal time, and ATR drifts.
- **`store.py`** -- `PaperTradingStore`, SQLite (WAL, `threading.Lock`,
  same convention every store built this session uses). Four tables:
  `portfolio_state` (single row -- cash, allocation, cumulative PnL,
  win/loss counts; percentages are DERIVED on read, never stored, so they
  can't drift), `positions` (one row per OPEN position -- a ticker's
  ABSENCE from this table IS "flat," no separate status column; now also
  carries `stop_price`/`target_price`), `trade_history` (append-only,
  powers the dashboard's trade table, CSV export, and equity curve),
  `latest_prices` (updated on every market tick -- exists because the
  Streamlit dashboard is a separate process with no access to the
  engine's in-memory price cache). `execute_buy`/`execute_sell` are
  OPERATION-shaped, not raw CRUD -- each updates positions +
  portfolio_state + trade_history atomically (one lock, one commit) so
  `consumer.py` never hand-coordinates a multi-table write.
- **Per-ticker enable/disable lives in `talonx_watchlist`, not a second
  ticker list** -- `paper_trading_enabled` is a new column on the SAME
  `tickers` table [running.md](../running.md)'s dashboard already
  manages (same idempotent migration pattern as `exchange`/`status`
  before it), toggled via a multiselect in the dashboard's "💰 Paper
  Trading" section. This is the "configure which ticker can be used"
  control surface.
- Wired into `run_talonx.py` as a sixth continuous task (see
  [orchestrator.md](orchestrator.md)) -- `--skip-paper-trading` leaves it
  out on purpose; a ledger-open failure degrades the same way Module 5's
  audit DB failure does (warns, doesn't crash the rest of the pipeline).
  Run it standalone with `python -m talonx_paper.run` if you want it
  decoupled.

## Long-term (DCA-aware) ledger

See [../phase2-multi-horizon.md](../phase2-multi-horizon.md) for the
DCA-aware long-term ledger — its own cash pool, recurring contributions
into open positions, `TAKE_PROFIT_REBALANCE` partial trims, and
`UNDER_PERFORM_REBALANCE` full exits.
