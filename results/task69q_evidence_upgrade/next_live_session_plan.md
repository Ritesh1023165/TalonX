# Next Live PAPER Session — Plan (NOT auto-started by Task69Q)

Broker lifecycle is already validated (Task69P). This plan is for the next
FULL PAPER evidence session on a regular market day, using the runtime as
upgraded by Task69Q. **Nothing in this task starts it.**

## Goal

Produce trustworthy, session-scoped NATURAL profitability evidence (or a
legitimate zero-signal day), with pre-market visibility, without touching
strategy semantics.

## Startup sequence

1. Start the process well before 04:00 ET (Part 10) so warmup/preflight are
   not racing the pre-market radar window or the regular open. Concretely:
   `talonx_piv.cli start --approved-sha <SHA> --confirm-paper-session-start`
   run early enough that preflight + `DecisionEngine.start()` (yfinance
   warmup, unchanged) complete before 04:00 ET.
2. `session_identity.json` is written automatically at `start` — confirm it
   exists before relying on session-scoped reports.
3. Confirm Telegram inbound `/ping` is reachable and its PIV section shows
   `feed_health` moving from `UNKNOWN (session starting up)` to `HEALTHY` once
   the live loop begins polling.

## Pre-market (04:00–09:30 ET)

- `SessionRunner.process_premarket_tick` runs automatically once the process
  clock crosses `PREMARKET_START` — no separate flag needed
  (`premarket_radar_enabled=True` by default).
- Expect `PREMARKET_WATCH`/`PREMARKET_WATCH_CLEARED` events only on bias
  transitions — a quiet pre-market (no gaps beyond ±1%) is a valid, expected
  outcome, not a bug.
- Do NOT expect any pre-market order. None can occur — see
  `premarket_radar_contract.json`'s structural guarantee.

## Regular session (09:30–15:45/15:50 ET)

- Full warmup + session-readiness gating unchanged from Task69P.
- Natural QuantScanner evaluation runs exactly as before; the ONLY additions
  are non-invasive telemetry (funnel accounting, execution economics on any
  fill) — no gate, threshold, or ranking logic was touched.
- Expect either:
  - **A natural signal fires** → a real PAPER order, fill, execution-economics
    fields captured automatically on `POSITION_OPENED`/`POSITION_CLOSED`, or
  - **Zero natural signals** → a valid `NO_TRADE` day. If the operator wants
    reassurance the engine is alive, `STATUS_HEARTBEAT` fires at most once
    per 30 minutes stating "No actionable trades. Engine active." plus
    decision-ready count, evaluation cycles, candidates, and top rejection
    reason.
- **Do NOT pass `--confirm-piv-lifecycle-probe` by default.** Broker
  lifecycle is already validated; only re-enable the probe if lifecycle/
  broker code was materially changed since Task69P AND the existing
  preconditions (paper-only, cutoff time, no natural lifecycle yet observed)
  are satisfied.

## EOD

- Run `talonx_piv.cli eod` as before. It now reads back `session_identity.json`
  and `quant_funnel_report.json` and produces a `latest_session_report.json`
  that is scoped to that session's own `trading_date_et`, with
  `natural_strategy` vs `piv_test_traffic` cleanly separated and
  `quant_funnel`/`quant_funnel_flag` present.
- Verify `quant_funnel.unaccounted_candidates == 0`. If not, the report is
  flagged (`quant_funnel_flag: UNACCOUNTED_CANDIDATES_DETECTED`) — investigate
  before treating the day's funnel numbers as reliable.
- Verify `positions_closed` in the report matches actual exits (this is the
  first live session where the Part 5 fix is exercised under real fills —
  worth a manual spot-check against `lifecycle_state.json`).

## What this session will NOT do

- No pre-market trading (structurally impossible, see above).
- No MULTI_DAY signal (no such strategy exists).
- No alpha tuning based on this session's outcome — any interesting
  natural-signal result feeds into Task70's frozen-alpha validation track,
  not same-day threshold changes.

## After this session

Feed its `latest_session_report.json` + `quant_funnel_report.json` +
`session_identity.json` into whatever Task70 uses as its next PIV evidence
input. If a natural NATURAL_SIGNAL fired and produced a filled position, its
execution-economics fields (`gross_pnl`, `net_pnl`, `gross_r`/`net_r` if a
stop was defined) are the first real per-trade evidence this runtime has ever
captured automatically — worth flagging to whoever reviews Task70's inputs.
