# ERM nominee integrity audit: GAP_UP_10|SHORT|H10|L1 (2026-10-05)

**Scope.** Development 2019–2023 only. Metadata, bar dates and volumes, and ALL/raw factor ratios at the same timestamp. **No returns, CIs, screens or rankings.**

**Inputs.** The frozen Phase D archive at `C:\workspace\TalonX-erm\results\event_response_map_v1`, read only. It is loaded through the frozen `data.load`, with sha256 verification and the LOAD guard; `guard_state.json` is never written. Input hashes are in `lineage_summary.json`.

**New external metadata.** 2,254 SEC `-index-headers.html` files (development filings ≤ 2023-12-29), fetched 2026-10-05 inside the R5 off-hours window through the frozen `phase_d.Sec` client. They are stored in `_sec_pit/` with a `manifest.json` of sha256 values.

**Reproduce** with the frozen research venv, cwd = this worktree root, in this order:

| # | Command | Output |
|---|---|---|
| 1 | `python research/erm_nominee_audit/lineage_audit.py` | `lineage_events.csv`, `lineage_summary.json` |
| 2 | `python research/erm_nominee_audit/duplicate_audit.py` | `duplicates.csv`, `duplicates_summary.json` |
| 3 | `python research/erm_nominee_audit/classify.py` | `classified_events.csv`, `classification_summary.json` |
| 4 | `python research/erm_nominee_audit/adjustment_audit.py` | `adjustment_events.csv`, `adjustment_summary.json` |
| 5 | `python research/erm_nominee_audit/pit_rules.py` | `pit_events.csv`, `pit_additions.csv`, `pit_summary.json`, `sic_header_todo.json` |
| 6 | `python research/erm_nominee_audit/sic_pit_fetch.py` | network: SEC, off-hours only; resumable; `_sec_pit/` |
| 7 | `python research/erm_nominee_audit/sic_pit.py` | `sic_pit.csv`, `sic_pit_summary.json` |
| 8 | `python research/erm_nominee_audit/reconcile.py` | `reconciled_events.csv`, `reconciled_additions.csv`, `reconcile_summary.json` |
| 9 | `python -m pytest tests/test_erm_nominee_accounting_fixtures.py` | 9 synthetic accounting fixtures |

**Specification.** `docs/research/preregistration/ERM_NOMINEE_CORRECTION_SPEC_V1.md`.

## V2 (2026-10-05)

**Targeted metadata acquisitions** (frozen clients, R5 off-hours):

| Script | What it fetches | Stored in |
|---|---|---|
| `f345_2018_fetch.py` | 2018 Form 3/4/5 datasets | `_sec_v2/` |
| `subs_v2_fetch.py` | submissions for 36 verified issuers | `_sec_v2/` |
| `etf_distributions_fetch.py` | ETF cash dividends, 2019–2023 | `_alpaca_v2/` |

Filing headers for new accessions are fetched inline by `v2_manifest.py` into `_sec_v2/`.

**Reproduce** (cwd = this worktree root):

| # | Command | Output / note |
|---|---|---|
| 1 | `python research/erm_nominee_audit/v2_manifest.py` | `v2/manifest.csv`, `v2/unresolved_manifest.csv`, `v2/duplicate_groups.csv` |
| 2 | `python research/erm_nominee_audit/v2_summary.py` | `v2/summary.json` |
| 3 | `python -m pytest tests/test_erm_nominee_v2_rules.py tests/test_erm_nominee_accounting_fixtures.py` | 28 fixtures |

**Determinism.** Two full runs produced the same `v2/manifest.csv` sha256, `1a1fd666ed3c453197b86e87235a6356da17350b31908d7e473f2d5c1a860040`.

**Specification.** `docs/research/preregistration/ERM_NOMINEE_CORRECTION_SPEC_V2.md`.
