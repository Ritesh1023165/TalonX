"""Task 71S -- symbol-level data freshness and provider-health state machine.

Evidence basis (see results/task71s_data_freshness_stabilization/): every
one of the 2026-08-26 session's 72 STALE_DATA events, and all 121
missing-opening-minute observations across its 15 DATA_NOT_READY symbols,
were independently confirmed -- via a read-only comparison against Alpaca's
own historical IEX 1-minute archive (talonx_piv/gap_forensics.py) -- to be
NO_IEX_BAR_OBSERVED: a genuine, per-symbol, per-minute absence of any
IEX-reported trade, not a live-ingestion defect. Missing minutes were
frequently shared across many DIFFERENT symbols in the exact same clock
minute purely by coincidence of independent thin printing (up to 8 of the
15 DATA_NOT_READY symbols missing the identical minute, on an otherwise
healthy day) -- so a "many symbols stale at once => the provider must be
down" heuristic would have raised FALSE provider-unavailable alarms on a
perfectly healthy feed. For that reason, provider-level health here is
driven ONLY by a directly-observed fetch failure (the underlying HTTP call
itself raising or returning non-200), never inferred from a majority-stale
symbol count -- see SessionRunner.fetch_bars_latest's own use of
record_provider_fetch_result.

This module holds no reference to any talonx_quant object and performs no
network I/O itself -- pure wall-clock/event-driven state bookkeeping,
callable from talonx_piv/session_runner.py without touching
talonx_quant/{strategy,indicators,consumer,config}.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# --- Per-symbol freshness states ---
FRESH = "FRESH"
STALE = "STALE"
RECOVERED = "RECOVERED"  # transient: returned only on the exact recovery tick, then settles to FRESH
DATA_GAP = "DATA_GAP"  # a STALE episode still unresolved at end-of-session
UNKNOWN = "UNKNOWN"  # no bar observed yet for this symbol this session

# Task 71S-R1: a per-TICK classification (never stored as the symbol's
# ongoing state) for "the provider poll succeeded and this symbol simply
# had no new bar this cycle, while still within the stale threshold" --
# the single most common, entirely ordinary condition on this feed (see
# results/task71s_r1_live_iex_semantics/iex_coverage_by_symbol.csv: most
# of the universe has well under 100% regular-session minute coverage on
# an ordinary day). This is deliberately NEVER an emitted event -- only a
# rolling counter (see observe_quiet_tick) -- so that ordinary sparsity
# never produces a notification, let alone a storm of them.
NO_NEW_IEX_BAR = "NO_NEW_IEX_BAR"

# --- Provider-level health states (independent dimension -- see module docstring) ---
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"

# How many CONSECUTIVE fetch failures before DEGRADED escalates to
# PROVIDER_UNAVAILABLE -- one isolated transient failure (already survived
# by session_runner's own per-tick try/except) is DEGRADED, not yet
# PROVIDER_UNAVAILABLE; two or more in a row is a genuine, evidenced
# connectivity problem worth a stronger classification.
_CONSECUTIVE_FAILURES_FOR_UNAVAILABLE = 2


@dataclass
class FreshnessTracker:
    """Session/date-scoped. Deliberately gap-driven, not timestamp-owning:
    the caller (SessionRunner, which already tracks `_last_seen_wall` as
    its single source of truth) tells this tracker WHETHER a bar was fresh
    or stale THIS tick -- this class only classifies the resulting state
    transition and counts consecutive provider failures. No timestamp
    bookkeeping is duplicated here, so there is no risk of this tracker's
    view of "when was the last bar" ever drifting from SessionRunner's own."""

    _state: dict[str, str] = field(default_factory=dict, init=False)
    _session: date | None = field(default=None, init=False)
    _provider_state: str = field(default=HEALTHY, init=False)
    _consecutive_provider_failures: int = field(default=0, init=False)
    # Task 71S-R1: rolling, in-memory, THIS-SESSION-ONLY coverage counters --
    # computed purely from what the live poll itself observes over time (no
    # historical network call), so "live suitability" can be reported without
    # ever guessing at a hard pass/fail threshold (see
    # results/task71s_r1_live_iex_semantics/threshold reasoning: no such
    # threshold is invented here -- these are exposed as metrics only).
    _fresh_bar_count: dict[str, int] = field(default_factory=dict, init=False)
    _quiet_tick_count: dict[str, int] = field(default_factory=dict, init=False)
    _stale_episode_count: dict[str, int] = field(default_factory=dict, init=False)

    def reset_for_session(self, session: date) -> bool:
        """Exact session/date scoping (no state persists across an ET
        trading-date boundary): a new session always starts every symbol
        at UNKNOWN and the provider at HEALTHY, never carrying over a
        prior date's STALE/DATA_GAP/PROVIDER_UNAVAILABLE state (or a prior
        date's rolling coverage counters). Returns True iff this call
        actually performed a reset (idempotent no-op otherwise, matching
        SessionRunner's own `self._session != session` convention)."""
        if self._session == session:
            return False
        self._session = session
        self._state = {}
        self._provider_state = HEALTHY
        self._consecutive_provider_failures = 0
        self._fresh_bar_count = {}
        self._quiet_tick_count = {}
        self._stale_episode_count = {}
        return True

    def state_of(self, symbol: str) -> str:
        return self._state.get(symbol.upper(), UNKNOWN)

    @property
    def provider_state(self) -> str:
        return self._provider_state

    def observe_fresh(self, symbol: str) -> tuple[str, bool]:
        """Call exactly when a genuinely NEW bar (later timestamp than any
        previously seen) has been recorded for `symbol` this tick. Returns
        (state_for_this_tick, recovered) -- recovered=True exactly once,
        on the STALE/DATA_GAP -> fresh transition (the DATA_RECOVERED
        event trigger). The stored state settles to FRESH immediately
        (RECOVERED is a one-tick pulse, never a lingering stored state)."""
        symbol = symbol.upper()
        previous = self._state.get(symbol, UNKNOWN)
        recovered = previous in (STALE, DATA_GAP)
        self._state[symbol] = FRESH
        self._fresh_bar_count[symbol] = self._fresh_bar_count.get(symbol, 0) + 1
        return (RECOVERED if recovered else FRESH), recovered

    def observe_quiet_tick(self, symbol: str) -> str:
        """Call when the poll succeeded but `symbol` had no NEW bar this
        tick, and the gap is still within the stale threshold -- an
        entirely ordinary condition on this feed (see module docstring),
        never itself an event. Only increments the rolling coverage
        counter; never changes the symbol's stored FRESH/STALE/etc state."""
        symbol = symbol.upper()
        self._quiet_tick_count[symbol] = self._quiet_tick_count.get(symbol, 0) + 1
        return NO_NEW_IEX_BAR

    def observe_stale(self, symbol: str) -> tuple[str, bool]:
        """Call when the caller has already determined (from its own
        gap-over-threshold check) that `symbol` has gone stale THIS tick.
        Returns (STALE, newly_stale) -- newly_stale=True exactly once per
        episode, mirroring SessionRunner's existing `_stale_flagged` dedup
        contract (this tracker is a parallel, redundant-by-design
        classification layer; it never replaces that dedup, only enriches
        it -- see session_runner.py's integration)."""
        symbol = symbol.upper()
        previous = self._state.get(symbol, UNKNOWN)
        newly_stale = previous not in (STALE, DATA_GAP)
        self._state[symbol] = STALE
        if newly_stale:
            self._stale_episode_count[symbol] = self._stale_episode_count.get(symbol, 0) + 1
        return STALE, newly_stale

    def coverage_ratio(self, symbol: str) -> float | None:
        """fresh_bar_count / (fresh_bar_count + quiet_tick_count) -- the
        fraction of this session's checked ticks that produced a genuinely
        new bar for `symbol`. None if never checked at all yet (avoids a
        misleading 0.0 for a symbol simply not yet observed). This is a
        rolling, LIVE, in-memory metric -- distinct from, and never a
        substitute for, warmup.py's historical-lookback-based
        WarmupCheck.ready (see warmup_vs_live_suitability.csv)."""
        symbol = symbol.upper()
        fresh = self._fresh_bar_count.get(symbol, 0)
        quiet = self._quiet_tick_count.get(symbol, 0)
        total = fresh + quiet
        return None if total == 0 else fresh / total

    def mark_data_gap_at_session_end(self) -> list[str]:
        """Any symbol still STALE (never recovered) graduates to DATA_GAP
        -- an explicitly unresolved gap, distinct from an episode that
        later recovered. Returns the symbols that transitioned."""
        gapped = [s for s, st in self._state.items() if st == STALE]
        for s in gapped:
            self._state[s] = DATA_GAP
        return sorted(gapped)

    def record_provider_fetch_result(self, ok: bool) -> tuple[str, bool]:
        """ok=True: the last market-data fetch's own HTTP round-trip
        succeeded (status 200), regardless of whether any individual
        symbol had a new bar in it. ok=False: the fetch itself failed
        (raised, timed out, or returned non-200) -- a directly-observed
        technical fact about the PROVIDER, never inferred from how many
        symbols are individually stale (see module docstring for why that
        inference is unsound on this data). Returns
        (new_provider_state, transitioned)."""
        previous = self._provider_state
        if ok:
            self._consecutive_provider_failures = 0
            self._provider_state = HEALTHY
        else:
            self._consecutive_provider_failures += 1
            self._provider_state = (
                PROVIDER_UNAVAILABLE
                if self._consecutive_provider_failures >= _CONSECUTIVE_FAILURES_FOR_UNAVAILABLE
                else DEGRADED
            )
        return self._provider_state, self._provider_state != previous

    def snapshot(self) -> dict[str, object]:
        """Cheap, JSON-friendly snapshot for /ping or EOD reporting.
        `coverage` reports symbols unsuitable for the current minute-driven
        decision path CLEARLY (rolling ratio + raw counters) without ever
        auto-excluding a symbol on this basis alone -- that decision stays
        with the existing, unmodified readiness/warmup gates plus the
        stale-episode-driven STALE/DATA_GAP exclusion. A configured symbol
        is never silently removed from this snapshot even at 0 coverage."""
        symbols = sorted(set(self._state) | set(self._fresh_bar_count) | set(self._quiet_tick_count))
        return {
            "provider_state": self._provider_state,
            "symbols": dict(sorted(self._state.items())),
            "coverage": {
                s: {
                    "fresh_bar_count": self._fresh_bar_count.get(s, 0),
                    "quiet_tick_count": self._quiet_tick_count.get(s, 0),
                    "stale_episode_count": self._stale_episode_count.get(s, 0),
                    "coverage_ratio": self.coverage_ratio(s),
                }
                for s in symbols
            },
        }
