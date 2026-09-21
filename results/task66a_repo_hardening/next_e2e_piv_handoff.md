# Next E2E PIV Session — How to Run It

This defines exactly how to run ONE clean, full end-to-end PAPER PIV session with the Task 66A
hardened checkpoint. Not executed by Task 66A itself — this is the handoff for whoever/whatever runs it next.

## What "full topology" means now

Unlike Task 65B (which ran feed + readiness + decision path + probe, but with the inbound Telegram
listener silently absent), a session started from this checkpoint runs everything the PIV harness is
designed to run, with nothing intentionally disabled without a documented reason:

```
YFinance causal warmup (preseed_symbols, verified per-symbol)
        ↓
Alpaca real-time IEX (or RESEARCH_SIP, per feed_mode)
        ↓
SessionReadinessValidator (now restart-safe: session_readiness_state.json)
        ↓
real talonx_quant.consumer.QuantScanner (via decision_engine.py, unmodified)
        ↓
Redis (QuantScanner's own gating -- confluence/RR/trend/cooldown -- authoritative)
        ↓
PAPER order lifecycle (talonx_piv.lifecycle, immutable Alpaca paper endpoint)
        ↓
Telegram outbound (event fan-out) + Telegram inbound (/ping, concurrent task)
        ↓
Reconciliation + EOD flatten
```

`talonx_brain`/`talonx_core`/`talonx_paper` (research-report generation, multi-signal correlation,
the separate long/short-term paper P&L ledger) remain out of scope by design — they are downstream,
non-PIV concerns, not omitted features.

## Exact commands

```
py -3.12 -m talonx_piv.cli preflight --approved-sha (git rev-parse HEAD)
```
Require exactly `PIV_READY`. This preflight now includes `decision_path_mode`, `warmup_mechanism_capability`,
`telegram_inbound_capability`, and `runtime_parity` (must read `RUNTIME_PARITY_PASS`) alongside every
existing Task 64 gate. If blocked, STOP — do not weaken any check to force a pass.

Start well before 09:30 ET (causal warmup takes real time for 35 symbols via yfinance — budget ~09:15 ET,
per the pattern already used in Task 65B):
```
py -3.12 -m talonx_piv.cli start --approved-sha (git rev-parse HEAD) --confirm-paper-session-start --confirm-piv-lifecycle-probe
```
Add `--no-telegram-inbound` ONLY if a separate `run_talonx.py` process is already polling the SAME
`TELEGRAM_BOT_TOKEN` (only one inbound poller per token is allowed by Telegram itself; outbound is
unaffected either way).

At end of day:
```
py -3.12 -m talonx_piv.cli eod
```

## What to verify this time that Task 65B could not

1. **Continuous readiness through a restart.** If the process needs to restart mid-session, confirm
   `SESSION_READINESS_STATE_RESTORED` appears in `piv_events.jsonl` and that any symbol already READY
   before the restart stays READY after it (not re-derived as DATA_NOT_READY).
2. **A natural signal actually reaching a readiness-eligible, warmup-eligible symbol.** Task 65B never
   observed this end-to-end in one continuous live run (the restart-forced readiness gap blocked it,
   which this task fixes). This is the single most important thing to confirm didn't regress and now
   actually completes the full chain: `SIGNAL(source=STRATEGY)` → `ORDER_INTENT` → `PAPER_ORDER_SUBMITTED`
   → `FILLED` → `POSITION_OPENED`, without needing the `PIV_LIFECYCLE_PROBE` fallback at all (a
   zero-natural-signal day is still a valid outcome — the probe exists exactly for that case — but a
   *restart-caused* zero should no longer happen).
3. **`/ping` actually answers.** Send `/ping` to the configured bot/chat during the session and confirm
   a reply arrives (uptime/CPU/RAM will be populated; most pipeline-stage metrics will correctly read
   "unknown" since PIV doesn't run brain/core/dispatch — that's expected, not a defect).

## Expected success criteria

- Preflight: `PIV_READY`, including `RUNTIME_PARITY_PASS`.
- Session runs uninterrupted (or, if restarted, readiness correctly persists across it) through the
  configured EOD flatten time.
- EOD reconciliation: `matched=true`, zero residual paper orders/positions.
- `/ping` answered at least once during the session.
- ORPB_V1/FPRC_V1 fingerprints unchanged; zero diff on protected `talonx_quant/*` files.
- Classification per the existing PARITY_OK/ENGINE_DEFECT/DATA_ISSUE/EXECUTION_DRIFT/
  STRATEGY_BEHAVIOR_EXPECTED/REVIEW_REQUIRED framework — a losing trade or a quiet natural-signal day
  is still not automatically a defect.
- No real-capital capability introduced or exercised at any point.
- Alpha status remains explicitly UNPROVEN in whatever summary is produced — this session, like every
  PIV session before it, is operational evidence only.

## Do not

- Do not weaken any preflight/safety gate to force `PIV_READY`.
- Do not tune, replay, or reinterpret ORPB_V1/FPRC_V1 — both remain rejected and retired.
- Do not force a natural signal by adjusting strategy config/thresholds.
- Do not begin alpha discovery inside this session — that remains a separate, later task
  (see `results/task65_piv/next_alpha_discovery_plan.md`).
