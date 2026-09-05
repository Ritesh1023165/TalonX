# Remaining Stabilisation Plan (post Task 72O)

1. **Recalibrate `examples/data/sample_AAPL_trade_1m.csv`** (Stage 2) --
   add a coincident MACD cross near the existing RSI-recovery/
   volume-surge target bar so it clears `confluence_score_min=2` under
   the current (correctly confirmed, 2026-08-21) strategy rule. Verify
   independently against the real, unmodified indicator functions before
   trusting the edit; do not weaken the test's assertion.
2. **Extend Stage 3's profitability probe** -- full 10-symbol universe
   (`data/historical_1m/task7b_alpaca_long_history`) over the same
   development window, and a genuinely separate validation-period run
   (auditing `task46_validation_windows`/`task54_extended_windows`
   first -- their contents/date ranges were not inspected this task).
   Do not touch `task56_holdout`/`task56_independent_family_holdout`
   without a fresh, specific preregistration for that data.
3. **Cross-process EOD/freshness state persistence** (carried over from
   Task 71S/71S-R1) -- `FreshnessTracker` and the Stage 1
   `eod_state.json` idempotency guard are both in-memory-per-process/
   disk-checked-at-call-time only; a genuinely concurrent or
   rapid-restart scenario has not been stress-tested.
4. **`EventBus._key`'s cross-symbol Telegram-dedup collision** (Task
   71S-R1, `notification_dedup_evidence.json`) -- still unfixed, still
   pre-existing, still out of scope for a single-event mitigation.
5. **`REQUIRED_1M_BARS`/`min_bars_required` decoupling** (Task 70S,
   still unresolved, requires touching `talonx_quant/config.py`).
6. **Dashboard/EOD-report surfacing** of the new freshness/coverage/EOD
   fields -- none of this task's new data is yet rendered anywhere an
   operator would see it without reading the raw JSON/event ledger.
7. **A genuine `PROVIDER_WIDE_INTERRUPTION` real-world example** --
   still only unit-tested with synthetic data (Task 71S-R1).
8. **`min_atr_pct=0.25`'s effective selectivity** -- Stage 3 observed it
   rejecting 99.5%+ of AAPL's bars over a routine ~4.5-month window;
   worth a dedicated study of whether this is intended selectivity or an
   overly tight gate for a mega-cap, low-relative-volatility name (a
   strategy-research question, out of this task's scope --
   `talonx_quant/config.py` is protected).
