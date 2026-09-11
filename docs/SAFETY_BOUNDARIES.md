# TalonX — Safety Boundaries

Every item here is enforced by code + tests, not just intent.

## Original vs Experimental

| | Original | Experimental |
|---|---|---|
| thresholds | `min_atr_pct 0.25` / `confluence_score_min 2` / `min_risk_reward_ratio 1.5` — **frozen** | `RELAXED_OVERRIDES` = `0.10 / 1 / 1.0` — **frozen** |
| profile drift guard | — | `assert_control_profile_unchanged()` at lane start fails closed if Original's defaults drift; the relaxed profile is a `dataclasses.replace(QuantConfig())`, never a mutation |
| external alerts | the sole official/external trading-alert lane | **never external** |
| paper state | `paper_trading.db` (separate `PaperTradingStore`) | `experimental_paper.db` (separate instance) — no shared object, no cross-file write |
| decision dependency | — | `talonx_core.DecisionEngine` never imports `talonx_signals`; Original's decision path never reads an Experimental store |

## External alert boundary (P0, structural)

`talonx_signals.external_boundary` — a real Experimental external send requires **three**
independent conditions: `enable_external_send=True` **and** the sender advertises
`is_external_transport=True` **and** `TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE=i-understand` in
the environment. Absent any one → `ExperimentalExternalBoundaryError`, nothing leaves the
process. `is_external_eligible(family)` is fail-closed (unknown family → not eligible).
Default posture: **structurally impossible**.

## One Telegram receive owner

Exactly one `get_updates` poller — `TelegramReplyListener` inside `run_talonx.py`'s
`DispatchAgent`. `talonx_ops.supervisor` refuses to start a second Original if one owner is
already running (`DuplicateTelegramOwnerError`); `count_telegram_get_updates_owners()` /
`assert_single_telegram_owner()` guard it. The D/X/R/E resolver registers on that ONE listener
via `extra_resolvers` — no second listener, no Experimental sender.

## Paper / capital

- **No shorts** — no `open_short` (or equivalent) method exists in `talonx_paper` or
  `talonx_signals.experimental_paper`. `SELL` / `EXIT` closes an existing long. `BEARISH` is a
  label, never an order.
- **No real capital** — `TALONX_PIV_REAL_CAPITAL=false`; `talonx_piv` raises `PaperGuardError`
  on `real_capital=True`. Original local paper performs no broker/network calls. Real-capital
  execution is not implemented anywhere in the repository.
- **PIV ≠ Original paper** — separate account, separate Redis DB index/namespace/state dir;
  never surfaced as Original local paper; `NOT_CHECKED` in the dashboard unless an explicit
  read-only reader is injected (never fabricated `0`).

## Data / models

- **No paid data by default** — `PAID_DATA_SPEND = £0` across the whole research programme. The
  only required config is `TALONX_SEC_USER_AGENT` (free, SEC-mandated).
- **No AI/ML in the runtime** — `talonx_brain` uses an LLM for *descriptive* context grounding
  only; the significance engine is deterministic fixed-point arithmetic with an AST-enforced
  no-forward-return guard. No model training, no ML inference on the trading path.

## Admin denylist

`:8787/admin/` refuses (and audits) any request touching a strategy/execution key — see
`docs/ADMIN.md` for the full pattern list. Strategy and execution parameters are not editable
anywhere in the running system.

## Descriptive intelligence semantics

The Information Significance band carries **no forward-return input and no direction**. CI lints
reject predictive language. "Band" = how much human attention an event deserves, nothing more.

## Frozen strategy settings

`min_atr_pct`, `confluence_score_min`, `min_risk_reward_ratio`, trend semantics, trigger
definitions, confluence scoring, R:R computation, Quant→Brain ordering, and every validated
indicator formula are **frozen**. Changing any of them is out of scope for operational tasks and
requires a separate, explicitly-authorised research/tuning mandate. See
`results/task102_operational_finalization/live_hotfix_policy.md` for what may vs may not be
changed during a live session.
