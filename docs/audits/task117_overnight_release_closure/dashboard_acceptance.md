# Dashboard acceptance — actual :8787 SPA vs isolated fixture (Task 117 §4)

## How it was rendered

- Read model: `talonx_ops/dashboard_read.py` gained a `TALONX_HOME` override
  (`_HOME = Path(os.environ["TALONX_HOME"]) if set else ~/.talonx`).
- Fixture: `results/task117_overnight_release_closure_evidence/iso_home/` — the
  S3 `.postclose` DB set + **6 seeded `fix-*` `intelligence_delivery` rows, one
  per state** (PENDING, IN_FLIGHT, SENT, AMBIGUOUS, FAILED, EXPIRED) on top of
  the real 9,843-row backlog.
- Server: the **real** `dashboard_web.py` (the :8787 primary cockpit) started
  with `TALONX_HOME` pointed at the fixture, on a spare port.
- Capture: `chrome.exe --headless=new --virtual-time-budget=15000
  --run-all-compositor-stages-before-draw --screenshot=<abs path>` against
  `http://127.0.0.1:<port>/?nows=1#<section>`. `?nows=1` is a new frontend
  affordance in `index.html` that skips the live `/ws` socket so a virtual-time
  screenshot settles deterministically — **no behaviour change without the
  param**.
- 7 screenshots in `./screenshots/` (`ISOLATED_FIXTURE_*.png`, 98–184 KB), hashes
  in `../../results/task117_overnight_release_closure_evidence/screenshot_index.json`.

Everything below is an **ISOLATED FIXTURE**; the displayed FAILED/DEGRADED
runtime badges are the correct honest rendering of a snapshot with no live
producers, not a live-session state.

## Frontend changes (this task)

- `renderIntelligence` — new **Card delivery** card: disabled/pending, sending
  (in-flight), sent, sending-ambiguous, failed, expired, suppressed, sent today,
  last card sent, last digest sent, queued-not-sent, and the note *"cards
  QUEUED is not cards SENT…"*. Backed by `dashboard_read.intelligence()['card_delivery']`.
- `renderPaperEod` — new **Official Telegram — last confirmed send** card:
  intraday / long-term (with ticker) / earnings-heads-up last **API-confirmed**
  send time, note *"human RECEIPT is never asserted"*. Backed by
  `dashboard_read.paper_eod()['official_telegram_last_send']`.

## Reconciliation of displayed values vs section JSON

### `ISOLATED_FIXTURE_intelligence.png` ↔ `section_intelligence.json.card_delivery`
| field | JSON | screenshot |
|---|---|---|
| disabled / pending | 9844 | 9844 |
| sending (in-flight) | 1 | 1 |
| sent | 1 | 1 |
| sending-ambiguous | 1 | 1 |
| failed | 1 | 1 |
| expired | 1 | 1 |
| suppressed | 0 | 0 |
| sent today | 1 | 1 |
| last card sent | 2026-09-10T23:13:30.840294+00:00 | 2026-09-10T23:13:30 |
| last digest sent | null | — |
| queued, not sent | 9845 | 9845 |

All six delivery states (**disabled/pending, sending-ambiguous, sending, sent,
failed, expired**) are individually visible. Service card shows
`NO_ACTIVE_PRODUCER` (producer live `false`) → the note explains 0 SENT with a
healthy loop = disabled/transport-not-configured.

### `ISOLATED_FIXTURE_paper_eod.png` ↔ `section_paper_eod.json`
| field | JSON | screenshot |
|---|---|---|
| official_telegram intraday | last_push_intraday 2026-08-14T19:45:17… | 2026-08-14T19:45:17 |
| official_telegram long-term | 2026-09-10T20:30:49… ticker ORCL | 2026-09-10T20:30:49 (ORCL) |
| official_telegram earnings-heads-up | null | — |
| eod_reconciliation.alert_counts | official 0 / experimental 355 / intelligence_events 9843 | official 0 / experimental 355 / intelligence_events 9843 |
| status | PARTIAL / STALE | PARTIAL / STALE badge |

