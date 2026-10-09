# POST_DELIVERY_ALERT_MARKOUT_V1: activation record (configuration locked 2026-10-09)

**Output.** *Post-delivery price markout under stated cost assumptions*. Not an executable fill, realised P&L or
portfolio return.

## Owner approval (activation-preparation instruction, 2026-10-09)

**Approved.**
- Protocol revision 2. The fingerprint **`c812a3e65e4018a5`** was verified against the code; the parameters are
  unchanged.
- 5-minute reaction delay.
- 30-minute interval with exact target bars.
- 60 s maximum quote age.
- Half spread at entry + half spread at exit + **5 bps total additional assumed cost** (an *unsupported modelling
  assumption*, not measured slippage).
- First delivery per symbol per session, selected before any price is inspected. An uncertain first delivery excludes
  that symbol/session, with no substitution.
- Delivery tracing **REQUIRED**.
- 20 sessions.
- Final reporting only after every completion check passes.
- Tracing deployment and one daily off-hours collector.

**Not authorised.** Pricing earlier alerts, changing research rules, or claiming profitability.

**Locked config:** `POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json`. It contains the approval, the protocol
fingerprint and parameters, and the SHA-256 of each implementation file:
- `post_delivery_markout.py`
- `post_delivery_acquisition.py`
- `post_delivery_collector.py`
- `talonx_opportunity/delivery_trace.py`

**Every run revalidates it** (`load_activation(require_integrity=True)`). Any changed file makes the run
`NOT_APPROVED: INTEGRITY_FAILED`, so an earlier hash can never cover changed code.

## Calendar (XNYS via `talonx_opportunity.phases.trading_window`; verified by test)

| Item | UTC | Europe/London |
|---|---|---|
| Activation boundary (window opens; earlier alerts are never admitted) | 2026-10-19 00:00Z | 01:00 BST |
| First session (regular 13:30–20:00Z) | 2026-10-19 | 14:30–21:00 BST |
| UK DST change | 2026-10-25 | BST → GMT |
| US DST change (close becomes 21:00Z from 2026-11-02) | 2026-11-01 | — |
| Last (20th) session | 2026-11-13 (14:30–21:00Z) | 14:30–21:00 GMT |
| Final observation deadline (close of 2026-11-17 + 60 min) | **2026-11-17 22:00Z** | **22:00 GMT** |
| Final-report eligibility | ≥ 2026-11-17 22:00Z **and** every completion check passes | — |

**Sessions:** 2026-10-19 … 10-23, 10-26 … 10-30, 11-02 … 11-06, 11-09 … 11-13. There are no holidays and no half days
in the period.

**Session deadline** = close of the second subsequent session + 60 min.

## R5 finding

The authoritative definition is in `research/event_response_map_v1/data.py` ("LOCK REV 2 (R5)") and the ERM
`transport.py`: Alpaca and SEC calls are refused on **weekdays 09:00–16:30 America/New_York, DST-aware**.
- The "13:00–20:30 UTC" wording seen earlier is that rule's **EDT** rendering. In EST the rule is 14:00–21:30 UTC.
- There is no genuine conflict, and no restriction was changed.
- The schedule avoids **both** the ET rule and the fixed 13:00–20:30 UTC form, enforced by test.
- `post_delivery_acquisition.r5_permitted` also refuses any request inside R5.

## Schedule (Windows Task Scheduler, `\TalonX\PDM_V1_Collector`)

**Trigger:** daily **00:15 Europe/London** (the machine's local zone).
- = **23:15Z** while BST (to 2026-10-24); = **00:15Z** while GMT (from 2026-10-26).
- 2026-10-25 00:15 occurs before the 02:00 change, so it is BST (23:15Z on 10-24).
- Each run therefore falls after the previous session's close + 60 min: 21:00Z in EDT and 22:00Z in EST.
- Each session gets at least 2 runs before its deadline (test).
- `StartBoundary` 2026-10-19 00:15 local; `EndBoundary` 2026-11-18 12:00 local. The last run, 2026-11-18 00:15Z, is a
  reconcile-only recovery run, because it is after the final deadline.

**Command** (working directory `C:\workspace\TalonX`):
```
C:\workspace\TalonX\.venv\Scripts\python.exe -m talonx_paperperf.post_delivery_collector
    --config C:\workspace\TalonX\docs\research\protocols\POST_DELIVERY_ALERT_MARKOUT_V1_APPROVED_CONFIG.json
    --enable --budget-s 900
```

**Guards.**
- Scheduler: `MultipleInstancesPolicy=IgnoreNew` and a 30-minute execution limit.
- Collector: its own lock (an overlapping run is refused) and a 900 s request budget.
- Provider limits: 40 requests/min, 2 retries, ≤ 5 quote pages, ≤ 200 observations per run.
- **Scope:**
  - No request before the activation boundary.
  - No new admission outside the 20 sessions. After the last session, only outstanding in-scope observations are
    fetched, until their own deadlines.
  - At or after the endpoint, the run reconciles and writes status only. Nothing late is fetched and nothing is
    reopened.
- Each run logs scheduled vs actual time and missed days to `results/post_delivery_markout_ops/runs.jsonl`, with
  operational status only; no return value is ever written there.
- There is no Telegram summary and no rolling outcome publication.

**Machine requirements** (unchanged, not modified):
- The user is logged in: interactive token, the same as the existing TalonX tasks.
- The machine is on AC power (existing convention: no start on battery).
- The network is available.

`StartWhenAvailable` runs a missed instance late. Lateness and missed days are recorded, and deadlines are never
extended.

## Final reporting

`final_report()` returns numbers only if **all** of these hold:
- the 20-session period has ended;
- the final deadline has passed;
- every in-scope source delivery has been registered, with none still in flight;
- every selected observation is terminal;
- the implementation integrity check passes;
- the protocol fingerprint matches.

Otherwise it returns `INCOMPLETE` (or `NOT_AVAILABLE_BEFORE_ENDPOINT`) with the failing checks. There is no
profitability verdict in either case.

## Rollback

1. **First**, disable the collector: `schtasks /change /tn "\TalonX\PDM_V1_Collector" /disable`.
2. Optionally remove it later with `/delete`.
3. Keep `results/post_delivery_markout*` as evidence.

Tracing can stay; it never affects delivery. To remove it, revert `Promoter._drain_signal` to the plain `drain(...)`
call and make a declared promotion restart.

None of this pauses review alerts, replays messages, resumes VR, alters other studies or deletes collected evidence.
