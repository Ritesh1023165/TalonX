# Accepted baseline
Milestones: Packages 1-5, RI-1..RI-4, PQ-1, PQ-2A, PQ-2A closure, PQ-2B, FINAL V2 RELEASE ACCEPTANCE.
Verdict: V2_RELEASE_ACCEPTED_WITH_BOUNDED_FOLLOWUPS at **b723901** (34 PASS / 4 BOUNDED_FOLLOWUP / 0 blocking).
See `docs/research/evidence/v2_final_release_acceptance/`.

**Difference between the accepted candidate and the frozen SHA.** The frozen SHA (a56ec8c) is b723901 plus ONE commit that only adds the
release-freeze mechanism required by this task's "new clean campaign" and "explicit frozen SHA" requirements:
- `talonx_v2/release_gate.py`: release campaign identity (V2-PAPER-RC1, own ledger), new gate check, create-once campaign init, clean-state verifier
- `talonx_ops/prospective/paths.py`: ledger/status paths honour TALONX_V2_DB_PATH / TALONX_V2_STATUS_PATH (default unchanged)
- `talonx_ops/prospective/preflight.py`: frozen-release pin check (exact SHA, or a descendant that changes only docs/tests/pin)
- `talonx_ops/prospective/__main__.py`: the start gate now sees the full environment (previously only the 4 resolved vars)
- `tests/test_v2_final_release_acceptance.py`: +8 tests

No strategy file (config.py, cluster_engine.py, liquidity.py, quant_bridge.py, brain_bridge.py), no provider semantics, no pricing/accounting file changed.
Strategy fingerprint e2acf6454789217e and provider contract fingerprint ac5e51aa3599d6c9 are byte-identical to the accepted state.
