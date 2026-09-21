# Task 57 — Execution Friction vs Trade Geometry Diagnostic

**Classification:** `BOTH_GROSS_AND_COST_WEAK`

Read-only diagnostic using committed Task 53, 54, and 56 trade evidence; no replay, tuning, filtering authorization, or production change.

## Headline

Combined RSI+MACD: 228 trades, gross +20.976R (+0.092R/trade), 5bps -73.901R (-0.324R/trade). Mean/median cost burden 0.416R/0.252R.

RSI: gross expectancy +0.355R, 5bps +0.053R, mean/median cost 0.302R/0.215R, median stop risk 0.466%. MACD: gross expectancy -0.113R, 5bps -0.619R, mean/median cost 0.505R/0.296R, median stop risk 0.338%.

Across the six predeclared stop-risk buckets with at least 10 trades per family, RSI exceeded MACD gross and at 5bps in four; it did not in 0.15–0.25% or >=0.75%. The approximate within-geometry advantage is substantial but not universal.

## Task 56 decomposition

RSI gross expectancy fell from +0.621R in Tasks 53+54 to +0.016R in Task 56; winner rate moved 33.9% to 34.1%, median stop risk 0.431% to 0.551%, and mean cost 0.338R to 0.256R. The holdout weakened mainly because gross winner economics disappeared toward zero; costs then overwhelmed that near-zero edge.

MACD gross expectancy improved from -0.198R to -0.021R and mean cost fell from 0.595R to 0.407R, but its holdout gross expectancy remained slightly negative. RSI's holdout deterioration was instead driven by average winning R falling from 3.778R to 1.507R; winner rate was essentially unchanged and geometry/cost improved.

## Conclusion

The top one/three/five/ten cost-R trades account for 15.7%/19.7%/22.9%/29.4% of total cost drag, but removing them does not make both families broadly healthy. Gross quality is weak overall while friction remains economically material. Therefore neither cost geometry alone nor a few pathological trades explain the result: `BOTH_GROSS_AND_COST_WEAK`.

Approximate within-geometry comparisons use only predeclared buckets; cells below 10 trades per family are flagged unsupported. Ex-post exclusions are sensitivity analysis only, not approved filters. Implied break-even bps are descriptive and are not a recommendation to assume cheaper execution.

Deployment remains `MONDAY_DECISION_SHADOW_ONLY`. No production action or capital is authorized.
