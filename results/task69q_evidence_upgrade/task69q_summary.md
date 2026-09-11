# Task69Q Summary

Post-Task69P evidence-quality closure and a Telegram/pre-market notification
upgrade, on `research/talonx-strategy-validation`, starting at
`3d0778360e81aca6c8f8fd8aafe80811ab7b622d`. No strategy semantics changed, no
F6 integration, no real capital, no fake signals, WATCH cannot place orders.

## What was found (Part 1)

Task69P's 13 headline claims all independently reconfirmed against raw
evidence. Four previously-undocumented gaps found and fixed this task; one
(warmup provider) assessed with a concrete, verified remediation path but not
fully migrated. See `task69p_deep_review.md`.

## What was fixed

1. **Session-scoped telemetry** — every event now carries `session_id` /
   `trading_date_et`; `build_session_report` can filter to exactly one
   trading date, so a single append-only `piv_events.jsonl` can never again
   silently mix multiple days' counts.
2. **Quant funnel accounting** — `DecisionEngine` now taps QuantScanner's
   existing `rejected_candidates_channel` alongside `signals_channel`
   (zero changes to protected `talonx_quant/*`), reconciling
   `candidates = published + rejected + pending + errored` with an explicit
   `unaccounted_candidates` check.
3. **Natural vs probe separation** — `reporting.build_session_report` now
   splits `natural_strategy` from `piv_test_traffic` explicitly; every
   notification is tagged with one of six classes
   (`SYSTEM`/`PREMARKET_RADAR`/`NATURAL_SIGNAL`/`PAPER_EXECUTION`/`PIV_TEST`/`EOD`).
4. **Position lifecycle defect fixed** — an exit fill previously emitted a
   second, misleading `POSITION_OPENED` instead of `POSITION_CLOSED` (broker
   exposure was always correct/flat; this was a state/event-naming bug).
   Fixed in `talonx_piv/lifecycle.py` with a symbol-keyed open-position map.
5. **Execution economics** — entry/exit slippage, gross/net PnL, holding
   time, and gross/net R (only when a stop is actually defined — never
   fabricated) are now captured automatically on every `POSITION_OPENED`/
   `POSITION_CLOSED` event.
6. **Pre-market radar** — new, purely observational `PREMARKET_WATCH`/
   `PREMARKET_WATCH_CLEARED` notifications from 04:00 ET (never UK-clock-
   driven), computed only from data already available (gap vs previous
   close). Structurally cannot place an order — the module has no import of
   `broker.py` or `lifecycle.py` at all.
7. **`/ping` PIV-awareness fix** — the headline Pipeline status no longer
   reads the unrelated general-ingest subsystem for a PIV caller; it now
   reflects PIV's own live feed health, plus a unified view (session id,
   quant funnel, natural/probe traffic, radar WATCH count).
8. **Status heartbeat** — a rate-limited (≤ once/30min) "No actionable
   trades. Engine active." notification when there's been no natural signal
   for a while, with decision-ready count / evaluation cycles / top
   rejection reason.

## What was investigated but not shipped

- **Warmup provider**: verified (via a real, read-only Alpaca API call using
  the existing IEX-tier credentials) that Alpaca's own historical-bars
  endpoint returns hundreds of 1-minute bars for symbols yfinance's warmup
  failed on. Built and tested a prototype fetch function
  (`talonx_piv/alpaca_historical_warmup.py`), but did NOT wire it into
  `QuantScanner`'s buffers — that integration needs its own focused review.
  See `warmup_provider_assessment.json`.
- **Live/offline replay parity**: designed only, per the task's own
  instruction, in `production_readiness_gaps.json` (PRG-08).
- **Per-session directory layout** (`results/runtime/<date>/<session_id>/`):
  deferred in favor of the lower-risk event-tagging approach above; recorded
  as PRG-01.

## Permanent product record

`docs/research/TALONX_PIV_RUNTIME_PRODUCT_TARGET.md` now records the
ET-canonical session clock, the pre-market three-concepts split (A/B live,
C deliberately disabled), the target ticker-decision contract, and the
notification-category taxonomy, so this direction survives across sessions.

## Tests

29 new focused tests (`test_task69q_evidence_upgrade.py`,
`test_task69q_alpaca_historical_warmup.py`), 2 pre-existing test fixes (one
fixture, one stale assertion — both confirmed via `git stash` to be
independent of/pre-dating this task's changes). Full regression: 2060 passed,
1 pre-existing unrelated failure (confirmed via `git stash`), 1 skipped, 15
xfailed.

## Next

Task70 — accelerated frozen-alpha validation / historical holdout assessment
is the immediate next priority. The next live PAPER session (plan in
`next_live_session_plan.md`) is prepared but **not started** by this task.
