# Task 131 — Complete SPA Dashboard Acceptance — evidence index

Durable pointer (tracked in Git) to the bulky, fixture-backed evidence
bundle for the Complete SPA Dashboard Acceptance pass, which itself
lives under the gitignored `results/` directory (screenshots, raw API
JSON, and a paper-engine reconciliation snapshot are not source code and
are not tracked, matching every other acceptance record in this repo).

- **Full requirement-by-requirement verdicts, screenshots, API
  evidence, reconciliation, browser diagnostics, exact commands, and
  fixture provenance**:
  `results/task131_spa_final_acceptance/SPA_ACCEPTANCE.md`
- **Packaged for review/attachment**:
  `results/task131_spa_final_acceptance/task131_spa_final_acceptance.zip`
  (built from the same directory, after this commit)
- **Design rationale**: `docs/research/TASK131_REMEDIATION_DESIGN.md`,
  "Complete SPA Dashboard Acceptance" section
- **Runtime provenance / test counts / candidate SHA**:
  `docs/research/TASK131_RETROSPECTIVE.md`, "Complete SPA Dashboard
  Acceptance runtime provenance log" section

## One-paragraph summary

Four real dashboard-correctness findings from a review of commit
`b642b3d`'s Broad Discovery tab were fixed, entirely within
`talonx_ops/dashboard_read.py` and `dashboard_web_static/index.html`
(no `talonx_v2/` file touched — the concurrent-admission fix and
temporal protections from the prior pass are preserved unmodified,
fingerprint `11107198c5b81237` unchanged): (1) upstream freshness is no
longer conflated with a local database-read timestamp — a new,
independently-queried `latest_source_event_utc` is the only source for
`upstream_data_as_of_utc`, explicitly `UNKNOWN` when unavailable; (2)
empty discovery-funnel states now carry a purely factual statement plus
independent operating-evidence signals, never an inferred reason — a
genuine gap in the database-unavailable branch (no explanatory text at
all) was found and fixed too; (3) real per-position/per-closed-trade
detail — entry data, a real quote-based mark or explicit unavailability,
real realized P&L — is now shown, reused directly from the same paper-
performance computation the Active V2 tab already makes, reconciled by
dict-equality against an independent direct call; (4) two real
narrow-screen CSS overflow bugs (a Grid/Flex `min-width:auto` default,
and a `.kv` flex-wrap edge case) were root-caused via actual rendering
and fixed at the shared-component level, confirmed via screenshots to
also repair the pre-existing characteristic on the untouched Active V2
and Overview tabs, with zero desktop regression. Verified throughout
with real headless-Chrome screenshots against two isolated fixtures
covering every required scenario; the full repository test suite (4655
passed, 4 pre-existing failures unchanged by exact name, 6 skipped)
confirms zero new regressions.
