# Task 63P — ORPB_V1 Independent Validation #1

Classification: **ORPB_V1_REJECTED**

Trades: 46 (O1 13, O2 10, O3 23; 26 symbols).

Gross expectancy: -0.131247R. 5bps expectancy: -0.243162R; PF 0.625910; bootstrap 95% CI [-0.578847, 0.151632].

Mandatory failures: at_least_90_trades, at_least_20_each_window, at_least_25_winners, at_least_45_losses, gross_expectancy_strictly_positive, gross_exceeds_mean_cost_by_at_least_0_10R, net_5bps_expectancy_at_least_0_10R, net_5bps_pf_at_least_1_20, bootstrap_lower_bound_above_zero, two_positive_windows_none_below_minus_0_10R, top3_winner_removal_net_expectancy_above_zero, max_symbol_positive_R_share_at_most_20pct.

No tuning, variant replay, extra window, symbol change, post-outcome filter, capital, or production action occurred.
