# Remaining blockers & optional enhancements — Task 117 final-activation corrections

Not a claim that all possible defects are eliminated.

## Blockers for controlled activation — NONE identified

Every item the review raised (A1–A5, B) is closed with real evidence. The
activation procedure (`docs/audits/task117_overnight_release_closure/deployment_candidate.md`,
now corrected) still requires **execution** by a reviewer — that is a step,
not a blocker.

## Carried forward from the prior release bundle (still open, still not blocking)

- S1–S3 timestamp anomaly (~4 h gap, 3 records) — `UNRESOLVED`, isolated,
  unrelated to this correction.
- `talonx_ingest.intelligence.service` runs under the supervisor (this
  correction relies on that), but the supervisor itself is started
  on-demand by `prospective start`, not itself under a higher-level always-on
  service manager (e.g. a Windows service / systemd unit) — an operator must
  still run `prospective start` each morning. Out of scope for tonight.
- SGML-Eastern acceptance path implemented and tested but not wired into a
  live raw-SGML ingester (submissions JSON, the wired path, is verified
  genuine UTC).

## New, deliberately deferred by this correction's own scope

- **Deliverable A (exact 39-name V2 baseline) was not run tonight.** The
  inventory and frozen membership manifest are done
  (`docs/research/TASK118_INVENTORY.md` on the research branch); the run
  itself needs an isolated `ingestion_ledger.db` copy driven through
  `talonx_research/replay_engine` with `execution_allowlist` set to the 39
  names, 20 bps costs, and the Task 107B/112R discovery/holdout split
  re-stated — a genuine multi-hour analysis, correctly out of scope for a
  bounded release-correction session. First action for tomorrow's research
  time, per the contract.
- **Deliverable B (Original intraday selectivity) and C (Experimental
  separate accounting) were not started.** They depend on the same isolated
  ledger copy and are next after A per the contract's ordering.
- CIK-per-ticker cross-reference for the 39-name manifest was not hand-derived
  tonight (the resolution is deterministic via `scope.py::resolve_watchlist`,
  ticker-level scoping is what `V2Service`/`from_insider_store` actually key
  off); capture it alongside the first replay run.

## Reconciled-restore rollback path (§A5) is documented, not rehearsed live

`rollback.md`'s §3 (reconciled partial restore, for the case compatible-code
rollback alone is judged insufficient) is a **documented procedure**, not
exercised against a real post-activation write set tonight — because no
activation has happened yet, there is nothing to reconcile. It will be a real
step only after a real activation produces real post-backup writes.

## Explicitly out of scope for this correction (per its own constraints)

Production startup, external messages, production migration/backlog expiry
execution, database restoration, Redis mutation, strategy tuning/promotion,
execution-scope expansion, paid data, broker activity, main merge,
force-push. None were done.
