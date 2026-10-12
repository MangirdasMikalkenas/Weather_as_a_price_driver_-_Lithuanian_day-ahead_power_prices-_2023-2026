"""The pricing and IRRBB functions of src/bank_products.py, checked against closed-form results."""

from functools import partial

import numpy as np
import pytest

from bank_products import (banking_book_cash_flows, bond_value, discount_factors, eba_lower_bound, fx_forward_strike,
                           fx_forward_value, interpolation_matrix, nii_change, par_rate, payer_swap_value,
                           present_value, shocked_rates, supervisory_shocks)

TENORS = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30])
FLAT = np.full(len(TENORS), 0.03)
SLOPED = np.linspace(0.01, 0.035, len(TENORS))


def test_interpolation_matrix_matches_numpy_interp_and_stays_flat_outside():
    times = np.array([0.1, 0.25, 0.8, 4.0, 12.5, 30.0, 40.0])
    w = interpolation_matrix(TENORS, times)
    assert np.allclose(w @ SLOPED, np.interp(times, TENORS, SLOPED))
    assert np.allclose(w.sum(axis=1), 1)


def test_discount_factors_work_for_one_curve_and_for_many_scenarios():
    single = discount_factors(SLOPED, TENORS, [1.0, 5.0])
    many = discount_factors(np.vstack([SLOPED, FLAT]), TENORS, [1.0, 5.0])
    assert np.allclose(many[0], single)
    assert np.allclose(many[1], np.exp(-0.03 * np.array([1.0, 5.0])))


def test_a_bond_with_the_par_coupon_is_worth_par_and_a_swap_at_the_par_rate_is_worth_zero():
    for curve in (FLAT, SLOPED):
        k = par_rate(curve, TENORS, 10)
        assert bond_value(curve, TENORS, 1e7, k, 10) == pytest.approx(1e7)
        assert payer_swap_value(curve, TENORS, 2e7, par_rate(curve, TENORS, 5), 5) == pytest.approx(0, abs=1e-6)


def test_bond_sensitivity_equals_the_analytic_derivative_on_a_flat_curve():
    coupon, notional, bump = 0.025, 1e7, 1e-6
    times = np.arange(1, 11, dtype=float)
    cash_flows = notional * (coupon + (times == 10))
    analytic = -(times * cash_flows * np.exp(-0.03 * times)).sum()
    numeric = (bond_value(FLAT + bump, TENORS, notional, coupon, 10) - bond_value(FLAT - bump, TENORS, notional, coupon, 10)) / (2 * bump)
    assert numeric == pytest.approx(analytic, rel=1e-6)


def test_a_payer_swap_gains_when_rates_rise():
    k = par_rate(SLOPED, TENORS, 5)
    assert payer_swap_value(SLOPED + 0.001, TENORS, 2e7, k, 5) > 0 > payer_swap_value(SLOPED - 0.001, TENORS, 2e7, k, 5)


def test_fx_forward_is_worth_zero_at_inception_and_loses_when_the_dollar_weakens():
    spot, usd, maturity, usd_rate = 1.10, 1e7, 0.5, 0.04
    strike = fx_forward_strike(SLOPED, TENORS, spot, usd, maturity, usd_rate)
    assert fx_forward_value(SLOPED, TENORS, spot, usd, strike, maturity, usd_rate) == pytest.approx(0, abs=1e-6)
    value_weaker_dollar = fx_forward_value(SLOPED, TENORS, spot * 1.01, usd, strike, maturity, usd_rate)
    expected = usd * np.exp(-usd_rate * maturity) * (1 / (spot * 1.01) - 1 / spot)
    assert value_weaker_dollar == pytest.approx(expected)


def test_supervisory_shocks_follow_the_basel_formulas():
    shocks = supervisory_shocks(np.array([0.0, 1e6]))      # a very long maturity stands for infinity
    assert shocks["parallel up"] == pytest.approx([0.02, 0.02])
    assert shocks["short rates up"] == pytest.approx([0.025, 0.0])
    assert shocks["steepener"] == pytest.approx([-0.65 * 0.025, 0.9 * 0.01])
    assert shocks["flattener"] == pytest.approx([0.8 * 0.025, -0.6 * 0.01])


