"""ERM nominee accounting fixtures (SYNTHETIC numbers only; no archive, no outcomes).

Compares the frozen primary metric -- the ratio of ALL-adjusted bars, pair_gross = -(C_exit/O_entry - 1)_stock +
(C_exit/O_entry - 1)_ETF (events.outcomes) -- with explicit fixed-entry-position cash-flow accounting:
short q_s = 1/S_entry shares, long q_e = 1/E_entry shares, positions NOT resized, cash distributions paid (short) or
received (long) in cash and NOT reinvested, spin-off entitlements delivered (short) / received (long) in kind.

Backward adjustment models (the provider's exact dividend/spin-off formula is not documented in the fetched API
reference; both common conventions are tested):
  MULT : prices before the ex-date x f, f = 1 - D / C_cum   (C_cum = close before the ex-date)
  SUB  : prices before the ex-date - D
Splits: prices before the ex-date / split ratio (exact under either model).
"""
import pytest

TOL = 1e-12


def mult_adj(price_before_ex, d, c_cum):
    return price_before_ex * (1 - d / c_cum)


def sub_adj(price_before_ex, d, c_cum):
    return price_before_ex - d


def ratio_ret(entry_adj, exit_adj):
    return exit_adj / entry_adj - 1


# ------------------------------------------------------------------------------------------------ 1 no action
def test_ordinary_two_leg_no_action_exact():
    S0, S10, E0, E10 = 100.0, 90.0, 50.0, 51.0
    pair_ratio = -ratio_ret(S0, S10) + ratio_ret(E0, E10)
    cash = (1 / S0) * (S0 - S10) + (1 / E0) * (E10 - E0)
    assert pair_ratio == pytest.approx(0.12, abs=TOL) and cash == pytest.approx(pair_ratio, abs=TOL)


# ------------------------------------------------------------------------------------------------ 2 splits
@pytest.mark.parametrize("ratio", [2.0, 0.1])          # 2:1 forward, 1:10 reverse
def test_split_inside_window_exact(ratio):
    S0_raw, S10_raw = 100.0, 45.0 * (2.0 / ratio)       # exit is post-split
    S0_adj = S0_raw / ratio
    pair_ratio = -ratio_ret(S0_adj, S10_raw)
    q = 1 / S0_raw
    cash = 1.0 - q * ratio * S10_raw                    # short q shares -> owes q*ratio after the split
    assert cash == pytest.approx(pair_ratio, abs=TOL)


# ------------------------------------------------------------------------------------------------ 3 stock cash dividend (short pays)
def _stock_div(model):
    S0, C_cum, d, S10 = 100.0, 101.0, 1.0, 95.0
    cash = (1 / S0) * (S0 - S10) - (1 / S0) * d        # short pays the dividend, no reinvestment
    adj = (mult_adj if model == "MULT" else sub_adj)(S0, d, C_cum)
    return cash, -ratio_ret(adj, S10)


def test_stock_cash_dividend_approximates_not_exact():
    cash, mult = _stock_div("MULT")
    _, sub = _stock_div("SUB")
    assert cash == pytest.approx(0.04, abs=TOL)
    assert mult == pytest.approx(0.0405, abs=1e-12)          # +5.0 bps vs cash
    assert sub == pytest.approx(0.0404040404, abs=1e-9)      # +4.04 bps vs cash
    # closed form (MULT): ratio - cash = d (C_cum - d - S_exit) / ((C_cum - d) S_entry): zero only if the price after
    # the ex-date ends exactly at the ex-adjusted level (reinvestment at the ex-date close earns nothing)
    S0, C, d, S10 = 100.0, 101.0, 1.0, 95.0
    assert mult - cash == pytest.approx(d * (C - d - S10) / ((C - d) * S0), abs=1e-12)


# ------------------------------------------------------------------------------------------------ 4 ETF cash distribution (long receives)
def test_etf_cash_distribution_approximates_not_exact():
    E0, C_cum, d, E10 = 50.0, 52.0, 0.5, 51.0
    cash = (1 / E0) * (E10 - E0) + (1 / E0) * d
    mult = ratio_ret(mult_adj(E0, d, C_cum), E10)
    assert cash == pytest.approx(0.03, abs=TOL)
    assert mult == pytest.approx(0.0299029126, abs=1e-9)     # -0.97 bps vs cash


# ------------------------------------------------------------------------------------------------ 5 special dividend: error scales with D/C
def test_large_special_dividend_diverges():
    S0, C_cum, d, S10 = 100.0, 100.0, 20.0, 85.0
    cash = (1 / S0) * (S0 - S10) - (1 / S0) * d                 # -0.05
    mult = -ratio_ret(mult_adj(S0, d, C_cum), S10)               # -0.0625
    assert cash == pytest.approx(-0.05, abs=TOL) and mult == pytest.approx(-0.0625, abs=TOL)
    assert abs(mult - cash) == pytest.approx(0.0125, abs=TOL)    # 125 bps of notional


# ------------------------------------------------------------------------------------------------ 6 spin-off (short delivers the spinco)
def test_spin_off_short_diverges_by_spinco_path():
    S0, C_cum, spin_value_at_ex, S10, spin_exit = 100.0, 100.0, 20.0, 76.0, 30.0
    q = 1 / S0
    ratio = -ratio_ret(mult_adj(S0, spin_value_at_ex, C_cum), S10)   # +0.05 (spinco value "reinvested" at ex)
    held_in_kind = q * (S0 - S10) - q * spin_exit                     # short also owes the spinco until cover: -0.06
    closed_at_ex = q * (S0 - S10) - q * spin_value_at_ex              # spinco obligation closed at ex value: +0.04
    assert ratio == pytest.approx(0.05, abs=TOL)
    assert held_in_kind == pytest.approx(-0.06, abs=TOL) and closed_at_ex == pytest.approx(0.04, abs=TOL)


# ------------------------------------------------------------------------------------------------ 7 adjustment-factor consistency
def test_post_window_dividend_invariance_depends_on_model():
    S0, S10 = 100.0, 95.0                                      # both prices precede a LATER dividend (after exit)
    later_d, later_c = 2.0, 98.0
    base = ratio_ret(S0, S10)
    m = ratio_ret(mult_adj(S0, later_d, later_c), mult_adj(S10, later_d, later_c))
    s = ratio_ret(sub_adj(S0, later_d, later_c), sub_adj(S10, later_d, later_c))
    assert m == pytest.approx(base, abs=TOL)                   # multiplicative: download-date invariant
    assert abs(s - base) > 1e-4                                # subtractive: ratio changes with later dividends


def test_ex_date_on_entry_session_carries_no_factor():
    # entry at the OPEN of the ex-date: the short is not liable (bought/sold ex); both endpoints are post-ex -> no factor
    S0_ex_open, S10 = 99.0, 95.0
    cash = (1 / S0_ex_open) * (S0_ex_open - S10)
    assert cash == pytest.approx(-ratio_ret(S0_ex_open, S10), abs=TOL)
