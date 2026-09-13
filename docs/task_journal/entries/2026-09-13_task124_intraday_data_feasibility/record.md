# Record

## Baseline verification (start of task)

- Research branch `research/talonx-profitability-2026-09` HEAD:
  `eee821f78341fc05c75e951fdbaf900a8999ffb4` (matches expected `eee821f`
  prefix exactly).
- Release worktree (`C:\workspace\TalonX`), branch
  `research/talonx-strategy-validation`, HEAD:
  `f28986999eec5e313cfc89db24e4dbacfb378891` (matches expected exactly),
  `git status --short` clean.
- No `talonx-*` python process running, no listening ports on
  8787/8770/8760/8501. Redis reachable (`PING` → True), 0 `talonx:*`
  keys — consistent with "production remains stopped" throughout this
  task.

## Actions taken, in order (all times UTC, 2026-09-13)

1. Read Task 123's frozen protocol, results, and journal outcome to
   confirm the exact decision being carried forward (§0 of
   `TASK124_INTRADAY_DATA_FEASIBILITY.md`).
2. Wrote `research/scripts/task124_data_manifest.py` (Part 2) — queries
   the live `talonx_ops.watchlist_coverage.build_coverage_map()`
   (release worktree, imported via `sys.path` insertion, never
   modified) cross-referenced against the three known local price
   directories (`task95g_broad_cross_sectional/_daily`,
   `task107a_form4_feasibility/_prices`,
   `task93_alpha_foundation/_canonical_data`). Ran once,
   ~06:55:39 UTC → `results/task124_intraday_feasibility/coverage_manifest.json`.
3. Wrote `research/scripts/task124_alpaca_feed_probe.py` (Part 3),
   reusing the exact request/credential pattern from
   `research/scripts/task63r_probe_alpaca_feeds.py` (release worktree,
   read-only). Credentials loaded via `dotenv.load_dotenv(...,
   override=False)` from the release worktree's `.env`; only presence
   of `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY` was checked, values were
   never printed or logged.
4. First probe run (~06:5x UTC) used `probe_2_older_period` default
   date `2024-01-15`, which is Martin Luther King Jr. Day — a US market
   holiday. Both SIP and IEX returned HTTP 200 with 0 bars
   (`EMPTY_RESPONSE`). This was investigated with ad-hoc follow-up
   requests (AAPL at 2024-03-01, 2023-03-01, 2022-03-01, 2020-03-02;
   SPCX/STX/SHOP/BABA at additional dates) which confirmed the 0-bar
   result was a test-date artifact, not a retention/entitlement limit.
5. Corrected `probe_2_older_period`'s default date to `2024-03-01` (an
   ordinary trading day) and added two new persisted probes,
   `probe_2b_retention_depth` (AAPL at 2023-03-01/2022-03-01/2020-03-02)
   and `probe_3b_other_missing_tickers` (STX/SHOP/BABA at 2023-03-01),
   so the ad-hoc follow-up findings are reproducible from the committed
   script rather than living only in shell history. Re-ran the full
   probe script at ~08:03 UTC → `results/task124_intraday_feasibility/alpaca_feed_probe.json`
   (this is the final, authoritative probe output).
6. Copied both output files (7,320 and 33,703 bytes — well under the
   program's existing evidence-size convention) into
   `docs/research/evidence/task124/`.
7. Wrote `docs/research/TASK124_INTRADAY_DATA_FEASIBILITY.md`
   synthesizing Parts 0/2/3/4/5/6.
8. Verified production/Redis preservation again at close (same result
   as baseline).

## Probe result summary (see `alpaca_feed_probe.json` for full detail)

| probe | classification(s) |
|---|---|
| 1 (AAPL 2025-02-05, sip) | `DATA_PRESENT` |
| 2 (AAPL 2024-03-01, sip+iex) | `DATA_PRESENT` / `DATA_PRESENT` |
| 2b (AAPL 2023-03-01/2022-03-01/2020-03-02, sip) | `DATA_PRESENT` / `DATA_PRESENT` / `DATA_PRESENT` (851 bars on 2020-03-02) |
| 3 (SPCX 2025-06-02, sip+iex) | `DATA_PRESENT` (16 bars only) / `EMPTY_RESPONSE` |
| 3b (STX/SHOP/BABA 2023-03-01, sip) | `DATA_PRESENT` (378/571/819 bars) |
| 4 (JPM daily raw vs. all around 2025-04-04) | `DATA_PRESENT` / `DATA_PRESENT`, confirmed ex-div step in the raw/all ratio |

No `REQUEST_ERROR` (4xx/5xx) occurred on any probe in this task. No
provider restriction blocked resolution; the investigation completed
within the ~90-minute active-work bound (well under it).

## Findings and corrections

- Task 123's Track A/B decisions and product decision are unchanged —
  carried forward verbatim (§0).
- Task 123's own "genuinely causal, executable" wording (already
  partially corrected in `TASK123_TIMING_CORRECTION.md`) is restated
  here as the current, carried-forward description: causally timed,
  reference-fill only, execution quality not established.
- New finding: SIP minute-bar retention extends to at least
  2020-03-02 (>5 years before the current Track B window start of
  2025-01-24) for AAPL — this had never been checked before this task.
- New finding: 2 of the 5 currently "locally uncovered" active tickers
  (SHOP, BABA) have substantial real SIP minute coverage available;
  SPCX's near-absence of bars (16/session) reflects genuine thin
  trading, not an entitlement gap.
- New finding (provenance gap, not previously flagged): the existing
  `task93_alpha_foundation/_canonical_data` manifest does not record
  which Alpaca feed (SIP vs. IEX) was used to build it — any future
  extension must resolve this before appending, per the explicit IEX/
  SIP non-interchangeability warning in the task prompt.
- Self-correction: probe 2's original date choice (2024-01-15, MLK Day)
  produced a misleading `EMPTY_RESPONSE`; corrected in the committed
  script and re-run before being used as evidence.

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`.
