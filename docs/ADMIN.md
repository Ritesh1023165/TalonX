# TalonX — Local Admin (`:8787/admin/`)

A dedicated **local-machine-only** page for routine operational config. Separate from the
read-only cockpit; the cockpit itself has no write affordance and does not link here.

## Access

- Served only when `dashboard_web.py` is bound to a loopback host (`127.0.0.1` / `localhost` /
  `::1`). Any other bind → every `/admin/*` route returns `403`.
- No authentication layer (by design — a fake security model is worse than none). "Local machine
  only" is the control.

## Routes

| route | method | purpose |
|---|---|---|
| `/admin/` | GET | the admin page (`dashboard_web_static/admin.html`) |
| `/admin/config` | GET | allowed actions + the denylist note + the recent audit tail |
| `/admin/config/state` | GET | current values for the 9 editable fields (for current-vs-proposed display) |
| `/admin/config/apply` | POST | apply one action — body `{ "action", "params", "confirm": true }` |

## The 9 controls (nothing else)

`watchlist.add` · `watchlist.remove` · `watchlist.pause` · `watchlist.resume` ·
`watchlist.set_horizon` · `watchlist.set_paper_trading` ·
`watchlist.set_paper_trading_long_term` · `paper.set_trade_allocation` (≥ 10.0) ·
`paper.set_dca_amount` (≥ 10.0).

Each delegates to the existing validated store method (`TickerWatchlistStore.*` /
`PaperTradingStore.update_*`) — the admin layer adds no new write primitive.

## What is permanently denied

`talonx_ops.admin_config._DENY_PATTERNS` — any request whose action name, a param key, or a param
value matches: `atr`, `confluence`, `risk_reward` / `rr` / `r:r`, `threshold`, `trend`,
`min_bars`, `htf`, `sma`, `macd`, `rsi`, `pivot`, `trade_gate`, `relaxed`, `override`, `promot*`,
`experimental_*enable`, `enable_external_send`, `telegram*token`, `broker`, `alpaca`,
`real_capital`, `short`, `execution`, `order`, `quant_config`, `decision`, `brain`,
`strategy_param`, `signal_type`, `episode`.

A match → `403` + audit `REFUSED_DENYLIST`, and the raw param **values** are never written (only
`{param_keys: [...]}`).

## Safety properties

- `confirm: true` required — otherwise `REJECTED_UNCONFIRMED`, no write.
- Invalid input (`amount < 10`, bad horizon, symbol not on the watchlist) → `REJECTED_INVALID`,
  no write.
- Every attempt is recorded in `~/.talonx/admin/config_audit.db`:
  `at_utc · action · config_key · previous_value · new_value · source · validation · outcome`
  (`APPLIED` / `REJECTED_UNCONFIRMED` / `REJECTED_INVALID` / `REFUSED_DENYLIST` / `FAILED`).
- The page uses `fetch()` (no native `<form>`), disables the button during the request, and
  clears the confirm box afterward — a browser refresh or double-click cannot silently repeat a
  write.
- No token field exists; no secret is ever displayed or logged.

## Scripted use

```bash
curl -s http://localhost:8787/admin/config | python -m json.tool
curl -s -X POST http://localhost:8787/admin/config/apply -H 'content-type: application/json' \
  -d '{"action":"watchlist.pause","params":{"symbol":"NVDA"},"confirm":true}'
```

## Not here

Destructive paper-portfolio resets, starting-balance edits, and long-term research views stay on
`:8501` — see `docs/COMPATIBILITY.md`. Strategy and execution parameters are not editable
anywhere in the running system, by design.
