# Record

## Baseline verification (start of task)

- Research branch `research/talonx-profitability-2026-09` HEAD:
  `e0d26bde41d6691bee30c73576b999c3aa9b4713` (matches expected exactly).
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), `git status --short` clean, both
  worktrees.

## Actions taken, in order (all times UTC, 2026-09-13)

1. Read `docs/research/TASK129_RESEARCH_PROGRAM_DECISION.md` and
   `docs/research/NEXT_SESSION_HANDOFF.md` (the existing handoff,
   located at this path — last substantively updated 2026-09-12 for
   Task 119A/120, predating this entire Task 121–129 research arc).
2. **09:40:01Z** — bounded, read-only stopped-state check:
   - `netstat`: 0 listening connections on 8787/8770/8760/8501.
   - `tasklist`: 0 Python processes of any kind.
   - `.run/task99c_*.pid` (4 files, from an unrelated, much earlier
     task): each PID individually checked via `tasklist /FI "PID eq
     ..."` — all 4 confirmed NOT running. Reported as found-but-stale,
     not silently ignored, per the instruction to report ownership/
     status of anything found.
   - Redis: `PING` → True, `scan_iter('talonx:*')` → 0 keys. Read-only;
     no `FLUSHDB`/`EXPIRE`/write of any kind issued.
3. Located the authoritative Experimental ledger
   (`~/.talonx/experimental/experimental_paper.db`, resolved from
   `talonx_signals/config.py`'s own `state_dir`/`paper_db_path`
   properties — not assumed) and read it read-only
   (`sqlite3.connect('file:...?mode=ro', uri=True)`):
   - `positions` table: 1 row — SPCX, 16.865960067130683 shares, entry
     $148.22755360794068, entry timestamp
     2026-09-10T19:29:45.777729+00:00, cost basis $2,500.00, stop
     $144.6133321126302, target $152.06332906087238.
   - `latest_prices` table: **0 rows** (empty for every ticker) — no
     mark-to-market update was ever persisted after entry. This
     directly contradicts the existing handoff's carried-forward claim
     of a "$151.2100 @ 2026-09-11T20:09:20Z" mark — that figure is not
     present in the authoritative ledger and is withdrawn as a current
     value in the updated handoff.
   - `trade_history`: 9 rows total; most recent is a
     2026-09-11T08:59:27-04:00 SELL (BLSH, `confirmed_bearish`) — the
     SPCX BUY (row 5) is the only entry with no matching exit.
   - File mtimes: `experimental_paper.db` last written 2026-09-10
     23:23 local; `exp_quant.db`/`forward_outcomes.db` last written
     2026-09-11 21:07–21:09 local — no ledger file written since,
     consistent with no process having run since then.
4. Located and read the authoritative V2 ledger (`v2_lane.db`, repo
   root of the release worktree — resolved from prior-session memory,
   confirmed present) read-only: `positions` table 0 rows, `portfolio`
   table cash $300,000.00 flat — confirms the existing handoff's "0
   open positions" claim for V2 was already accurate; no correction
   needed there.
5. Updated `docs/research/NEXT_SESSION_HANDOFF.md` **in place** (no
   new document created): added a top-of-file pause banner; rewrote
   the "Open-position and pending-notification obligations" section
   with the freshly-verified SPCX/V2 state (explicitly withdrawing the
   stale mark, stating the exit-evaluation gap and the no-fabrication/
   no-flatten/no-uninterrupted-monitoring constraints); replaced the
   "Next market session" launch framing with a not-scheduled statement;
   added an "Application state as of this closure task" section with
   the exact verification timestamp; added a "Programme decision and
   resumption conditions (Task 129)" section with the exact named
   conditions and future-proposal requirements; replaced "One next
   research/product action" with an explicit none-scheduled statement.
   The prior "Candidate release"/"Startup procedure"/"Canonical EOD
   procedure" sections were left as reference material (still
   factually accurate for a future restart) but are now clearly framed
   by the top banner as not a scheduled or implied next action.
6. Added one minimal row to `docs/task_journal/TASK_INDEX.md` for
   discoverability, consistent with this journal's standing convention
   — no other index/ledger/PRODUCT_STATUS.md rewrite performed, per
   the instruction to make only the minimum necessary research-document
   changes.
7. No code was changed, no backtest was run, no download occurred, no
   external message was sent, and no production process was started,
   stopped, or modified at any point in this task.

## Production preservation (end of task)

Unchanged from the start-of-task snapshot — no process started, no
port opened, Redis `talonx:*` key count still 0 (unread/unwritten
beyond the read-only scan), both ledgers (`experimental_paper.db`,
`v2_lane.db`) opened strictly read-only and unmodified, release
worktree still clean at `f28986999eec5e313cfc89db24e4dbacfb378891`.
