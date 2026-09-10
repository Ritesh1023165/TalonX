# InsiderStore before / after the timestamp work

## Correction manifest outcome

`timestamp_correction_manifest.csv` — 22 rows keyed by stable source identity
(`{accession}|acceptance`):

| classification | rows | action |
|---|---:|---|
| `ALREADY_CORRECT` | 10 | none — `data.sec.gov/submissions` `acceptanceDateTime` is genuine UTC (10/10 SGML↔JSON cross-reference); the parser now agrees. |
| `UNRESOLVED` | 12 | **left unchanged** — the persisted S1–S3 `accepted_at_utc` sits a consistent ~4 h behind `retrieved_at` with a hard 4 h floor, which contradicts the SGML↔JSON evidence. No live EDGAR for the forward-dated 2026 accessions to break the tie. |
| `VERIFIED_CORRECTION` | **0** | — |

**0 VERIFIED_CORRECTION ⇒ no rebuild.** Nothing in the InsiderStore (or
`text_events`) is corrected by this task.

## Before / after — identical

| | value |
|---|---|
| `~/.talonx/ingestion_ledger.db` md5 | `2ae2105c6f51a4af4b3b80dc06e5f30f` — **unchanged** (this task never wrote to it) |
| `insider_filings` rows | 7,596 (unchanged) |
| `insider_transactions` rows | 33,400 (unchanged) |
| `text_events` rows | 9,843 (unchanged) |
| rows carrying an `acceptance_tz_*` flag | **0** — the earlier global-Eastern change was code + tests only, never run against production, and is now reverted |
| `accepted_at_utc` offset suffixes present | `+00:00` only (unchanged) |

## V2 episodes / intents / eligibility — before vs after

No change, and none possible:

- The frozen **Task 116 replay** reads the Task-107A parquet (`filing_date`
  column) and does **not** import `edgar_normalize` → provably unaffected by any
  acceptance-parsing change. 168 V2/research tests (incl. the replay) green.
- Live `from_insider_store` keys a missing `filing_date` on
  `accepted_at_utc.date()`. Under **both** timestamp readings (genuine UTC, or
  ET-mislabelled-as-UTC) the S1–S3 code-P records land on the **same ET calendar
  day**, so `cluster_engine` window / activation / `eligible_entry_session` are
  identical. The only in-scope cluster (ABCL) activated mid-August with an
  intra-RTH activation filing — unaffected either way.
- `form4_source.py` was reverted to `t.accepted_at_utc.date()` (the pre-task
  original) — no ET-date reinterpretation.

**`insiderstore_before_after` result: NO CHANGE.** No production migration is
proposed for execution; if the ~4 h anomaly is ever resolved against live EDGAR,
the (idempotent, reversible) rebuild steps in `deployment_candidate.md` apply.
