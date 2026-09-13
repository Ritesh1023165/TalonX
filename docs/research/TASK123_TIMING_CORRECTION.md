# Task 123 Part 1 — correcting Task 122's causal-timing assumption

## The defect

Task 122's feasibility check computed a trigger from session S's **final**
daily volume (`volume[S] >= 2x trailing-20-session average`), then its
proposed evaluation protocol implicitly assumed this trigger could be
acted on **at S's own closing price**. This is not causally valid: a
session's final daily volume figure includes trading activity through
the close itself — it is only fully known once the session is
essentially over, at the same moment (or after) the closing price is
set. `shift(1)` on the trailing-average BASELINE correctly prevented
session S's own volume from contaminating its own 20-session reference
average, but that guard does nothing to make the trigger **observable
in time to act on S's own close** — a materially different problem.
Task 122's claim implicitly required knowing, before or at the close,
information that is only available at or after the close. That causal-
execution claim is **withdrawn**.

Also withdrawn: any implicit suggestion that the fix is to substitute
yesterday's volume as the trigger, or to enter after the close using a
post-close price. Both would be **different hypotheses** — a lagged-
volume trigger tests a different (weaker, one-day-stale) signal, and a
post-close entry changes the holding period and forfeits the mechanism
(retail attention concentrated AT the close/open transition) the source
literature actually describes. Neither substitution is made here.

## The correction: two explicitly separate tracks

**Track A — DAILY-DATA ASSOCIATION DIAGNOSTIC (non-actionable).**
Session S's own final volume selects observations whose REFERENCE
return is `S.close → next_XNYS_session.open`. This is a **conditional
historical-return study** — it measures whether sessions that (in
hindsight) had abnormal volume show a different overnight return than
the unconditional population. It is explicitly **not** an executable
alert strategy and **not** an achievable paper fill, because the
selection criterion (S's final volume) is not known in time to act on
S's own close.

**Track B — ACTIONABLE PRE-CLOSE CANDIDATE.** A genuinely executable
version must use only information available at a **fixed pre-close
cutoff** (e.g., volume accumulated from the session's open through a
time strictly before the close), enter after a stated decision/delivery
delay at a **subsequent observed price**, and exit at the next session's
observed open. This requires intraday (sub-daily) data to construct
the pre-close cumulative-volume measure and the post-decision entry
price — daily bars alone cannot support it. Frozen separately in
`docs/research/TASK123_FROZEN_PROTOCOL.md` §B and evaluated in
`docs/research/TASK123_OVERNIGHT_ATTENTION_RESULTS.md`.

## Correction applied to Task 122

`docs/research/TASK122_CANDIDATE_DECISION.md`'s Part 4/5 feasibility
check and fixed-evaluation-protocol sections implicitly assumed a
same-close entry was achievable from the daily-only trigger. That
assumption is corrected here, not in the original document (which
remains as written, per this session's established convention of
appending corrections rather than rewriting history) — see the
blockquote added to that document's own text, and to this task's
journal entry, both dated 2026-09-13.

The trigger-FREQUENCY facts Task 122 reported (2,447 events / 86
months / 0 data-quality issues, on the full 35-name daily panel) are
**not** invalidated by this correction — they remain accurate counts of
how often the trigger condition fires. What was wrong was the implicit
claim that firing could be ACTED ON at the same session's close.