Three **separate** ledger cards (Original / Experimental / PIV) with the banner
*"Original / Experimental / PIV paper are SEPARATE ledgers — never one merged
positions count."* Official count (`dispatch_audit.alerts` = 0) is shown
distinct from the comingled experimental count (355).

### `ISOLATED_FIXTURE_v2_active_strategy.png`
- fingerprint `11107198c5b81237`, status `PAPER_CANDIDATE`, horizon 10 td,
  real-capital **BLOCKED**, shorts **BLOCKED**.
- **5 independent health signals, each on its own line:** process health DOWN ·
  data state CURRENT · coverage INCOMPLETE_COVERAGE · pricing READY · activity
  NO_OPPORTUNITIES. Plus a separate *Event source readiness* card (source ok,
  DB read age, upstream poll age) and a *delivery drain ON* line.
- `$300,000` campaign ledger: starting/cash/available 300000, open 0, closed 0,
  BUY/SELL 0/0, realized P&L 0, EXIT_UNRESOLVED 0.
- Scoped funnel: Form-4 code-P 8/0 · distinct issuers 3/0 · **near-miss `2 ADC,
  INTC`** · ≥2-distinct clusters `1 ABCL` · **stale (entry > 3 sessions old) 1**
  (the ABCL `SKIPPED_ENTRY_STALE` episode) · delivery
  SENT/HELD/RETRY/FAILED/AMBIGUOUS/PENDING = 0/0/0/0/0/0 · interpretation
  STRATEGY_SELECTIVE.
- Banner: *"Alert delivery — this is a TRADING lane (separate from Intelligence
  & Experimental)"* → Trading / Intelligence / Experimental distinction explicit.

### `ISOLATED_FIXTURE_overview.png`
- Active V2 first-class card at the top (fp, campaign cash 300000/300000,
  delivery counters, EOD state PARTIAL).
- **Runtime health split per domain:** overall FAILED · Original FAILED ·
  Experimental DEGRADED · Intelligence DEGRADED · Telegram send READY · Telegram
  receive DOWN · Forward outcomes DEGRADED · EOD PARTIAL.
- Alerts card: official generated/sent/failed/held 0/0/0/0, official status
  NO_ACTIVE_PRODUCER, **Experimental external BLOCKED**, Experimental eligible
  false.
- *Source status (false-zero guard)* table: every domain shows its authoritative
  source + an honest "not running (no runtime_metadata.json)" note — a 0 is
  rendered as `NO_ACTIVE_PRODUCER` / `STALE`, never as a real zero.

### `ISOLATED_FIXTURE_original_quant.png`, `premarket.png`, `validation.png`
Render fully (98 / 152 / 165 KB); Original quant funnel, premarket movers and
the strategy-validation section respectively — unchanged this task, captured for
completeness.

## Requirement coverage

| §4 dashboard item | where |
|---|---|
| delivery disabled / pending / sending-ambiguous / sent / failed / expired | Intelligence → Card delivery |
| last actual send time + acks across official domains | Paper/EOD → Official Telegram (intraday / long-term / earnings) |
| source / processing / pricing / coverage / delivery health separately | Active V2 → 5 independent signals + Event source readiness; Overview → Runtime split |
| scoped V2 funnel | Active V2 → funnel (`ADC, INTC` near-miss, `ABCL` cluster, stale=1) |
| correct current-session EOD state | Paper/EOD → EOD reconciliation PARTIAL/STALE; Overview EOD state |
| startup waiting / ready / failure states | Overview → Runtime + Source status (false-zero guard) |
| existing positions visible during source/delivery failure | Active V2 ledger card renders regardless of producer health |
| Trading / Intelligence / Experimental distinction | Active V2 "TRADING lane" banner; Experimental "internal only" banner; Intelligence "descriptive, no forward-return" banner |

## Accounting corrections visible on the dashboard

`authoritative_read_model.quant_signals()` exposes `published_proxy_alerts_today`
= `dispatch_audit.alerts` count (Original-attributable). The comingled
`metrics:<date>:quant:*` counter is **not** presented as an official
publication count anywhere in the SPA. See `accounting_corrections.md`.
