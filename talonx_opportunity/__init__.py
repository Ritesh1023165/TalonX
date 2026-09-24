"""
talonx_opportunity -- the Continuous Opportunity Engine (REQ S14-01..S14-06).

While TalonX runs, broad-universe opportunity discovery continues across every market phase the configured
provider actually supports (OVERNIGHT / PREMARKET / REGULAR / AFTER_HOURS; CLOSED / DATA_UNAVAILABLE otherwise).
Market phase may change the data source, liquidity context, classification context and execution eligibility --
it never globally suspends discovery.

Architecture (every component is its own restartable process and the SINGLE writer of its own store):

    DATA_INGESTION  -> market.db        (per-symbol session-to-date aggregates, daily history, watermarks, probes)
    DISCOVERY       -> opportunity.db   (UNCAPPED candidates + append-only lifecycle events + scans)
    <HORIZON>_EVALUATOR -> evaluators.db (INTRADAY / SAME_DAY / SHORT_TERM / LONG_TERM, each with its own cursor)
    NOTIFICATION_WORKER -> notification.db + research outbox (attention budget lives ONLY here)
    OUTCOME_TRACKING -> outcomes.db     (evaluation only, never feeds back into detection)
    REPORTING       -> reports/         (deployment-boundary aware)
    runtime.db      heartbeats, component events, DEPLOYMENT/CHANGE BOUNDARIES (written by each component at start)

Research lane only: it never trades, never emits a V2 TRADE_EVENT, never writes a V2 ledger/outbox and never
imports talonx_v2. PAPER_EXECUTION remains the frozen V2 companion (observed read-only).
"""
