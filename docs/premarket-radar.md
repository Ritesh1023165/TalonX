# Pre-Market Radar (whole watchlist)

`run_talonx.PreMarketPoller` extends the extended-hours price capture
built for the [Earnings Radar](earnings-radar.md) (originally only for
tickers inside their earnings window) to **every active ticker**, so
pre-market moves are visible before the regular session opens rather
than gapping into view all at once when it does.

- Regular hours already get live prices from `WatchlistDrivenMarketData`/
  `LongTermPriceRunner` via yfinance's `fast_info`, which does **not**
  reflect pre/post-market trading -- without this poller, a pre-market
  move was invisible until the regular session opened.
- Polls every `TALONX_PREMARKET_POLL_INTERVAL_SECONDS` (default 300s)
  using `fetch_extended_hours_quote` (`history(prepost=True)`, the same
  call the earnings fast-track poller uses), but only while inside a
  configurable UTC time-of-day window: `TALONX_PREMARKET_START_UTC` /
  `TALONX_PREMARKET_END_UTC` (default `08:00`-`14:30` UTC). Ticks flow
  onto the same `talonx:market:stream` channel as every other price
  source, so they hit the exact same downstream signal/decision/
  notification pipeline and gates as a regular-session tick -- no
  separate, looser filtering for pre-market moves.
- **Deliberately simplified**, same posture as the Earnings Radar's flat
  2-day earnings window: Monday-Friday only, no trading-holiday calendar,
  no per-exchange session lookup for non-US tickers. US pre-market is
  4:00-9:30am ET, which is 08:00-13:30 UTC during EDT or 09:00-14:30 UTC
  during EST; the default window deliberately covers the **union** of
  both rather than picking one side of DST, since a bit of slack at
  either edge is harmless (the fetch just returns the latest available
  bar) but missing an hour of real pre-market movement from picking the
  wrong side of DST would not be.
- Excludes any ticker `EarningsFastTrackPoller` currently owns (same
  `active_earnings_symbols_fn` exclusion `LongTermPriceRunner` already
  applies) -- that poller already handles extended-hours pricing for its
  own narrower ticker set at a cadence tied to the actual earnings event,
  so this poller staying out of its way avoids two independent sources
  racing ticks for one symbol.
- Disable with `--skip-premarket`.

## `talonx_quant`'s own pre-market rules

Separate from (but complementary to) this whole-watchlist price poller,
`talonx_quant` applies session-aware signal-quality gates specifically to
pre-market candidates (stricter volume-surge threshold, a liquidity gate,
a news-catalyst requirement) — see
[modules/quant.md](modules/quant.md#phase-2-additions-pre-market-rules-and-the-15-min-trend-gate).
