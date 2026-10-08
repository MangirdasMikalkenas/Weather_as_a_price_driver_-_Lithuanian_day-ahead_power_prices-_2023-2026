"""The exposure model of src/exposure.py: curve fit, martingale tests, trades at par and SA-CCR by hand."""

import numpy as np
import pytest

from bank_products import fx_forward_strike, par_rate
from exposure import (HullWhite, collateralised_values, discount_along_paths, effective_epe,
                      expected_positive_exposure, fx_forward_paths, payer_swap_paths, sa_ccr_ead, simulate_fx,
                      supervisory_duration)

TENORS = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30])
CURVE = np.linspace(0.02, 0.035, len(TENORS))


def simulation(paths=20_000, years=5, step=1 / 24, a=0.03, sigma=0.01, seed=0):
    model = HullWhite(CURVE, TENORS, a, sigma)
    times = np.round(np.arange(0, years + 1e-9, step), 10)
    rng = np.random.default_rng(seed)
    return model, times, model.simulate(times, rng.standard_normal((paths, len(times) - 1))), rng


def test_the_model_reproduces_todays_curve():
    model = HullWhite(CURVE, TENORS, 0.03, 0.01)
    r0 = model.f0(0.0)[0]
    for maturity in (1.0, 5.0, 10.0):
        assert model.zero_bond(0.0, maturity, r0) == pytest.approx(model.p0(maturity)[0], rel=1e-6)


def test_discounted_zero_bonds_are_martingales():
    model, times, r, _ = simulation()
    discount = discount_along_paths(times, r)
    for t, maturity in [(1.0, 3.0), (2.0, 5.0)]:
        k = int(np.argmin(np.abs(times - t)))
        draws = discount[:, k] * model.zero_bond(times[k], maturity, r[:, k])
        error = draws.std(ddof=1) / np.sqrt(len(draws))
        assert abs(draws.mean() - model.p0(maturity)[0]) < 4 * error + 2e-4


def test_the_discounted_foreign_bond_in_euros_is_a_martingale():
    model, times, r, rng = simulation(paths=20_000, years=2)
    x = simulate_fx(times, r, 0.9, 0.04, 0.08, rng.standard_normal(r[:, 1:].shape))
    k = len(times) - 1
    draws = discount_along_paths(times, r)[:, k] * x[:, k]                 # one unit of foreign currency held to t
    expected = 0.9 * np.exp(-0.04 * times[k])
    assert abs(draws.mean() - expected) < 4 * draws.std(ddof=1) / np.sqrt(len(draws))


def test_trades_at_par_are_worth_zero_today_and_their_cash_flows_are_fair():
    model, times, r, rng = simulation(paths=20_000, years=5)
    swap, swap_flows = payer_swap_paths(model, times, r, 2e7, float(par_rate(CURVE, TENORS, 5)), 5)
    assert np.abs(swap[:, 0]).max() < 1e-4
    # a trade at par: the expected discounted cash flows are worth zero today
    discounted = (discount_along_paths(times, r) * swap_flows).sum(axis=1)
    assert abs(discounted.mean()) < 4 * discounted.std(ddof=1) / np.sqrt(len(discounted))
    assert np.count_nonzero(swap_flows[0]) == 5                             # five annual payments
    x = simulate_fx(times, r, 1 / 1.1, 0.04, 0.08, rng.standard_normal(r[:, 1:].shape))
    strike = float(fx_forward_strike(CURVE, TENORS, 1.1, 1e7, 0.5, 0.04))
    forward, forward_flows = fx_forward_paths(model, times, r, x, 1e7, strike, 0.5, 0.04)
    assert np.abs(forward[:, 0]).max() < 1e-4
    assert (swap[:, times >= 5 - 1e-9] == 0).all() and (forward[:, times >= 0.5 - 1e-9] == 0).all()
    assert np.count_nonzero(forward_flows[0]) == 1                          # settlement at 6 months


def test_epe_and_effective_epe():
    times = np.array([0, 0.25, 0.5, 0.75, 1.0])
    ee = np.array([0.0, 4.0, 2.0, 6.0, 1.0])
    assert expected_positive_exposure(times, ee) == pytest.approx((0 + 4 + 2 + 6) * 0.25)
    assert effective_epe(times, ee) == pytest.approx((0 + 4 + 4 + 6) * 0.25)   # the running maximum of EE


def test_collateral_leaves_only_the_change_over_the_margin_period_and_ignores_payments():
    values = np.array([[0.0, 5.0, 7.0, 4.0]])
    assert collateralised_values(values).tolist() == [[0.0, 5.0, 2.0, -3.0]]
    # a payment of 3 received at the last step explains the drop in value: no loss is left
    assert collateralised_values(values, np.array([[0.0, 0.0, 0.0, 3.0]])).tolist() == [[0.0, 5.0, 2.0, 0.0]]


def test_sa_ccr_matches_a_calculation_by_hand():
    swap = {"kind": "ir", "notional": 20e6, "start": 0.0, "end": 5.0, "delta": 1}
    forward = {"kind": "fx", "notional": 9e6, "maturity": 0.5, "delta": 1}
    ead_swap, _ = sa_ccr_ead([swap])
    assert ead_swap == pytest.approx(1.4 * 0.005 * 20e6 * (1 - np.exp(-0.25)) / 0.05)
    ead_forward, _ = sa_ccr_ead([forward])
    assert ead_forward == pytest.approx(1.4 * 0.04 * 9e6 * np.sqrt(0.5))
    ead_both, parts = sa_ccr_ead([swap, forward])
    assert ead_both == pytest.approx(ead_swap + ead_forward)               # no diversification across asset classes
    ead_margined, _ = sa_ccr_ead([swap, forward], margined=True)
    # margined: every trade gets the maturity factor 1.5 x sqrt(10 / 250) = 0.3, including the 6-month forward
    assert ead_margined == pytest.approx(1.4 * 0.3 * (0.005 * 20e6 * supervisory_duration(0, 5) + 0.04 * 9e6))
    assert supervisory_duration(0, 5) == pytest.approx(4.4239843, rel=1e-6)
