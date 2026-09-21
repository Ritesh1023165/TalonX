# Task 83 — Browser & Streamlit Route/Section Inventory

Every surface below is **read-only**. No route or widget starts a session,
places an order, changes a setting, authorizes an experiment, or toggles a
safety control.

## Browser dashboard — `dashboard_web.py` (localhost:8787)

| Method | Path | Added? | Read-only | Purpose |
|---|---|---|---|---|
| GET | `/` | pre-existing | yes | serves `index.html` (now with Live/Original/PIV/Compare tab nav) |
| GET | `/ws` | pre-existing | yes | live pipeline WebSocket snapshot |
| GET | `/static/*` | pre-existing | yes | static assets |
| GET | `/piv/status` | pre-existing (Task 78I) | yes | `observability.build_integrated_projection` — unchanged contract |
| **GET** | **`/views/original`** | **Task 83** | yes | Redis health, Warmup/Quant/Brain/Core/Dispatch/Telegram funnel, local simulated-paper (`SIMULATED_PAPER`) |
| **GET** | **`/views/piv`** | **Task 83** | yes | provider/readiness/freshness, stale/recovery, quant funnel + rejections, decisions/shadow/PAPER lifecycle, reconciliation/EOD, `UNVALIDATED` + feed/exec mode + real-capital prohibition + QuantStateStore limitation |
| **GET** | **`/views/compare`** | **Task 83** | yes | per-stage totals, per-symbol agreement/divergence, missing/late stages + reason codes, separate `SIMULATED_PAPER` / `PIV_SHADOW` / `PIV_PAPER` / `EXPERIMENTAL` streams; `?date=YYYY-MM-DD` selects an archived day |

- All routes registered with `app.router.add_get(...)` only. `test_all_routes_are_get_only`
  asserts every route's method ∈ {GET, HEAD}. `test_no_mutating_endpoints` rejects any path
  containing start/launch/order/submit/auth/approve/kill/enable/disable/settings/config/shutdown/activate.
- A read failure returns an explicit HTTP 500 with an error body (`*_VIEW_READ_FAILED`),
  never a silently-empty 200.
- `index.html` tab JS issues `fetch("/views/" + view, {method:"GET"})` only, on a 5 s
  poll while a non-Live tab is active. Health badges are colour-coded by state; the
  last-update timestamp and age are shown next to every stage.

## Streamlit dashboard — `talonx_dispatch/app.py`

| Section (radio) | Added? | Behaviour |
|---|---|---|
| 📈 Intraday Monitor | pre-existing | unchanged |
| 💎 Long-Term Radar | pre-existing | unchanged |
| 📊 Daily Funnel & Metrics | pre-existing | unchanged |
| ⚙️ Watchlist & Settings | pre-existing | unchanged (this section still owns the only writes in app.py — ticker add/remove — outside Task 83 scope) |
| **🔬 PIV & Comparison** | **Task 83** | read-only; `render_piv_comparison()` |

`render_piv_comparison()` panels:

- trading-date / session `selectbox` (chooses which archived day to *view* — mutates nothing)
- live PIV identity + strategy `UNVALIDATED` + feed/execution mode metrics
- archived Original vs PIV funnels (per stage)
- readiness / freshness exclusions
- decisions & reason codes
- notification & lifecycle records
- outcomes by execution class (`SIMULATED_PAPER` / `PIV_SHADOW` / `PIV_PAPER` / `EXPERIMENTAL`, never combined)
- EOD reconciliation & divergence table
- source-health & archive-integrity diagnostics (file-hash verification result + problems)
- known capability limitation (QuantStateStore) + unresolved IEX timestamp question

Widget audit (`test_no_control_widgets_in_piv_comparison_section`): the AST of
`render_piv_comparison` calls only `st.{subheader,caption,selectbox,columns,metric,markdown,dataframe,json,write,info,divider}`.
No `button`, `form`, `form_submit_button`, `download_button`, `file_uploader`,
`text_input`, `number_input`, `checkbox`, `toggle`, `slider`, `text_area`,
`data_editor`, `chat_input`, `camera_input`, or `color_picker`.

CLI (read-only, not run by Task 83): `python -m talonx_compare {collect-once|status|verify <date>|run}`.
`run` only ever SUBSCRIBEs to the observed channels.
