# Task75A Part 6 -- Execution Cost Contract

**Primary all-in validation hurdle: 25 bps** (10bps baseline + 15bps
short-specific add-on for wider open-side spread/slippage and a borrow-
fee-and-friction buffer). Diagnostic levels (0/5/10/15/20 bps) are
retained for comparability but are NOT the primary pass/fail bar for
this short-only candidate -- per this task's own instruction not to
assume 10bps covers every short-specific cost.

**Open-fill semantics:** first regular-session 1-minute bar's OPEN
(this dataset cannot resolve true opening-auction prints).

**Borrow availability:** no historical borrow-rate/HTB data source
exists in this repo. V1 ASSUMES every frozen-universe mega-cap symbol is
easily borrowable (a standard, but UNVERIFIED, assumption for large
liquid names) -- disclosed as an open limitation, not proven. A future
real-capital integration must independently verify borrow availability
before any live short.

**Dividend liability:** UNMODELED (no ex-date data source exists). This
is a downside-only omission -- it would make real short economics worse,
not better, than validation will show.

**Gap-through risk:** governed by `risk_policy.json`'s stop semantics
(pessimistic fills only).

**Rejected/unfillable trades:** any row failing a data/session check is
excluded and labeled with a rejection reason -- never assumed filled.
