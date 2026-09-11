# Session final — 2026-09-11 (post-canonical-close)

**Canonical EOD executed**: `python -m talonx_ops.prospective close`,
`2026-09-11T20:09:38+01:00` (20:09:38Z) — **after** the 20:00:00Z expected
close, **well within** the 21:30:00Z deadline (no lateness to document).
**Verdict: PASS_WITH_FINDINGS.**

## EOD result

| check | result |
|---|---|
| V2 health / market feed | HEALTHY / HEALTHY |
| V2 cash | $300,000.00 (start $300,000.00 — 0 activity today) |
| V2 open/closed/unresolved | 0/0/0 |
| clusters ≥2 distinct insiders | 1 (ABCL, stale, unchanged episode id `07242bc857569f60`) |
| all 15 named invariant asserts | **PASS**, except `base_reconciliation: PARTIAL` (PIV not checked — no `piv_reader` injected, a known, pre-existing, non-blocking characteristic; `mismatches: []`, i.e. **no actual discrepancy found**) |
| shutdown | clean — checkpoint_daemon (pid 11700), v2_companion (552), supervisor (16524) all `stopped`, `residual_talonx_processes: []` |

**Verified independently, not merely from the close command's own report**:
`psutil.pid_exists()` on all three pids → `False`; no LISTENING socket on
8787/8760/8770/8501 (only TCP `TIME_WAIT`/stale `SYN_SENT` remnants —
normal post-shutdown noise, not an active listener); Redis
`ping() → True` — retained, responsive, not flushed or restarted.

## Final per-lane accounting (September 11 activity, campaign totals kept separate)

| lane | Sept 11 activity | campaign total | realized P&L | open/unresolved |
|---|---|---|---|---|
| **Original** | 0 published, 0 pushed | 0 trades all-time | $0 | 0 open |
| **V2** | 0 signals, 0 trades | 0 trades all-time (campaign started 2026-09-08) | $0, cash unchanged $300,000 | 0 open, 0 pending intents |
| **Intelligence** | 6 event cards delivered, aggregated into **1** Telegram message (message_id 720, this morning) | n/a (informational, not a trading lane) | n/a | 0 pending (`PENDING: 0`) |
| **Experimental** | **4 exits today** (VRT/STX/AMD/BLSH — per the canonical `base_reconciliation.experimental_paper.trades_today: 4`) | **9 trades all-time** (5 BUY across 2026-09-09/10, 4 SELL today) | **−$324.4662160270568** (canonical, `mismatches: []`) | **1 open (SPCX)** |

**The 5 Experimental entries span 2026-09-09 (VRT, BLSH) and 2026-09-10
(AMD, STX, SPCX) — not "five entries today."** Only the 4 exits are
today's activity, confirmed by the canonical EOD's own
`trades_today: 4` field, not asserted from memory.

## SPCX — final state at close

**Still open** (authoritative `experimental_paper.db.positions`,
unchanged through close): 16.865960 shares, entry $148.2276 (2026-09-10),
stop $144.6133, target $152.0633.

**Final valuation, timestamped**: last available bar **$151.2100
(2026-09-11T20:08:00Z)** — captured in the pre-close snapshot, one minute
before shutdown, the last real market observation this position will
receive until the next session. **Unrealized: +$50.30 (+2.01%)** — no
cost applied (position never closed), not fabricated, not backdated.
Price stayed below target ($152.0633) throughout — no target-hit event
occurred; the position was never forced or backdated to close for EOD.
**Carries over to Monday 2026-09-14 under its existing stop/target/gap
policy — not flattened.**

## Recovery-affected trades — kept separate from a clean track record

VRT, STX, AMD, BLSH (today's 4 exits) are each the **first-ever** real
exit through the Task 118A fix (deployed ~11:54Z) — **not** pooled with
V2's separate (zero-activity) track record, and **not** presented as an
established Experimental performance history. All four are losses; no
profitability claim follows from them. SPCX (currently open, unaffected
by any defect throughout) is not itself "recovery-affected" — its exit
path was always correctly wired (Task 118E's own trace).

## Deployment timeline (unchanged from Task 118G, reconfirmed)

| period | release SHA | window |
|---|---|---|
| 1 | `fb4b071` | `08:11:55Z` → `11:53:10Z` |
| 2 | `c88f4d4` | `11:54:30Z` → `15:50:06Z` |
| 3 | `5c0b3f3` | `15:51:18Z` → `20:09:11Z` (canonical close) |

**Warmup attribution, unchanged and preserved exactly**:
30/43 → **41/43** ordinary startup preseed; 41/43 → **42/43** the bounded
recovery sweep (exactly 1 symbol, logged); 42/43 → **43/43** subsequent
live accumulation (NUE, first observed READY `16:20:50Z` — the exact
transition time was never logged and is not invented). **This is a
bounded, once-per-startup sweep, not continuous mid-session recovery.**

## Remaining uncertainty — carried forward, not reopened without new evidence

Heartbeat-lapse locus (Task 118C) and the historical "45 candidates"
counter's source query (Task 118A/C) remain **unresolved**. **No active
blocking defect was observed at this session's close** — this is not the
same claim as "no defects exist anywhere," and is not presented as one.

## Evidence

Pre-close snapshot: `C:\Users\rites\talonx_activation_backups\task118h_pre_eod_snapshot_20260911T200911Z\`
(outside Git). Canonical close evidence:
`results/prospective_2026-09-11/{eod.json,final_report.md,terminal_summary.txt}`
(local, session directory).