def test_eba_lower_bound_and_its_use():
    assert eba_lower_bound([0, 10, 50, 60]) == pytest.approx([-0.015, -0.012, 0.0, 0.0])
    times = np.array([1.0, 10.0])
    base = np.array([-0.02, 0.01])                         # the 1-year rate is already below the bound
    down = shocked_rates(base, times, np.array([-0.02, -0.03]))
    assert down == pytest.approx([-0.02, -0.012])          # observed rate kept; the 10-year rate stops at the bound
    small = shocked_rates(base, times, np.array([-0.001, -0.001]))
    assert small == pytest.approx([-0.02, 0.009])          # below the bound a rate cannot fall further; above it, it can


def flat(rate):
    return lambda t: np.full(np.shape(t), rate)


@pytest.mark.parametrize("item", [dict(amount=500.0, rate=0.035, years=15, kind="annuity"),
                                  dict(amount=150.0, rate=0.025, years=5, kind="bullet"),
                                  dict(amount=300.0, rate=0.005, years=5, kind="spread")])
def test_an_item_discounted_at_its_own_rate_is_worth_its_amount(item):
    # annual compounding at r is continuous compounding at ln(1 + r)
    assert present_value({"item": item}, flat(np.log1p(item["rate"]))) == pytest.approx(item["amount"])


def test_short_bullets_pay_once_and_overnight_items_are_repaid_at_once():
    times, flows = banking_book_cash_flows(dict(amount=300.0, rate=0.04, years=0.25, kind="bullet"))
    assert times == pytest.approx([0.25]) and flows == pytest.approx([303.0])
    overnight = {"deposits": dict(amount=200.0, rate=0.0, years=0.0, kind="bullet")}
    assert present_value(overnight, flat(0.05)) == pytest.approx(200.0)


BOOK_ASSETS = {"fixed-rate mortgages": dict(amount=500.0, rate=0.035, years=15, kind="annuity"),
               "floating-rate loans": dict(amount=300.0, rate=0.040, years=0.25, kind="bullet"),
               "government bonds": dict(amount=150.0, rate=0.025, years=5, kind="bullet")}
BOOK_LIABILITIES = {"deposits, non-core": dict(amount=200.0, rate=0.000, years=0.0, kind="bullet", non_maturity=True),
                    "deposits, core": dict(amount=300.0, rate=0.005, years=5, kind="spread", non_maturity=True),
                    "term deposits": dict(amount=250.0, rate=0.030, years=1, kind="bullet"),
                    "senior bonds issued": dict(amount=100.0, rate=0.032, years=5, kind="bullet")}


def test_nii_change_by_hand_and_the_deposit_floor_makes_it_asymmetric():
    nii = partial(nii_change, BOOK_ASSETS, BOOK_LIABILITIES, pass_through=0.5, hedge_notional=250.0)
    # +200 bp: hedge 250 x 2% x 0.75, floating loans 300 x 2% x 0.75, deposits (200 + 300) x 1% = 3.75 + 4.5 - 5.0
    assert nii(0.02) == pytest.approx(3.25)
    assert nii(-0.02, deposit_floor=None) == pytest.approx(-3.25)
    # -200 bp with a 0% floor: non-core deposits already pay 0%, core deposits fall from 0.5% to 0% instead of -0.5%
    assert nii(-0.02) == pytest.approx(-3.75 - 4.5 + 300 * 0.005)


def test_the_deposit_floor_never_raises_a_rate_already_below_it():
    negative = {"deposits": dict(amount=100.0, rate=-0.005, years=0.0, kind="bullet", non_maturity=True)}
    assert nii_change({}, negative, -0.02, pass_through=0.5) == pytest.approx(0.0)    # stays at -0.5%
    assert nii_change({}, negative, 0.02, pass_through=0.5) == pytest.approx(-1.0)    # -0.5% -> +0.5%
