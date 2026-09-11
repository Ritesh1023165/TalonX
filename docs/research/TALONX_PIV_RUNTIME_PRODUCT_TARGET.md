# TalonX PIV Runtime — Permanent Product Target

**Status**: CONFIRMED direction, recorded by Task 69Q (2026-08-25) so it is not
lost between sessions. This document is append-only in spirit, matching
`TALONX_RESEARCH_LEDGER.md`'s convention — future tasks should add to it, not
silently reinterpret it. It governs **runtime/operational** product shape
(session windows, notification categories, the ticker-decision contract); it
does NOT govern alpha/strategy content, which remains
`TALONX_PRODUCT_STRATEGY_SPEC.md`'s domain.

## 1. Canonical session clock

- PRE-MARKET starts at **04:00 America/New_York**. In August 2026 this is
  09:00 UK/BST — that UK time is a DERIVED DISPLAY VALUE, never the source of
  truth, and it drifts with DST (currently UTC+1; UK/ET offset is not
  constant across the year).
- **Never hardcode a UK clock time for US-market semantics.** Every session
  boundary is computed in `America/New_York`/XNYS and converted for display
  only. (Confirmed compliant in the live decision path as of Task69Q — see
  `talonx_piv/session_runner.py`'s `ET = ZoneInfo("America/New_York")` and
  `talonx_piv/premarket_radar.py`'s `PREMARKET_START`. The one UK-local
  reference found, `talonx_dispatch/telegram_listener.py`'s `/ping` SESSION
  display line, is display-only and does not drive any decision.)

## 2. Pre-market has three concepts — only two are live

| Concept | Status |
|---|---|
| A. System preparation (startup/warmup ahead of the radar window) | LIVE (Task69Q Part 10 design; can start ahead of 04:00 ET) |
| B. Market/radar observational analysis | LIVE (Task69Q Part 7A — `talonx_piv/premarket_radar.py`) |
| C. Actionable pre-market trading | **DISABLED, DELIBERATELY.** Must remain disabled until a separately researched/frozen/validated pre-market trading strategy exists. `premarket_radar.py` has no import of `broker.py`/`lifecycle.py` at all — this is a structural guarantee, not a config flag that could be silently flipped. |

## 3. TalonX must not sit silent until 10:00 ET

During pre-market the runtime analyses configured symbols and surfaces
observational information (gap/overnight move, data readiness, developing
WATCH status where supported by already-available data) without reusing
regular-session strategy thresholds. See `premarket_radar_contract.json`
(Task69Q) for what is and is not implemented today.

## 4. Canonical ticker decision contract (target shape)

```
ticker
timestamp
market_session

horizon: INTRADAY_SHORT | INTRADAY_LONG | MULTI_DAY
decision: BULLISH | BEARISH | NO_TRADE | DATA_NOT_READY
status/actionability: WATCH | ACTIONABLE | NOT_ACTIONABLE

entry
stop_loss
target / exit_policy
holding_horizon
reason_codes
data_status
provider
strategy_id / version / fingerprint
```

As of Task69Q: `talonx_piv.events.PivEvent` carries `horizon`, `strategy_id`,
`reference_price`/execution-economics fields, `reason`, `status`, `source`
(maps to provider/lane), and `notification_class`. It does NOT yet carry a
single unified `decision`/`market_session` enum pair across all emitters —
that unification is a good candidate for Task70+ if/when a second strategy
family (e.g. a validated MULTI_DAY signal) makes a shared schema valuable
rather than premature.

## 5. Short-term vs longer-term are separate strategy/evidence families

QuantScanner (the only live natural strategy today) is intraday-only.
`talonx_piv/decision_engine.py`'s `NATURAL_STRATEGY_HORIZON = "INTRADAY_SHORT"`
is hardcoded and must not be silently reused to imply a MULTI_DAY result.
**No MULTI_DAY strategy is researched, frozen, or validated as of this
document.** The `horizon` field exists precisely so a future, separately
validated longer-horizon strategy can be added without redesigning the
event schema — not as license to manufacture a MULTI_DAY signal now.

## 6. Notification categories (operator-facing)

`OBSERVATIONAL/RADAR` (=`PREMARKET_RADAR`), `NATURAL STRATEGY` (=`NATURAL_SIGNAL`
+ `PAPER_EXECUTION`), `PIV TEST TRAFFIC` (=`PIV_TEST`), `SYSTEM HEALTH`
(=`SYSTEM`), `EOD` — see `notification_contract.json` (Task69Q) for the full
mechanism (`talonx_piv.events.notification_class_for`).

## 7. WATCH and NO_TRADE are first-class, safe outputs

- **WATCH is not a trade recommendation and is not alpha evidence.** It must
  never trigger a broker order. Enforced structurally today (see §2 above),
  not just by convention.
- **NO_TRADE is a legitimate, useful output** — a natural strategy day with
  zero signals, or a radar day with zero WATCH transitions, is a valid,
  informative result, not a failure of the system.

## 8. Profitability remains a mandatory production-readiness requirement

Operational readiness (this document's concern) is necessary but not
sufficient. See `docs/research/TALONX_PRODUCT_STRATEGY_SPEC.md` and
`TALONX_RESEARCH_LEDGER.md` for the alpha-validation track (Task70+), which
this document does not shortcut or substitute for.

---
Recorded by Task 69Q. See `results/task69q_evidence_upgrade/` for the
evidence and contracts behind each claim above.
