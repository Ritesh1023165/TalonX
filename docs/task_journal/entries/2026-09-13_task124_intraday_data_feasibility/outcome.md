1. **Data verdict**: **`DATA_EXTENSION_FEASIBLE`** — existing free
   Alpaca SIP access (already credentialed and used in this research
   program) can provide a materially longer and/or broader intraday
   dataset compatible with Task 123 Track B's frozen contract,
   unchanged. This does not authorize running the acquisition, a new
   backtest, or any production change.

2. **SHAs**: release verified `f28986999eec5e313cfc89db24e4dbacfb378891`
   unchanged (research-only task). Research `eee821f` (confirmed exact:
   `eee821f78341fc05c75e951fdbaf900a8999ffb4`) → **`<this commit>`**,
   pushed to `research/talonx-profitability-2026-09` only.

3. **Coverage — existing vs. newly verified**: existing local coverage
   unchanged from Task 123 (43 active/5 paused of 48; 38 active with
   daily coverage, 12 with minute coverage; 5 active names — BABA, BLSH,
   SHOP, SKHY, SPCX — with no local daily OR minute file at all). Newly
   verified THIS task, via live probes (not merely re-read from
   documentation): SIP minute retention to at least 2020-03-02; 2 of
   the 5 "locally uncovered" names (SHOP, BABA) have substantial real
   SIP coverage available but never downloaded; SPCX's absence reflects
   genuine thin trading (16 bars/session), not an entitlement block.

4. **Provider/feed/adjustment findings**: all probes used the existing
   `data.alpaca.markets/v2/stocks/{symbol}/bars` endpoint (no new
   provider integration). SIP consistently returns far more bars than
   IEX for the same symbol/date (AAPL 2024-03-01: SIP present, IEX
   present but comparatively less complete; SPCX: SIP present/thin, IEX
   empty) — **IEX and SIP are confirmed NOT interchangeable**, exactly
   as the task warned; no feed was silently concatenated. `adjustment=all`
   was directly confirmed (not merely documented) to perform real
   dividend back-adjustment via a clean price-ratio step at JPM's
   2025-04-04 ex-dividend date. A genuine provenance gap was found: the
   existing `task93_canonical_v1` minute dataset's manifest does not
   record which feed (SIP/IEX) built it — flagged as a precondition for
   any extension, not resolved in this task.

5. **Causal-timing compatibility**: Track B's decision rule (fixed
   pre-close cutoff, same-time-of-day cumulative volume, 2-minute
   delay, next-session-open exit) is unaffected by a data extension —
   it is adapter logic, already implemented and unchanged. The newly
   available longer/broader SIP history uses the same bar-timestamp
   semantics already verified in Task 123 (probe 1 matched the
   already-downloaded data's own convention). Early-close handling was
   NOT separately re-verified this task (bounded scope) and must be
   checked explicitly in any acquisition task, not assumed uniform.

6. **Unexamined-data availability and limitations**: every calendar
   date before 2025-01-24 for the 12 already-covered symbols, and every
   date for the 5 currently-uncovered active symbols, is genuinely
   unexamined for this hypothesis. Limitation: more observations from a
   longer window do not automatically mean more independent evidence —
   Task 123's own date-block bootstrap (resampling distinct trading
   dates, not raw row count) remains the correct approach; no future
   result should be called "properly powered" from trade count alone.
   SPCX's extreme thinness limits how much any extension can help that
   one name specifically.

7. **Acquisition estimate**: no exact blocker was hit. Estimated
   effort is SMALL-to-MEDIUM: reuses `task107a_prices.py`'s existing
   rate-limited pagination/backoff pattern; ~17 symbols × ~2 years of
   1-minute bars is within this account's already-demonstrated access,
   not a new-infrastructure undertaking. Investigation completed well
   within the ~90-minute active-work bound; no provider restriction
   required retrying.

8. **ONE next action**: run the concrete acquisition-and-validation
   task specified in `docs/research/TASK124_INTRADAY_DATA_FEASIBILITY.md`
   Part 6 — extend the 12 Track-B symbols back to 2023-01-01 and add
   the 5 currently-uncovered active symbols, via `feed=sip`, contingent
   on first confirming `task93_canonical_v1`'s original feed identity
   (or storing the extension as a clearly separate, distinctly-labelled
   series if that cannot be confirmed) — not executed in this task.

9. **Production preservation**: no release-branch change; no
   application process started; Redis `talonx:*` key count 0 both
   before and after; release worktree unchanged and clean.

10. **Journal/reports**: `entries/2026-09-13_task124_intraday_data_feasibility/`
    + `docs/research/TASK124_INTRADAY_DATA_FEASIBILITY.md` +
    `docs/research/evidence/task124/{coverage_manifest.json,alpaca_feed_probe.json}`
    + `research/scripts/task124_{data_manifest,alpaca_feed_probe}.py` —
    all at this commit, pushed.

Priority followed as instructed: causal contract → bounded computation
→ economic decision. The deliverable here is the decision about
whether the missing evidence is obtainable, not another strategy
result — that verdict is `DATA_EXTENSION_FEASIBLE`, with one concrete,
bounded next task specified and nothing executed beyond this
investigation.
