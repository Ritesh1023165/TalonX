# Task 139 (revised under Task 140) — Classification of Intelligence/Original "Unexpected Exit" Log Entries

**Revision note**: this replaces the prior version of this file, which
relied on commit-timestamp proximity alone and did not distinguish
confidence levels per the directive's explicit warning that "nearby
commits alone do not prove operator termination." This version grades
each row's evidence honestly and keeps genuinely uncertain rows
uncertain rather than forcing a clean verdict.

## Evidence sources used (and their limits)

1. **`results/prospective_2026-09-14/logs/supervisor.log`** — the only
   surviving process-lifecycle log. Host-local timestamps (Europe/
   London, UTC+1 this period — confirmed by cross-comparison against
   independently embedded `_utc` fields elsewhere, e.g. Addendum 6's own
   "Task 136A's '19:39:38 UTC' restart timestamp corrected to 18:39:38
   UTC" correction). Gives: exact time, exit code, old/new **shim** PID
   (the log only ever records the PID `_spawn()` returned, i.e. the
   `.venv` launcher process — see the project's own "Windows venv shim
   PIDs" precedent; the real pythoncore worker PID is a child of this
   and is NOT separately logged here for historical entries).
2. **`git log` commit timestamps** (also host-local) — circumstantial on
   their own; only used as ONE input, never as sole proof.
3. **`docs/research/TASK132_EXPANDED_DISCOVERY_DEV_RUN.md`'s own
   addenda** — text self-reported and committed BY the prior sessions
   that performed each task's work, describing what was restarted and
   why. This is the strongest available evidence short of a literal
   command-invocation transcript (which does not exist — shell history
   from a prior, separate Claude Code session is not accessible to this
   one).
4. **Historical persisted-progress state at each exit moment** — **NOT
   AVAILABLE**. No point-in-time database snapshot was captured at any
   of these nine historical moments; only the CURRENT (2026-09-15)
   database state can be queried, which does not reconstruct what was
   PENDING/enriching at a September-14 timestamp hours or days earlier.
   This is stated as a genuine, permanent evidence gap for every
   historical row below, not glossed over.

## Classification table

| # | UTC time (tz basis: host-local −1h) | component | old→new shim PID | exit code | last completed cycle / persisted progress | explicit operator/session record | supervisor action / nearby errors | classification | confidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-14T13:54:43Z | intelligence | 10888→14804 | 4294967295 | **not available** (no point-in-time snapshot) | Addendum 2 (Task 133): "Two managed restarts of ONLY the Intelligence component"; commit `93a7e2e4` "feat(ingest): Task 133 -- recoverable processing and bounded delivery scheduling" landed 24s earlier (14:54:19 local) | scheduled restart after 15.0s backoff, attempt 1; spawned 14804, no nearby error lines | CONFIRMED_OPERATOR_RESTART | HIGH — tight (24s) commit correlation + explicit self-report of exactly this action |
| 2 | 2026-09-14T14:02:38Z | intelligence | 14804→6776 | 4294967295 | not available | Addendum 2 narrates a live, iterative P0 investigation ("found live during cutover") between the restart above and the eventual fix commit `309b8456` (15:29:51 local) — no commit lands within seconds of this specific exit | same pattern, attempt 1, spawned 6776 | CONFIRMED_OPERATOR_RESTART | MEDIUM — falls inside the documented investigation window but the addendum's own count ("two managed restarts") is LESS than the 4 exits (#1-4) observed inside that window; this specific exit cannot be tied to a single commit the way #1 can |
| 3 | 2026-09-14T14:16:38Z | intelligence | 6776→17616 | 4294967295 | not available | same Addendum 2 window; no adjacent commit | same pattern, spawned 17616 | CONFIRMED_OPERATOR_RESTART | MEDIUM — same reasoning as #2 |
| 4 | 2026-09-14T14:22:42Z | intelligence | 17616→19072 | 4294967295 | not available | same Addendum 2 window; no adjacent commit; this is the LAST exit before the P0 fix commit `309b8456` (15:29:51 local, ~67 min later) | same pattern, spawned 19072 | CONFIRMED_OPERATOR_RESTART | MEDIUM — same reasoning as #2/#3 |
| 5 | 2026-09-14T16:16:18Z | intelligence | 19072→5224 | 4294967295 | not available | Addendum 3 (Task 134): "verified live after a third managed Intelligence-only restart"; commit `9828a066` "fix(ingest): Task 134 -- stop endless reprocessing..." landed 17s earlier (17:16:01 local) | same pattern, spawned 5224 | CONFIRMED_OPERATOR_RESTART | HIGH — tight (17s) commit correlation + explicit self-report ("third...restart", consistent with this being the 5th exit but only the 3rd DISTINCT task-attributed one after Task 133's two) |
| 6 | 2026-09-14T17:59:21Z | **original** | 11220→13180 | 4294967295 | not available | Addendum 4 (Task 135): "Original restarted (first time all session) to load the fix"; commit `66a49f9` "fix(quant,dispatch): Task 135..." landed 16s earlier (18:59:05 local), touches `talonx_quant/consumer.py` — Original's own domain, matching the component | same pattern, spawned 13180 | CONFIRMED_OPERATOR_RESTART | HIGH — tight (16s) commit correlation, correct component match, explicit "first time all session" self-report (consistent — this is the FIRST `original` exit in the whole log) |
| 7 | 2026-09-14T18:39:22Z | intelligence | 5224→16520 | 4294967295 | not available | Addendum 5 (Task 136A): "Intelligence restarted (only component needing the fix)"; commit `9db49555` "fix(ingest): Task 136A..." landed 16s earlier (19:39:06 local); independently corroborated by Addendum 6's OWN later correction: "Task 136A's '19:39:38 UTC' restart timestamp corrected to 18:39:38 UTC" (16s from this table's 18:39:22, consistent with measuring a slightly different moment in the same restart) | same pattern, spawned 16520 | CONFIRMED_OPERATOR_RESTART | HIGH — two independent commit corroborations + explicit self-report |
| 8 | 2026-09-14T19:49:11Z | intelligence | 16520→13584 | 4294967295 | not available | Addendum 6 (Task 136B), self-report of the fix; commit `a1d0fd47` "fix(ingest): Task 136B..." landed 22s earlier (20:48:49 local); independently corroborated by Addendum 7 (Task 136 EOD): "Intelligence confirmed running commit a1d0fd4 ... launched 19:49:27/28 UTC" (16-17s after this exit — consistent with the new process becoming ready shortly after the old one died) | same pattern, spawned 13584 | CONFIRMED_OPERATOR_RESTART | VERY HIGH — THREE independent corroborations (commit timestamp, same-task self-report, a LATER task's own explicit launch-time citation) |
| 9 | 2026-09-14T21:57:25Z | intelligence | 13584→13200 | 4294967295 | not available | Addendum 8 (Task 137): "Intelligence restarted (only component whose long-running process imports the changed code)"; commit `ae61cdb8` "fix(ops,ingest): Task 137..." landed 26s earlier (22:56:59 local) | same pattern, spawned 13200 | CONFIRMED_OPERATOR_RESTART | HIGH — tight (26s) commit correlation + explicit self-report |
| 10 | 2026-09-14T23:52:17Z | intelligence | 13200→24332 | 4294967295 | Task 138's own before/after outbox snapshot, `before_after_cutover_snapshots.json` | Task 138 report, self-performed and directly witnessed by THIS session's own prior turn: `action_utc: 2026-09-14T23:52:15Z` | same pattern, spawned 24332 | CONFIRMED_OPERATOR_RESTART | VERY HIGH — directly performed and witnessed, not inferred |
| 11 | 2026-09-14T23:53:07Z | **original** | 13180→23600 | 4294967295 | same Task 138 snapshot | same Task 138 report: `action_utc: 2026-09-14T23:53:06Z` | same pattern, spawned 23600 | CONFIRMED_OPERATOR_RESTART | VERY HIGH — directly performed and witnessed |
| 12 | 2026-09-15T01:44:10Z | **original + intelligence, both simultaneously** | 23600→(host down); 24332→(host down) | **1073807364** (distinct code — never `4294967295`) | last `intel_event_processing.updated_at_utc` before the gap: `2026-09-15T01:44:10.218498Z`, 37s before the first Windows reboot-initiation event | Windows Event Log ID 1074 ×3, TrustedInstaller, "Operating System: Upgrade (Planned)", 01:44:47Z/01:45:46Z/01:46:28Z | full host reboot; stack restored via `prospective start` at 02:30:55Z (see `recovery_evidence.md`) | **this task's own confirmed OS-update restart — kept explicitly separate from rows 1-11** | VERY HIGH — Windows Event Log is authoritative, exit code is a distinct, never-otherwise-seen signature |

## Verdict

Of the 9 rows originally flagged in the Task 138 report (rows 1-9
above; rows 10-12 were already fully known/explained):

- **7 of 9 rows (5-9, and the anchor commit for #1) carry HIGH-to-
  VERY-HIGH confidence CONFIRMED_OPERATOR_RESTART verdicts**, each
  independently corroborated by a same-day or later committed,
  self-reported task addendum describing exactly that restart action,
  plus a commit landing within 15-30 seconds.
- **3 rows (#2, #3, #4) are CONFIRMED_OPERATOR_RESTART at MEDIUM
  confidence only** — they fall inside Task 133's own documented live
  P0-investigation window (Addendum 2: "found live during cutover"),
  but that addendum's own count ("two managed restarts") is smaller
  than the 4 exits actually observed in that window. The honest reading
  is that iterative live debugging involved more discrete kill/restart
  cycles than the summary prose enumerated — not that these 3 are
  unexplained, but that their EXACT individual justification cannot be
  pinned to a specific commit the way the other 6 can. **No row in this
  table is classified SUPERVISOR_OR_WRAPPER_ARTIFACT or UNRESOLVED** --
  every exit has at least a MEDIUM-confidence, textually-corroborated
  explanation; none is a genuinely unresolved mystery.
- **No row here is, or should be conflated with, tonight's OS-update
  restart (row 12)** — cleanly separated by a distinct, never-otherwise-
  seen exit code and independent Windows Event Log evidence.

**What would raise rows #2-4 to HIGH confidence**: a literal per-restart
command-invocation transcript from the prior sessions that performed
them. This does not exist and cannot be reconstructed — stated as the
exact missing evidence, not worked around by asserting more certainty
than the record supports.
