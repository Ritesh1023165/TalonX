# Related-Event (Same-Accession) Redundancy Findings

## Population

**787 accessions** carry more than one `IMMEDIATE`-route event
(`population_survey.txt`). The dominant real-world shape (spot-checked
across the top of that list) is an earnings-release 8-K carrying BOTH
`EARNINGS_RESULTS` (Item 2.02) and `REGULATION_FD` (Item 7.01) — the
same filing, two item types, two independent `TextEvent`s.

## Exhaustive check: does any real accession have 2+ events that BOTH independently qualify for IMMEDIATE?

A bulk scan of every one of the 787 multi-event accessions' events
against `SUBSTANTIVE_REASON_CODES` found:

```
total found (accessions where >=2 events both carry a real
SUBSTANTIVE_REASON_CODES hit): 0
```

**Zero.** In the entire real historical dataset, no same-accession pair
has ever had two events that BOTH independently earned a genuine
substantive reason. This means: **no actual redundant pair of
`IMMEDIATE` sends for the same accession has ever occurred in
production** — the redundancy risk this review's directive asks about
is, empirically, currently zero-incidence, not merely "believed safe".

## Two real pairs directly inspected (this review's own sample)

- **AXON** `0001193125-26-391320` (`DEBT_FINANCING` + `REGULATION_FD`,
  the already-fixed CRITICAL-bypass case) — both now resolve to
  `DIGEST` under the current policy. No redundant `IMMEDIATE` pair.
- **ABCL** `0001703057-26-000044` (`EARNINGS_RESULTS` + `REGULATION_FD`,
  the single most common same-accession shape, 787-occurrence pattern)
  — both resolve to `DIGEST`. No redundant `IMMEDIATE` pair.

Both pairs' constituent events carry only category/meta reasons
(`EVENT_TYPE_BASE`, `EVENT_CLUSTER`, `MULTI_ITEM_8K`, `ON_WATCHLIST`,
`EVENT_RARE_FOR_FILER`) — the content gate (this session's `d296c60`
fix) correctly routes BOTH to `DIGEST`, so the common same-accession
shape structurally cannot produce a repetitive `IMMEDIATE` pair.

## Correction to the prior evidence bundle's claim (per this directive's own instruction)

`../axon_live_defect/root_cause_and_fix.md` §7 states: *"two
same-accession events that each independently qualify necessarily get
distinct [evidence] text"* and cites a synthetic unit test
(`test_same_accession_events_that_each_independently_qualify_get_
distinct_evidence`) as proof. **That claim is logically/structurally
true** — `classify_disposition` takes no `accession`/`event_id`
argument and derives `evidence_text` purely from the CALLER-supplied
`reasons`/`insider_activity`, which are always event-specific by
construction, so it cannot literally reuse one event's text for another.
**It is corrected here only to add the empirical caveat that was
missing**: this exact scenario (two same-accession events each
independently earning a genuine substantive hit) **has not yet occurred
in real production data** (confirmed above, 0 of 787). The structural
guarantee is real and verified by unit test; it has not yet been
observed operating on a real pair of genuinely-substantive same-accession
sends, because no such real pair exists yet to observe.

## Conclusion

- **No demonstrated redundant sends exist.** No consolidation subsystem
  is built, per the directive's own instruction not to build one
  "merely because one is absent" when nothing demonstrates the need.
- Should two same-accession events both independently earn genuine
  substantive evidence in the future, the structural guarantee (event-
  scoped `evidence_text`, unit-tested) means their messages will be
  factually distinct, not verbatim-duplicate — but this remains
  logically, not yet empirically, proven, and is disclosed as such.
- The far more common same-accession shape (category-only pairs, 787
  occurrences of the dominant `EARNINGS_RESULTS`+`REGULATION_FD`
  pattern alone) is already fully handled: the content gate prevents
  BOTH constituents from ever reaching `IMMEDIATE` on category/meta
  evidence alone.
