# TASK 95G — Precondition A — Identity Verification Report

Deterministic resolution of the identity-map rows Task 95F flagged `SECONDARY` / `LOW` / malformed. No fuzzy or AI matching.

## Operative use of the identity map in Task 95G

For Task 95G the identity map is used ONLY to (a) stitch the two RENAME pairs that appear as explicit REMOVE/ADD rows in the membership timeline (WLTW->WTW 2022-01-10, CDAY->DAY 2024-02-01) and (b) document terminations. Every other MERGER_SUCCESSOR/ACQUIRED/FAILED row is a pure TERMINATION: the historical ticker's Alpaca bar series ends at the corporate-action date on its own, and the named 'successor' is a DIFFERENT company already in the index under its own ticker (no return-series is ever remapped). Pure ticker renames not in the changes table (FB->META, COG->CTRA, ANTM->ELV, VIAC->PARA, FISV->FI, RE->EG, PKI->RVTY, PEAK->DOC) are handled implicitly: the Task 95F backward walk carries the CURRENT ticker back through history, and Alpaca serves that ticker's full continuous series (verified in Task 95F price proof: META/WTW/ELV all n=1915 from 2019-01-02).

## Flagged rows — resolution

| historical_symbol | status | change_type | valid_to | successor (in-universe) | confidence | detail |
|---|---|---|---|---|---|---|
| ALXN | **RESOLVED** | ACQUIRED_FOREIGN_PARENT | 2021-07-21 | — | PRIMARY | Alexion Pharmaceuticals acquired by AstraZeneca plc (LSE/Nasdaq ADR AZN, NOT an S&P 500 member). ALXN simply terminates on deal close 2021-07-21. No in-universe return-series mapping. Source: AstraZeneca completion press release 2021-07-21; Wikipedia 'Historical components' REMOVE row. |
| KSU | **RESOLVED** | ACQUIRED_FOREIGN_PARENT | 2021-12-14 | — | PRIMARY | Kansas City Southern acquired by Canadian Pacific Railway (CP, TSX-primary; CP was NOT an S&P 500 member). KSU terminates on close 2021-12-14. No in-universe mapping. Source: CP/KCS completion notice. |
| VAR | **RESOLVED** | ACQUIRED_FOREIGN_PARENT | 2021-04-15 | — | PRIMARY | Varian Medical Systems acquired by Siemens Healthineers AG (XETRA SHL; not an S&P 500 member). VAR terminates on close 2021-04-15. Source: Siemens Healthineers completion press release. |
| AXE | **EXCLUDED_WITH_REASON** |  |  | — | n/a | Row is incorrect/legacy: Anixter International (AXE) left the S&P 500 in 2018 (before the 2019-2026 window) and was acquired by WESCO International (WCC), not Insight Enterprises (NSIT). AXE does not appear in the Task 95F 2019-2026 removed-name set. Dropped from the map. |
| MXPS | **EXCLUDED_WITH_REASON** |  |  | — | n/a | Placeholder row, not a real security. Dropped. |
| CTRA_OLD_COG | **EXCLUDED_WITH_REASON** |  |  | — | n/a | Malformed synthetic key; superseded by the explicit COG->CTRA RENAME row. Dropped. |

## Summary

- Resolved: 3 — ALXN, KSU, VAR (all: foreign-parent acquisition, ticker terminates, no in-universe remap)
- Excluded with reason: 3 — AXE, MXPS, CTRA_OLD_COG (legacy/incorrect/placeholder rows dropped)
- Remaining PRIMARY rows in `ticker_identity_map.csv`: unchanged, previously verified in Task 95F.
- **No unresolved row blocks Task 95G.** The two changes-table renames (WLTW/WTW, CDAY/DAY) are the only rows the panel builder actively consumes; everything else is a natural termination.
