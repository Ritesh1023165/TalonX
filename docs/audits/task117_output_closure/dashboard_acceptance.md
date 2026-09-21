# Dashboard acceptance — D1 / D2 / D3 (isolated data)

**No browser / screenshot tool is available in this session.** The SPA (`dashboard_web.py` →
`talonx_ops/dashboard_read.py` → `/api/section/<name>`) is verified through its **read-model
API surface** against isolated / preserved data. Each check below is reproducible.

---

## D1 — V2 funnel scoped to the enforced 39-name allowlist

`build_funnel(db_path="v2_lane.db", as_of=2026-09-10)` on the preserved ledger:

| | `execution_allowlist="auto"` (new default) | `execution_allowlist=None` (pre-D1) |
|---|---|---|
| `scope.execution_scope_enforced` | `True` | `False` |
| `scope.execution_scope_count` | `39` | `None` |
| `clusters.single_insider_near_miss_issuers` | **`["ADC", "INTC"]`** | `["ADC", "INTC", "MUNEX", "NMZ", "PML"]` |
| `clusters.cluster_symbols` | `["ABCL"]` | `["ABCL"]` |

The out-of-scope municipal closed-end funds (MUNEX, NMZ, PML) no longer appear in the operator's
near-miss list. `dashboard_read.v2_active_strategy()` calls `build_funnel(...)` with the default,
so the SPA's "Active V2" funnel now matches what the live companion actually evaluates.
**PASS.**

## D2 — logical Telegram poller ownership on Windows

`talonx_ops.supervisor.count_telegram_get_updates_owners()`:

| scenario (mocked process table) | result |
|---|---|
| app stopped (no `run_talonx.py`) | `0` |
| venv shim (pid A) + its worker child (pid B), both `… run_talonx.py` | **`1`** (B's ancestor A is also a match → B is a shim child) |
| two independent launchers, each shim+worker | `2` (genuine second owner) |
| a shell command that merely *mentions* `run_talonx.py` as a string | `0` (not an argv token) |
| `run_talonx.py --skip-dispatch` | `0` |

`_telegram_receive_state()` in `dashboard_read.py` reads `telegram_get_updates_owners` and only
flags `DEGRADED` when `> 1`, so the false "2 owners → DEGRADED" on the SPA is resolved for the
shim+worker case while a real second poller still trips it. Tests:
`tests/test_task117_telegram_owner_dedup.py` (4). **PASS.**

## D3 — current-session EOD state + truthful valuation timestamps

`DashboardReadModel._v2_eod_state(es, now=2026-09-11T12:00Z)` with the reconciliation store's
latest row still being for `2026-09-10`:

```
{
  "state": "NOT_DUE_YET",                       # the market-phase state for 2026-09-11 stands
  "session_date": "2026-09-11",
  "prior_reconciliation_session": "2026-09-10",
  "prior_reconciliation_note": "latest reconciliation row is for 2026-09-10, not the current
                                session 2026-09-11 -- not applied to this tile"
}
```

Previously the tile showed the 2026-09-10 `PARTIAL` as if it were the current session. Now a
prior-session row is **surfaced separately** and never overrides the current state.
`_v2_position_lifecycle(row, now=self.now)` likewise computes `days_held` from the read-model
`now`, not `datetime.now()`. **PASS.**

## Ingestion / processing / queued / sent — shown separately

`DeliveryOutbox.counts_by_state()` now yields `{PENDING, SENT, EXPIRED, FAILED, SUPPRESSED}`
distinctly, so a dashboard tile can render **queued (PENDING) ≠ sent (SENT)** and a healthy
poll loop no longer implies delivery. The tile itself (a `paper_eod` / `intelligence` section
addition) is proposed in `remaining_gaps.md` — the data separation is in place.

## Not done here

- **Rendered screenshots** — no browser tool. If a reviewer runs the SPA locally against
  `results/task117_day3_eod_20260910T202656Z/db/*.postclose` (copied to `~/.talonx/`), the
  "Active V2" funnel will show `[ADC, INTC]` and the EOD tile will not show a stale PARTIAL.
- **D4 startup-verdict** SPA behaviour — not changed this task (see `remaining_gaps.md`).
