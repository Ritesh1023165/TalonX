# TASK 95G — Family B — Pullback Within Relative Strength Replication

Replication of Task 95E Family B. Rank = `pctrank(rel_20) − pctrank(rel_3)` (and the 20/5 version) —
high = strong over 20 days **and** weak over the last 3(5). Top decile (~50 names), daily rebalance.

| feature | k3 `top_decile_excess` / net@5 | k5 / net@5 | k10 / net@5 | T−B (k3) | symbol-block CI (k3) | years+ | verdict |
|---|---:|---:|---:|---:|---|---:|---|
| `pctrank(rel20) − pctrank(rel3)` | +2.0 / −12.0 | −? / −? | −? / −? | +16.6 | [−3, +7] | 1/4 | FAIL |
| `pctrank(rel20) − pctrank(rel5)` | **+3.8** / −8.3 | +0.8 / −19.4 | −13.5 / −54.0 | **+17.0** | **[−0.2, +8.1]** | 2/4 | FAIL |

## Reading

- Family B is the **only** family in Task 95G that is not negative-signed at the top decile: a small
  positive `top_decile_excess` (+2 to +4 bps at k3) and a positive `top_minus_bottom` (+17). This is
  a genuine, mild "buy the peer-relative dip in a relatively-strong name" tendency at 3 days —
  consistent with the reversal finding in Family A (recent *weakness* mean-reverts).
- But it **fails every economic gate**:
  - **G2:** net@5 = **−8.3 bps** (turnover 0.40/day erases the +3.8 gross); `top_minus_bottom` +17 < +20 bar.
  - **G3:** net@10 = −20.5; net@20 = −44.8.
  - **G4:** symbol-block CI **[−0.2, +8.1]** straddles zero; date-block CI [−9.3, +18.9] straddles zero.
  - **G5:** positive in only 2 of 4 discovery years (2021 −6.9, 2023 −7.1).
  - **G7:** decile gradient is **non-monotone** — D1 +3.8 but **D2 +31.3**, D3 +16.6, then negative
    D4–D10. The signal lives in the 2nd decile, not the 1st.
- Current vs removed: +1.9 / +13.2 — the mild effect is slightly stronger among removed names
  (a stress/reversal flavour), not a survivor effect.

## Verdict

**Family B — both `DISCOVERY_FAIL`.** A real but tiny reversal-flavoured tendency, economically
worthless after turnover, statistically indistinguishable from zero, non-monotone, and not
year-stable. Same conclusion as Task 95E, now on 500 names.
