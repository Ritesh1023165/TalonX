# Remaining blockers & optional enhancements — after Task 117 overnight closure

Not a claim that all possible defects are eliminated. This is the honest list of
what is still open, split into **blockers for controlled activation** vs
**optional enhancements**.

## Blockers for controlled activation — NONE identified

Every enumerated §1–§6 correctness / delivery / startup / dashboard item is
closed with evidence (`acceptance_matrix.md`). The activation procedure
(`deployment_candidate.md`) still requires **execution** by a reviewer — that is
a step, not a blocker.

## Known-open items carried forward (do not block a controlled paper activation)

| id | item | severity | why it does not block |
|---|---|---|---|
| **S1–S3 timestamp anomaly** | the ~4 h gap between persisted `retrieved_at` and the SEC acceptance time on the S1–S3 live records contradicts the verified SGML↔submissions-JSON evidence; no live EDGAR for 2026 accessions to re-fetch | P2, **UNRESOLVED** | isolated to 3 records already in the ledger; the parser contract is correct and unchanged; no production history was reinterpreted (Task E manifest 0 VERIFIED_CORRECTION). Tracked in `docs/audits/task117_delivery_timestamp_completion/timestamp_source_contract.md`. |
| **SGML-Eastern acceptance path not wired** | `parse_acceptance_datetime_ex(source="sgml_header")` (Eastern, DST-aware) is implemented + tested but the ingest path only calls `source="submissions"` | P3 | submissions JSON `Z` is verified genuine UTC; the SGML path is a latent capability for a future raw-SGML ingester, not a live gap. |
| **`talonx_ingest.intelligence.service` is not continuously supervised** | the poll loop is run on demand, not under the supervisor; dashboard shows `NO_ACTIVE_PRODUCER` / "not continuously scheduled (Task 99K/99L)" | P2 | Intelligence-card delivery is activated as an explicit operator step (`poll --send`), not an always-on service, in this release. Bringing it under supervision is Task 99K/99L / a follow-up. |
| **live-source adapter parity** | replay parity is proven on cached parquet + the isolated ingestion DB; the live-source boundary was exercised with grounded inputs but not against a fresh live EDGAR pull (none available for 2026 accessions) | P3 | frozen V2 fingerprint replays bit-for-bit (Task 116); the live boundary test uses real cached primary sources, not invented confirmation. |
| **dashboard runtime badges show FAILED/DEGRADED in the fixture** | expected — the isolated fixture has no live producers | not a defect | the false-zero guard renders this honestly; a live session shows real health. |

## Optional enhancements (nice-to-have, explicitly NOT done tonight)

- Bring the Intelligence poll loop under the supervisor with its own heartbeat
  and a dashboard producer badge.
- Wire the SGML-Eastern acceptance path into a raw-SGML ingester and add a
  live-boundary parity test once 2026 accessions are fetchable.
- A dedicated headless-render harness (the `?nows=1` affordance + a small
  screenshot script) promoted from `results/` into `tests/` for CI dashboard
  snapshots.
- Lane-suffix the `metrics:<date>:quant:*` Redis counters so Original and
  Experimental stop incrementing the same keys (the comingling is currently
  handled by *labelling*, not by *separation*).
- Persist a point-in-time snapshot of the quant funnel counters at each
  checkpoint so a future "16:24 ping" is reconstructable.

## Explicitly out of scope for this task (Task F constraints)

Production launch, external messages, ledger/source/Redis/watchlist/backlog
mutation, frozen-threshold changes, Experimental external delivery, data
purchase, broker execution, main merge / force-push, historical-timestamp
reinterpretation, production rebuild. None were done.
