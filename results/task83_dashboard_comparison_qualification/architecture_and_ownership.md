# Task 83 — Architecture and Ownership Map

Start SHA: `e15345034666dd7d8670ff39f872c5986b89bdbd` (Task 82 tip).

## Re-audit of Task 82 isolation (performed before any edit)

| Boundary | Task 82 mechanism | Re-audit result |
|---|---|---|
| Redis keys | Original `TALONX_REDIS_URL` (DB 0); PIV `TALONX_PIV_REDIS_URL` (DB 1) | unchanged; collector only *reads* both |
| Redis Pub/Sub | Original `talonx:*`; PIV **must** use `talonx:piv:*` (server-wide bus) | unchanged; `validate_piv_isolation` still rejects overlap even across DBs (scenario 7) |
| Quant persistence | Original `TALONX_QUANT_DB_PATH`; PIV `<state_dir>/piv_quant.db` (reserved, unused) | unchanged; surfaced as an explicit limitation (§6) |
| Runtime evidence | Original stores/logs; PIV `TALONX_PIV_STATE_DIR` | unchanged; collector writes to neither |
| Telegram outbound | Original only; PIV disabled + rejected by isolation validation | unchanged; scenario 10 asserts PIV `EventBus.telegram_send is None` |
| Telegram inbound | Original only; PIV listener not built when disabled | unchanged; scenario 11 |
| Process role | one Original; one `--isolated-parallel` PIV | unchanged; `process_guard` used unmodified, driven by genuine subprocesses in scenarios 4–6, 19 |
| Session identity | credential-free config hash includes state dir / Quant path / Redis identity / channels / namespace / telegram-disabled | unchanged; recovery-required still wins over startup markers (scenario 18) |

No Task 82 file was modified by Task 83 except `talonx_piv/observability.py` (additive
`capability_limitations` section only — no behaviour change to existing keys).

## New component: `talonx_compare/` (passive observer)

```
                 Redis DB 0                         Redis DB 1
     Original ── talonx:* ─────────┐      ┌──────── talonx:piv:*  ── PIV
        │  (writes, owns)          │      │        (writes, owns)   │
        │                    (SUBSCRIBE only, never publish/ack)    │
        │                          ▼      ▼                         │
        │                  ┌───────────────────────┐               │
   metrics:{date}:* ──read─▶   ComparisonCollector  ◀─read── PIV state dir
   (DB 0 counters)         │   (talonx_compare)    │        (*.json / *.jsonl)
        │                  └───────────┬───────────┘               │
        │                              │ append-only, dedup by _id │
        │                              ▼                           │
        │            results/task83_.../daily_evidence/<date>/     │
        │            manifest.json (immutable) · original_events.jsonl ·
        │            piv_records.jsonl · comparison.json · divergences.json ·
        │            telegram.json · diagnostics.json · file_hashes.json
        │                              │                           │
        ▼                              ▼                           ▼
  dashboard_web.py  ◀── talonx_compare.dashboard_views ──▶  talonx_dispatch/app.py
  GET /views/original                                        radio: "PIV & Comparison"
  GET /views/piv                                             (read-only)
  GET /views/compare
```

### Ownership contract (additions)

| Resource | Owner | Collector / dashboards |
|---|---|---|
| `TALONX_COMPARE_STATE_DIR` (`results/task83_.../collector_runtime`) | collector | cursors, dedup index, `collector.lock` — **its own**, never a PIV/Original path |
| `TALONX_COMPARE_EVIDENCE_ROOT` (`results/task83_.../daily_evidence`) | collector | date-partitioned evidence |
| namespace `talonx:compare` | collector | names its own storage only — it never publishes, so this is not a Pub/Sub prefix |
| Original Redis (DB 0) | Original | collector `ping` / `scan_iter` / `mget` only; `RecordingFakeRedis.write_calls == []` asserted (scenarios 9, 13, 20) |
| PIV Redis (DB 1) | PIV | subscribe-only; buffered in memory, never re-emitted (scenario 9) |
| PIV state dir | PIV | read-only; `execution_ownership.lock` never opened (scenario 19) |
| Original/PIV session ids, cooldowns, locks, metrics keys | Original / PIV | never reused — collector mints no session id and holds only `collector.lock` |

### Read-only guarantees

- Collector: no `publish`, no `set`/`incr`/`delete`, no writes under Original/PIV dirs.
  Verified by a recording fake Redis (`talonx_compare.testing.FakeRedis.write_calls`)
  and by `_server.publish_log` staying empty across a full pass.
- Browser routes: all `GET`; `test_all_routes_are_get_only` + `test_no_mutating_endpoints`.
- Streamlit section: `test_no_control_widgets_in_piv_comparison_section` walks the AST of
  `render_piv_comparison` and rejects every mutating widget; only `selectbox` (choose which
  archived date to *view*) is allowed.

## Files changed

| File | Change |
|---|---|
| `talonx_compare/` (new package) | `__init__`, `config`, `identity`, `health`, `divergence`, `alignment`, `evidence`, `projections`, `collector`, `archive`, `dashboard_views`, `runner`, `__main__`, `testing` |
| `dashboard_web.py` | +3 GET routes (`/views/original|piv|compare`); `compare_config` app key |
| `dashboard_web_static/index.html` | +Live/Original/PIV/Compare tab nav + read-only fetch/render JS |
| `talonx_dispatch/app.py` | +`render_piv_comparison()`; +radio option "🔬 PIV & Comparison" |
| `talonx_piv/observability.py` | +`capability_limitations.durable_quant_state_store` (additive) |
| `tests/test_task83_*.py` (5 new files) | health contract, collector, browser, streamlit, offline dual-run |

Protected `talonx_quant/{strategy,indicators,consumer,config}.py`: **unchanged**.
