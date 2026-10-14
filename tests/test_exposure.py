"""The exposure model of src/exposure.py: curve fit, martingale tests, trades at par, the exposure of an FX forward
against its closed form, the calibration on a simulated market and SA-CCR by hand."""

import numpy as np
import pytest
from scipy import stats

from bank_products import fx_forward_strike, par_rate
from exposure import (HullWhite, calibrate_rate_and_fx, collateralised_values, discount_along_paths, effective_epe,
                      expected_positive_exposure, exposure_profile, fx_forward_paths, payer_swap_paths, sa_ccr_ead,
                      simulate_fx, supervisory_duration)

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


def test_exposure_profile_by_hand():
    values = np.array([[-1.0, 2.0], [3.0, -4.0], [5.0, 6.0], [-7.0, 8.0]])      # 4 paths, 2 dates
    ee, pfe = exposure_profile(values, 0.975)
    assert ee == pytest.approx([2.0, 4.0])              # the mean of max(value, 0): (3 + 5) / 4 and (2 + 6 + 8) / 4
    assert pfe == pytest.approx([4.85, 7.85])           # its 97.5% quantile (numpy): 3 + 0.925 x 2, 6 + 0.925 x 2
    assert exposure_profile(-np.abs(values), 0.975)[1].tolist() == [0.0, 0.0]   # nothing owed, no exposure


def test_the_exposure_of_an_fx_forward_matches_the_lognormal_closed_form():
    # with deterministic euro rates (Hull-White sigma 0, a flat 3% curve) the forward is worth a X(t) - k on date t,
    # with X(t) lognormal around its forward F: EE = a F N(d1) - k N(d2), and PFE = a X_q - k, X_q the 97.5% quantile
    r_eur, r_usd, vol, x0, notional, maturity = 0.03, 0.04, 0.10, 0.9, 1e7, 1.0
    model = HullWhite(np.full(len(TENORS), r_eur), TENORS, 0.03, 0.0)
    times, paths = np.array([0.0, 0.25, 0.5, 0.75, 1.0]), 200_000
    r = model.simulate(times, np.zeros((paths, len(times) - 1)))
    x = simulate_fx(times, r, x0, r_usd, vol, np.random.default_rng(3).standard_normal((paths, len(times) - 1)))
    strike = notional * x0 * np.exp((r_eur - r_usd) * maturity)                     # at par
    ee, pfe = exposure_profile(fx_forward_paths(model, times, r, x, notional, strike, maturity, r_usd)[0], 0.975)
    for k, t in enumerate(times[1:-1], start=1):
        a, b = notional * np.exp(-r_usd * (maturity - t)), strike * np.exp(-r_eur * (maturity - t))
        forward, s = x0 * np.exp((r_eur - r_usd) * t), vol * np.sqrt(t)
        d1 = (np.log(a * forward / b) + s ** 2 / 2) / s
        assert ee[k] == pytest.approx(a * forward * stats.norm.cdf(d1) - b * stats.norm.cdf(d1 - s), rel=0.02)
        assert pfe[k] == pytest.approx(a * forward * np.exp(-s ** 2 / 2 + s * stats.norm.ppf(0.975)) - b, rel=0.02)
    assert ee[-1] == pfe[-1] == 0.0                                                 # settled at maturity


@pytest.mark.parametrize("tenor", [1.0, 5.0])
def test_the_calibration_recovers_the_parameters_of_a_simulated_market(tenor):
    # one day of a Hull-White model and an FX rate with known parameters on 100,000 paths: the changes of the zero
    # rate of `tenor` years (volatility sigma B(0, tenor) / tenor) and of the log FX rate give the parameters back
    a, sigma, sigma_fx, rho, dt = 0.03, 0.01, 0.08, -0.4, 1 / 250
    model = HullWhite(CURVE, TENORS, a, sigma)
    rng = np.random.default_rng(4)
    z_rate = rng.standard_normal((100_000, 1))
    z_fx = rho * z_rate + np.sqrt(1 - rho ** 2) * rng.standard_normal(z_rate.shape)
    r = model.simulate(np.array([0.0, dt]), z_rate)
    x = simulate_fx(np.array([0.0, dt]), r, 0.9, 0.04, sigma_fx, z_fx)

    def zero_rate(t, short_rate):
        return -np.log(model.zero_bond(t, t + tenor, short_rate)) / tenor

    d_rate = zero_rate(dt, r[:, 1]) - zero_rate(0.0, r[:, 0])
    estimate = calibrate_rate_and_fx(d_rate, np.log(x[:, 1] / x[:, 0]), a, tenor)
    assert estimate["sigma"] == pytest.approx(sigma, rel=0.01)
    assert estimate["sigma_fx"] == pytest.approx(sigma_fx, rel=0.01)
    assert estimate["rho"] == pytest.approx(rho, abs=0.01)


def test_epe_and_effective_epe_follow_the_crr_sums():
    # CRR Article 284(5)-(6): effective EE_k = max(effective EE_(k-1), EE_k), and effective EPE = the sum over
    # k = 1..n of effective EE_k x (t_k - t_(k-1)), each step valued at its end
    times = np.array([0, 0.25, 0.5, 0.75, 1.0])
    ee = np.array([0.0, 4.0, 2.0, 6.0, 1.0])
    assert expected_positive_exposure(times, ee) == pytest.approx((4 + 2 + 6 + 1) * 0.25)
    assert effective_epe(times, ee) == pytest.approx((4 + 4 + 6 + 6) * 0.25)       # 5.0; 3.5 at the start of steps
    # unequal steps are weighted by their length, and a netting set maturing within a year is averaged to maturity
    assert effective_epe(np.array([0, 0.1, 0.5, 1.0]), np.array([1.0, 3.0, 2.0, 5.0])) == pytest.approx(
        3 * 0.1 + 3 * 0.4 + 5 * 0.5)
    assert effective_epe(times, ee, horizon=0.5) == pytest.approx((4 + 4) * 0.25 / 0.5)


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
