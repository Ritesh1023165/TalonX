# Task 140 — Dashboard Refresh No Longer Interrupts Reading

**User-reported defect**: the `:8787` cockpit dashboard automatically
refreshes every 6 seconds while the operator is reading lower content,
and returns them to the top of the page. Confirmed real, concretely
reproduced and fixed — see the reproduction below.

## 1. Root cause (reproduced before editing)

`dashboard_web_static/index.html`'s `loadSection(name)`/`loadLegacy(view)`
were the SAME function used for both the initial tab load AND every
periodic auto-refresh (`setInterval(..., 6000)`). On every call, BEFORE
even issuing the fetch, the section container's entire `innerHTML` was
replaced with a one-line `"loading…"` placeholder — collapsing total
document height far below wherever the reader had scrolled, so the
browser clamped `window.scrollY` down to the new, much shorter max
scroll. Then, on response, `innerHTML` was replaced again wholesale,
destroying every existing DOM node (any user-expanded `<details>` went
with it) and rebuilding from scratch. **No explicit `scrollTo`/`focus`
call existed anywhere in the file** — the jump was a pure side effect of
full-replace-driven document-height collapse-then-regrow, exactly
matching the candidate cause list's "loading states that collapse the
content."

### Concrete reproduction (real browser, real pre-fix code, isolated fixtures)

The REAL pre-fix `dashboard_web_static/index.html` (git commit `4f0af50`,
the last commit that touched this file before this correction — the real
repository file was never reverted or touched to produce this, only a
scratch copy served via a monkeypatched `STATIC_DIR`) was driven in a
real headless Chrome against synthetic, isolated fixture data (never live
production data):

```
PRE-FIX CODE -- scrollY before 3 auto-refresh cycles: 900
PRE-FIX CODE -- scrollY after 3 auto-refresh cycles: 0
PRE-FIX CODE -- jump distance: 900 px
```

See `repro_prefix_bug_output.txt` and `screenshots/prefix_after_jump.png`
(the reader is shown back at the very top of the Intelligence tab after
three refresh cycles that started at `scrollY=900`).

**The real scroll container is the document/window itself** — no nested
scrollable panel exists (`.card`/`.tblwrap` only ever get horizontal
`overflow-x:auto` for wide tables); `window.scrollY` is the correct and
only thing to preserve.

## 2. Fix — files changed, behaviour corrected

**Only `dashboard_web_static/index.html` was modified.** No Python file,
no backend route, no strategy/ingestion/execution/accounting code was
touched (confirmed — see §6).

- **A hand-written, dependency-free keyed DOM morph** (`morphNode`/
  `morphChildren`, ~60 lines) replaces full `innerHTML` replacement for
  every REFRESH of an already-displayed tab. Unchanged DOM nodes are
  never removed/recreated, so their scroll position, focus, and
  `<details>` open/closed state survive automatically — the same
  technique morphdom/idiomorph use, hand-rolled here specifically because
  the task requires reusing the existing vanilla-JS architecture rather
  than adding a new frontend framework. Table rows use `data-key`
  (stamped by `boundedTable`'s new optional `keyFn` argument, wired to a
  natural unique field — `event_id`, `symbol`+`entry_session`, etc. — at
  each of its 19 call sites) for keyed reconciliation, so a row survives
  identity-correctly even when OTHER rows above/below it are
  added/removed/reordered; non-list structural content (cards, kv rows)
  uses safe positional matching (their order is fixed by the same code
  path every render).
