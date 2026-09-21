# Before / After — Actual Sender Payloads

## BEFORE (real, actually sent to Telegram — `raw_axon_provenance.txt`)

```
[INFO] AXON — Direct financial obligation (8-K Item 2.03/2.04)
direct financial obligation 8-K (Item 2.03/2.04)
Source: 2026-09-15 07:20 UTC (source age: 4.1h)
⚠️ Source freshness unknown at emit time
⚠️ Data limitations: multi_item_filing
Reply "details" for facts and filing link.
ℹ️ Information, not advice. TalonX makes no prediction about future price or returns.
```

```
[INFO] AXON — Regulation FD disclosure (8-K Item 7.01)
Regulation FD disclosure 8-K (Item 7.01)
Source: 2026-09-15 07:20 UTC (source age: 4.1h)
⚠️ Source freshness unknown at emit time
⚠️ Data limitations: multi_item_filing
Reply "details" for facts and filing link.
ℹ️ Information, not advice. TalonX makes no prediction about future price or returns.
```

Line 1 (category header) and line 2 ("evidence") say the **same thing
twice** — the entire message explains nothing beyond "this filing type
exists".

## AFTER — same two real events, run through the corrected policy (isolated verification, `isolated_verification_post_fix.txt`)

```
disposition: DIGEST | evidence_text: None
```
for both. Neither event has a genuine `SUBSTANTIVE_REASON_CODES` hit or
buy-cluster, so under the corrected policy **neither would be sent as an
immediate push at all** — both correctly fall through to `DIGEST`
(routine digest stays OFF; the events remain fully enriched and
dashboard-visible with their real reasons, per the requirement's own
"retain the event... with an explicit reason" instruction). This is the
honest, correct outcome: no genuine substantive fact exists in the
system today for either Item 2.03/2.04's specific terms or Item 7.01's
specific disclosed content, so no send is the truthful result — not a
gap papered over.

## AFTER — a FIXTURE positive example (not a real send; `tests/test_task140b_critical_content_gate.py::test_critical_band_with_genuine_substantive_reason_still_sends_one_useful_message`)

To prove the fix does not simply block all CRITICAL informational
alerts, a **synthetic fixture** (symbol `POSV`, a made-up quarterly
filing) carrying a genuine `XBRL_MAGNITUDE` reason — the same shape the
significance engine actually computes for a real large reported
financial-statement change — still sends cleanly:

```
[INFO] POSV — Quarterly report (10-Q)
very large reported revenue YOY change (magnitude 42%; size only, not direction)
Source: 2026-09-15 11:26 UTC (source age: 0.0h)
Reply "details" for facts and filing link.
ℹ️ Information, not advice. TalonX makes no prediction about future price or returns.
```

Line 2 now states a real, specific, already-computed fact (a 42% revenue
change) distinct from line 1's category label — exactly the contract
this fix enforces. **Labelled clearly: this is a test fixture, not a
real production send.**

## Freshness wording — before/after (same real AXON message)

**Before**: `⚠️ Source freshness unknown at emit time` — reads as if it
doubts the "Source: 2026-09-15 07:20 UTC (source age: 4.1h)" line
directly above it.

**After** (`test_freshness_wording_no_longer_implies_the_known_source_
timestamp_is_in_doubt`): `⚠️ Ingestion feed-poll currency not tracked
for this source (the filing date/age above is exact and unaffected)` —
names the actual, separate signal (an EDGAR-poll currency tracker,
verified `UNKNOWN` for 100% of persisted events today) without implying
doubt about the event's own, precisely-known timing.
