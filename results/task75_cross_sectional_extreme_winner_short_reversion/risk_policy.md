# Task75A Part 5 -- Risk Policy

**Decision: Option B -- one structurally justified catastrophic stop.**

A SHORT position with theoretically unbounded upside loss, held 3
trading days with no monitoring in between under a no-stop policy,
carries an unacceptable single-name short-squeeze tail risk. Task74B's
own already-computed `risk_diagnostics.csv` for the anchor cell shows a
wide adverse-excursion tail: median MAE 2.35 (in units of 1% of entry
price), 90th pct 7.88, 95th pct 10.07, 99th pct 16.28, max 26.34.

**Frozen stop: 15% above entry (SHORT).** A conservative round buffer
between the 95th (10.07) and 99th (16.28) percentiles -- NOT selected by
grid-searching stop distances against P&L; no such grid was ever run.

**Fill semantics:** checked on each subsequent regular-session bar's
HIGH starting from the bar strictly after entry; a gap-through fills at
that bar's OPEN (never a better fill than the bar permits) -- same
conservative convention as the frozen Task72 stop. A stop trigger
replaces the scheduled fixed-horizon exit, whichever occurs first.

No take-profit, no trailing stop. Overnight gaps are treated
pessimistically (worse-than-stop fills), never optimistically.
