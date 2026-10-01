# TASK 95G — Partition Rationale

Task 95G reuses the **Task 95B chronological partitions verbatim** — the same boundaries used by
Tasks 95B, 95D and 95E — so that the only variable changed relative to Task 95E is the **universe**
(35 survivor names → ~500-name point-in-time S&P 500).

| partition | dates | entry-eligible end | role in Task 95G |
|---|---|---|---|
| **Discovery** | 2020-01-02 → 2023-06-30 | 2023-06-15 | the **only** partition used. Ranking begins ~2020-10 once the 200-day feature warm-up is met for the broad universe. |
| Validation | 2023-07-17 → 2025-02-14 | 2025-01-31 | **UNTOUCHED** in Task 95G. |
| Holdout | 2025-03-03 → 2026-08-14 | 2026-07-31 | **UNTOUCHED** in Task 95G. |

- **Purge/embargo:** 10 trading days (= the maximum forward horizon) sit between discovery and
  validation, so no discovery forward-return window reaches into validation.
- Boundaries are **frozen regardless of results** and were not moved after any outcome was seen.
- A `DISCOVERY_PASS` in Task 95G would still require a **separate, authorised** validation task
  against the untouched validation partition (and broader-universe external validity remains a
  caveat regardless).
