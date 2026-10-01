# TASK 95B — Family B — Pullback in an Established Uptrend

**Hypothesis:** a stronger long-term uptrend plus a short-term pullback creates a favourable
long-only rebound/continuation.

**Pre-registered bins:** established uptrend = `adj_close > 50-day SMA` **and** `> 200-day SMA` (both
shifted). Conditioned on: 3-day prior return in the discovery bottom quintile; 5-day prior return
bottom quintile; 4–10 % below the prior 20-day high; daily RSI(14) < 40. Primary horizon 3–5 d.
Metric = net excess bps over the matched unconditional-long comparator.

## Result — 9 experiments (+1 inconclusive, n=7), 0 pass

| Bin | n | excess net @5 bps | @10 bps | non-overlap CI low | block-boot CI low | years+ | symbols+ | why it fails |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| uptrend + 3-day pullback bottom quintile (k=3) | 1,286 | +13.7 | +3.7 | +10.5 | +7.0 | 0.50 | 0.54 | S2 (< +25); S6 (remove-best kills it) |
| uptrend + 5-day pullback bottom quintile (k=5) | 1,026 | **−23.3** | −33.3 | −91.5 | −46.8 | 0.50 | 0.46 | negative — deeper pullbacks in uptrends keep falling over 5 d |
| uptrend + 4–10 % below 20-day high (k=5) | 3,610 | +4.1 | −5.9 | +5.7 | −10.1 | 0.25 | 0.40 | S2, S3, S4, S5, S6 |
| uptrend + daily RSI(14) < 40 (k=3) | 7 | — | — | — | — | — | — | INCONCLUSIVE — the condition almost never co-occurs (a name in a strong dual-SMA uptrend rarely has daily RSI < 40) |

## Interpretation

**No usable pullback edge.** The shallowest pullback (bottom-quintile 3-day dip within a dual-SMA
uptrend) is the only positive cell at +13.7 bps excess net @5 bps — real sign, but half the economic
bar and it does not survive removing the best contributors (S6). Going one step deeper (bottom-
quintile *5-day* pullback) flips to **−23 bps**: within this universe a multi-day drawdown inside an
uptrend is more often the start of a larger drop than a dip to buy. The "RSI dip in an uptrend"
bin is empty for practical purposes. The pullback thesis is not supported at swing horizons here.
