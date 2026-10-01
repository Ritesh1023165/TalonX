# TASK 95B — Family E — Gap / Event Follow-Through (price/volume only)

**Hypothesis:** an overnight gap (with or without volume) is followed by multi-day continuation or
mean-reversion. **Long-only.** No earnings/event timestamps are available in `task95a_expanded_v1`,
so this family is **price/volume only** — a gap is defined purely as `adj_open(t) / adj_close(t−1) − 1`.
This is a documented data limitation: a clean earnings/catalyst calendar would let E test
post-catalyst drift separately from mechanical gaps.

**Pre-registered bins:** top-decile up gap; top-decile up gap + volume ≥ 2× 20-day median;
bottom-decile down gap; bottom-decile down gap + volume ≥ 2×. Primary horizon 2 d (up-gap
continuation) / 3 d (down-gap rebound). Metric = net excess bps over the matched unconditional-long
comparator.

## Result — 10 unconditioned + regime-conditioned experiments, 0 pass (after adjudication)

| Bin | n | excess net @5 bps | @10 bps | non-overlap CI low | block-boot CI low | years+ | why it fails |
|---|---:|---:|---:|---:|---:|---:|---|
| top-decile up gap (k=2) | 3,040 | **−36.4** | −46.4 | −42.7 | −41.0 | 0.25 | up-gaps **fade** hard — long the gap is a large loser |
| top-decile up gap + volume ≥ 2× (k=2) | 382 | **−38.6** | −48.6 | −133.6 | −74.9 | 0.50 | volume makes the fade worse; S1 (n < 300) |
| bottom-decile down gap (k=3) | 3,039 | −1.7 | −11.7 | −21.3 | −11.3 | 0.50 | no edge unconditioned |
| bottom-decile down gap + volume ≥ 2× (k=3) | 442 | −4.8 | −14.8 | −78.5 | −42.3 | 0.75 | no edge |

### Regime-conditioned (Phase 10) — the automated PASS and its rejection

`E-gapdn_p10 × vol_high` (bottom-decile down gap, high realized-vol regime, k=3) **passed the
automated S1–S10 check** (n=1,177; excess net @5 +63.7; net @20 +33.7; non-overlap CI [+6.4, +138.6];
block-boot [+44.7, +112.0]; years+ 0.75; symbols+ 0.74; best-year share 0.40). It is **adjudicated
`DISCOVERY_FAIL`** for these documented reasons:

1. **Wrong comparator.** Scored vs the *global* discovery mean (26.4 bps/3 d). Against the
   **regime-matched vol_high baseline** (55.1 bps/3 d) the excess falls to +35 net @5, and the
   non-overlap CI becomes **[−22.3, +109.9] — includes zero (S4 fail)**; at k=5 the non-overlap CI
   is entirely negative.
2. **~77 % of the return is the market.** Phase 15: the equal-weight-basket return over the **exact
   same event dates** is **+76.6 bps** vs the candidate's +100.2 bps raw. The events cluster on days
   that immediately preceded broad market rallies; the signal-specific residual is ~23 bps, below
   the +25 bar.
3. **Negative in the bear year that holds half the events.** By-year excess (vs vol_high baseline):
   2020 +120 · 2021 +140 · **2022 −47 (n = 588 of 1,177)** · 2023 +211. It is a V-bottom /
   crash-recovery effect (2020 Q1–Q2, late-2022 → 2023), not a general swing edge.
4. **Phase 13 fail — remove best year → negative.** −6.3 bps at k=3, −28.9 at k=5 (vs vol_high
   baseline).
5. **Negative on the liquid COMMON10 universe** (net @5 −20.7; best-symbol share 0.32).
6. **1 of 35 (family-best × regime) grid cells** — protocol §7 automatic-reject for a grid-selected
   cell whose mechanism holds only in a specific historical episode.

Other stress-regime cells (`E-gapdn_p10 × mkt_bull` +26.6, `× dd20` +15.3) fail S4 (non-overlap CI
spans zero) and/or S7.

## Interpretation

**Up-gaps mean-revert** strongly at 1–2 days (long-the-gap loses 36–39 bps of excess) — a clean
negative. **Down-gaps** carry no edge on their own; the only positive appears when they coincide with
a high-volatility regime, and that is the same crash-recovery artifact as Family D, not a repeatable
phenomenon. A proper earnings/catalyst calendar would be required to test true post-event drift; on
price/volume alone, no gap candidate advances.