- **Only the FIRST load of a newly-selected tab does a full replace**
  (`loadSection`/`loadLegacy`'s own entry points) — that is genuine
  intentional navigation with nothing yet to preserve, exactly like
  following a link; the loading skeleton is legitimate there and only
  there.
- **Scroll-anchor correction** (`applyRefresh`/`findAnchor`): finds the
  topmost `[data-key]` element still visible, and after the morph,
  corrects `window.scrollBy` for whatever shifted above it. If the exact
  anchored element didn't survive (its row genuinely left), it walks
  outward through where it used to sit to the nearest still-connected
  element as a "sensible nearby fallback" — never leaving the correction
  fully unapplied.
- **"New items above" indicator, never an auto-jump**: `maybeShowNewItemsPill`
  shows a small, sticky, dismissible pill ("New updates above — click to
  view") only when the section's own topmost item changed identity while
  the reader has scrolled down — click scrolls up; nothing ever
  auto-scrolls the reader anywhere.
- **One genuinely conditional card** (`renderV2Discovery`'s "Unresolved
  CIK sample") was changed to always render its wrapper (content inside
  toggles instead) — this removes the one case where a whole sibling
  card could be added/removed between refreshes, which would otherwise
  misalign purely-positional card matching in its `.grid`.
- **A real, second layout bug found and fixed by this same work**: the
  new refresh-status text, if allowed to vary in width/wrap based on
  message length, could itself grow the page **header's** height (the
  header uses `flex-wrap`), shifting the whole page and reintroducing a
  small scroll jump on exactly the kind of message this fix adds (a
  failed-request error). Fixed with a fixed-width, `white-space:nowrap`,
  ellipsis-truncated status element — confirmed via direct
  before/after header-height + `scrollY` measurement (see
  `browser_test_run_output.txt`,
  `test_failed_request_keeps_content_and_recovers_without_losing_position`).

## 3. Refresh controls (reused existing header styling)

Added to the existing `<header>` (`#refresh-controls`): **Pause/Resume**,
**Refresh** (manual), and a status line (`updated Ns ago` / `paused` /
`updating…` / an honest error message — never a bare changing clock
presented as proof of new data).

- **Pause** clears the single `setInterval` handle (`disarmRefreshTimer`)
  — no automatic refresh is even scheduled while paused, not merely
  ignored on arrival.
- **An in-flight auto request cannot silently apply after pause**:
  `fetchAndApplySection`/`fetchAndApplyLegacy` re-check `paused` a SECOND
  time right before applying the response, discarding it if pause was
  engaged while the request was in flight.
- **Manual refresh works while paused and leaves it paused** — it never
  touches `paused`/the timer, and goes through the exact same morph/
  scroll-preserving apply path as an automatic refresh.
- **Resume re-arms exactly one timer** (`armRefreshTimer` is idempotent —
  guards on an existing handle) and does not fire a burst of catch-up
  refreshes for time missed while paused.
- **`lastSuccessAt` only advances on a real, applied success** — a failed
  request's `catch`/`!resp.ok` branch never touches it; the displayed
  "Ns ago" is a live 1-second ticker over that one honestly-gated
  timestamp, not a bare wall clock presented as freshness proof.

## 4. Requests/errors handled safely

- **No overlapping requests for the same target**: a per-target
  generation counter + `AbortController` — a manual refresh aborts any
  in-flight request for the same section/view and supersedes its
  generation; an auto tick is skipped outright (not queued) if one is
  already in flight for that target.
- **Older responses cannot overwrite newer state**: every apply path
  re-checks `myGen === state.generation` (and that the operator hasn't
  switched away from that section/tab) before touching the DOM — proven
  with a real, controlled delayed-vs-fast response race
  (`test_delayed_response_cannot_overwrite_newer_state`).
- **A stale response for an old tab/filter cannot replace the current
  view**: the same generation + `activeSection`/`activeLegacy` identity
  check also guards a genuine tab switch mid-flight
  (`test_tab_switch_during_in_flight_refresh_shows_the_new_tab`).
- **No duplicated listeners/timers**: nav-button click listeners are
  attached once at module load (unchanged from before); the refresh
  timer is a single guarded handle, never re-created by resume.
- **A temporary error keeps the last usable content, with an honest
  status, and never resets scroll or selections** — proven directly
  (`test_failed_request_keeps_content_and_recovers_without_losing_position`).
- No additional backend polling load: the refresh cadence itself is
  unchanged (still one poll per active tab every 6s); the only new
  client-side behaviour is aborting a superseded in-flight request, never
  adding requests.

## 5. Rendered verification

Real (non-headless-only-claimed) behavioural proof: `tests/
test_task140_dashboard_refresh.py`, 10 tests, all passing, driving the
ACTUAL shipped JS in a real headless Chrome via Chrome's own DevTools
Protocol (`tests/_dashboard_browser.py` — no Playwright/Selenium/Node
installed in this environment; Chrome itself already is, so this uses it
directly rather than adding a new frontend/test framework, per this
task's own instruction). See `browser_test_run_output.txt` for the full
run (10/10 pass) and the file's own docstring/test names for exactly
which of the task's 10 required scenarios each one proves.

Visual, desktop + narrow-screen (390×844, an iPhone-class viewport),
against the REAL LIVE `:8787` dashboard's real data — Overview (shows
the new Pause/Refresh controls), Active V2, and Broad Discovery, per the
task's explicit tab list: `screenshots/desktop_*.png`,
`screenshots/narrow_*.png`.

**Limitation honestly disclosed**: no screen recording (video) tool is
available in this environment; the evidence is real DOM/scroll-position
measurements taken programmatically before/after each refresh cycle
(not merely static screenshots — see the task's own caution that
screenshots alone don't prove a scroll jump is fixed) plus static
before/after screenshots for visual/layout confirmation. The
pre-fix-vs-post-fix scroll-position numbers (900→0 vs 900→900±drift) are
the load-bearing proof, not the screenshots alone.

## 6. Preserving the running application

- **No file other than `dashboard_web_static/index.html` was modified.**
  Confirmed by `git status`/`git diff --stat` at commit time (see the
  commit this document accompanies). No `dashboard_web.py` change, no
  `talonx_v2`/strategy/ingestion/execution/Telegram/accounting file
  touched.
- **No backend restart of any kind was performed or is required.**
  `dashboard_web.py::index_handler` serves this file via
  `web.FileResponse(STATIC_DIR / "index.html")` — read fresh from disk on
  every request, no in-process caching. Confirmed live: the ALREADY-
  RUNNING `:8787` process (pid unchanged throughout this work) was
  curled directly and found to already be serving the new markers
  (`morphChildren`, `refresh-pause-btn`, `new-items-pill`) with zero
  restart action taken.
- **Operator action required**: a browser tab that already had the
  dashboard open before this fix is running the OLD JavaScript in memory
  and needs a normal page reload (F5 / Ctrl+R) once to pick up the fix.
  Any new page load already gets it automatically. No other action is
  needed.

## 7. Regression

Focused suite (existing dashboard tests + the new Task 140 real-browser
suite): `focused_regression_output.txt` — **93 passed, 1 failed**. The
one failure, `tests/test_task104_p2_cleanup.py::
test_32_33_original_strategy_and_thresholds_unchanged`, is the SAME
pre-existing/environmental failure already individually verified against
the pre-Task-138 baseline commit (`13c9902`) via a temporary git
worktree earlier in this session's own evidence
(`docs/research/evidence/task138/full_suite_run_output.txt`) and
reconfirmed name-for-name identical in the reply-details correction's
own full-suite run (`../full_suite_run_output_task140_v2.txt`) — not
attributable to this change, which touches no Python file that failure's
root cause could depend on. A full ~80-minute, 4800+-test whole-repository
run was not repeated for this frontend-only, single-file HTML/CSS/JS
change; the focused run above directly covers every test that imports or
exercises `dashboard_web.py`/`dashboard_web_static/`.

## Limitations

- The scroll-anchor correction is a best-effort heuristic when the
  anchored row itself is evicted by a bounded-table row cap (many rows
  changing identity simultaneously) — proven to keep the reader within a
  small, non-disorienting distance of their original position (never
  back near the top), not always pixel-perfect. See
  `test_new_rows_above_do_not_auto_jump_and_show_an_indicator`'s own
  comment for the measured bound.
- No text input/filter/sort control exists anywhere in this dashboard
  today, so "preserve filters/sort/in-progress input" has nothing to
  preserve currently — the morph-based architecture preserves any such
  control generically (by never destroying its DOM node on refresh)
  the moment one is added, without further change.
