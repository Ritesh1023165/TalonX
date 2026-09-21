# scripts/

Classification (Task 105). Full operational guidance: `docs/OPERATIONS.md`; deprecation status:
`docs/COMPATIBILITY.md`.

## PRIMARY

| script | use |
|---|---|
| `start_talonx_supervised.ps1` | **the one recommended startup** — `python -m talonx_ops.supervisor run` (Original + Experimental + Intelligence + `:8787`) |

## UTILITY (fine to use; not the whole-system path)

| script | use |
|---|---|
| `start_dashboard_web.ps1` / `stop_dashboard_web.ps1` | `:8787` cockpit only, without the supervisor |
| `stop_talonx.ps1` | stop the legacy `run_talonx.py` + Streamlit pair |
| `ticker_funnel_report.py` | read-only per-ticker funnel diagnostic |

## LEGACY / COMPATIBILITY (do NOT use as the default)

| script | note |
|---|---|
| `start_talonx.ps1` | `run_talonx.py` + Streamlit `:8501` only — no supervisor, no Experimental/Intelligence. Header marked LEGACY. Target of `register_scheduled_tasks.ps1`'s 10am task. |
| `register_scheduled_tasks.ps1` | schedules the LEGACY path — unchanged |

## RESEARCH / FIXTURE-GEN (reproduce a frozen study or regenerate a checked-in fixture)

| script | what it reproduces |
|---|---|
| `download_historical_1m.py` | downloads real 1-min market data into `data/` (gitignored) |
| `run_historical_regimes.py` | runs the frozen strategy across historical regime windows |
| `run_task56_holdout.py` · `run_task56_window.py` · `analyze_task56_holdout.py` | Task 56 independent-family holdout replay + diagnostics (SHA-gated) |
| `task25_live_shadow_capture.py` | Task 25 live shadow capture |
| `gen_sample_multi_trade_1m.py` | deterministic generator for `examples/data/sample_multi_trade_1m.csv` — `TEST_FIXTURE_ONLY` |
| `generate_task83_r2_rehearsal_evidence.py` · `verify_task83_r2_content_commit.py` · `verify_task83_r2_final_manifest.py` | Task 83-R2 evidence generation + manifest verification |

These read/write `results/task*` paths with SHA verification — **do not rename or move them or
their inputs** (`results/task105_repository_cleanup/backtest_preservation_manifest.md`).
