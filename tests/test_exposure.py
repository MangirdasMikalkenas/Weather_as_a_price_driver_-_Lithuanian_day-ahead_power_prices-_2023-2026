"""The exposure model of src/exposure.py: curve fit, the bond price and the drift against independent integrals,
martingale tests, trades at par and their cash flows, the exposure of an FX forward against its closed form, the
calibration on a simulated market and by hand, and SA-CCR by hand."""

import numpy as np
import pytest
from scipy import stats
from scipy.integrate import quad

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


def test_todays_forward_rates_are_the_slope_of_the_discount_curve():
    # zero rates are linear between tenors, 0.15 percentage points apart, so f(0, t) = d(r(t) t)/dt = r(t) + t r'(t)
    # inside each segment, and 2% below the first tenor, where the curve is flat
    model = HullWhite(CURVE, TENORS, 0.03, 0.01)
    step = CURVE[1] - CURVE[0]
    times = np.array([0.0, 0.1, 1.5, 4.0, 12.0])
    slopes = np.array([0.0, 0.0, step / 1, step / 2, step / 5])              # segments [1, 2], [3, 5] and [10, 15]
    assert model.f0(times) == pytest.approx(np.interp(times, TENORS, CURVE) + times * slopes, abs=1e-10)


def test_the_bond_price_is_the_expected_discount_given_the_short_rate():
    # given r(t), the integral of the short rate from t to T is normal: its mean is the integral of the drift shift phi
    # plus (r(t) - phi(t)) B(t, T), its variance sigma^2 times the integral of B(u, T)^2, and P(t, T) = exp(-mean +
    # variance / 2). Integrated numerically, this must match the model's closed form to rounding error
    a, sigma = 0.03, 0.01
    model = HullWhite(CURVE, TENORS, a, sigma)

    def phi(s):
        return model.f0(s)[0] + sigma ** 2 / (2 * a ** 2) * (1 - np.exp(-a * s)) ** 2

    for t, maturity, r in [(1.0, 3.0, 0.01), (2.0, 10.0, 0.05), (4.5, 7.0, -0.01)]:
        kinks = TENORS[(TENORS > t) & (TENORS < maturity)]                 # the forward curve jumps at the tenors
        b = (1 - np.exp(-a * (maturity - t))) / a
        mean = quad(phi, t, maturity, points=kinks)[0] + (r - phi(t)) * b
        variance = sigma ** 2 * quad(lambda u: ((1 - np.exp(-a * (maturity - u))) / a) ** 2, t, maturity)[0]
        assert model.zero_bond(t, maturity, [r])[0] == pytest.approx(np.exp(-mean + variance / 2), rel=1e-9)


def test_without_shocks_the_short_rate_is_the_shift_that_fits_todays_curve():
    # with all normals zero the short rate is the shift phi(t) and the bank account discounts by exp(-integral of phi);
    # the shocks would add the convexity E[exp(-integral of x)] = exp(V / 2), V = sigma^2 times the integral of
    # B(u, t)^2 over [0, t], and together they must give today's discount factors
    a, sigma = 0.03, 0.01
    model = HullWhite(CURVE, TENORS, a, sigma)
    times = np.round(np.arange(0, 10 + 1e-9, 0.01), 10)        # the forward curve jumps at tenors, all on the grid
    discount = discount_along_paths(times, model.simulate(times, np.zeros((1, len(times) - 1))))[0]
    for t in (1.5, 4.0, 9.5):                                               # dates between tenors
        variance = sigma ** 2 * quad(lambda u: ((1 - np.exp(-a * (t - u))) / a) ** 2, 0, t)[0]
        k = int(np.argmin(np.abs(times - t)))
        assert discount[k] * np.exp(variance / 2) == pytest.approx(model.p0(t)[0], rel=1e-7)


def test_each_column_of_normals_moves_the_short_rate_and_the_exchange_rate_in_its_own_step():
    # one shock of one standard deviation in the step from 0.5 to 1 year: the short rate jumps there by the standard
    # deviation of the exact Ornstein-Uhlenbeck step and then reverts at the speed a, and the exchange rate moves there
    # by sigma_fx sqrt(dt) in logs; rate and FX shocks of the same step are the ones the calibration correlates
    a, sigma, sigma_fx, dt = 0.5, 0.01, 0.1, 0.5
    model = HullWhite(CURVE, TENORS, a, sigma)
    times = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    shock = np.zeros((1, 4))
    shock[0, 1] = 1.0
    response = model.simulate(times, shock) - model.simulate(times, np.zeros((1, 4)))
    jump = sigma * np.sqrt((1 - np.exp(-2 * a * dt)) / (2 * a))
    assert response[0] == pytest.approx([0.0, 0.0, jump, jump * np.exp(-a * dt), jump * np.exp(-2 * a * dt)])
    fx = simulate_fx(times, np.zeros((1, 5)), 1.0, 0.0, sigma_fx, shock)
    assert np.diff(np.log(fx[0])) + sigma_fx ** 2 / 2 * dt == pytest.approx([0.0, sigma_fx * np.sqrt(dt), 0.0, 0.0])


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
    # without FX volatility it holds on every path and date: the drift is each step's average euro rate, as in the
    # bank account
    certain = simulate_fx(times, r, 0.9, 0.04, 0.0, np.zeros_like(r[:, 1:]))
    assert np.allclose(discount_along_paths(times, r) * certain, 0.9 * np.exp(-0.04 * times), rtol=1e-12, atol=0)


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
    k = int(np.argmin(np.abs(times - 0.5)))
    assert forward_flows[:, k] == pytest.approx(1e7 * x[:, k] - strike)     # dollars received, euros paid


def test_a_swap_pays_the_coupon_fixed_a_year_before_and_is_worth_a_new_swap_at_each_reset():
    # on annual dates, a year past maturity: the first coupon is fixed today at 1 / P(0, 1) - 1 and the last one at year
    # 4; right after each payment the next coupon is reset to the market, so the floating leg is worth par and the
    # swap is worth 1 - P(t, 5) - fixed x the sum of P(t, t_i) over the payments left, per unit of notional
    model = HullWhite(CURVE, TENORS, 0.03, 0.01)
    times = np.arange(0, 7, dtype=float)
    r = model.simulate(times, np.random.default_rng(11).standard_normal((50, 6)))
    notional, fixed = 1e6, 0.03
    values, flows = payer_swap_paths(model, times, r, notional, fixed, 5)
    assert flows[:, 1] == pytest.approx(np.full(50, notional * (1 / model.p0(1.0)[0] - 1 - fixed)))
    assert flows[:, 5] == pytest.approx(notional * (1 / model.zero_bond(4.0, 5.0, r[:, 4]) - 1 - fixed))
    for k in range(1, 5):
        bonds = np.column_stack([model.zero_bond(times[k], maturity, r[:, k]) for maturity in range(k + 1, 6)])
        assert values[:, k] == pytest.approx(notional * (1 - bonds[:, -1] - fixed * bonds.sum(axis=1)))
    assert (values[:, 5:] == 0).all() and (flows[:, 6] == 0).all()           # nothing is left after maturity


def test_exposure_profile_by_hand():
    values = np.array([[-1.0, 2.0], [3.0, -4.0], [5.0, 6.0], [-7.0, 8.0]])      # 4 paths, 2 dates
    ee, pfe = exposure_profile(values, 0.975)
    assert ee == pytest.approx([2.0, 4.0])              # the mean of max(value, 0): (3 + 5) / 4 and (2 + 6 + 8) / 4
    assert pfe == pytest.approx([4.85, 7.85])           # its 97.5% quantile (numpy): 3 + 0.925 x 2, 6 + 0.925 x 2
    assert exposure_profile(-np.abs(values), 0.975)[1].tolist() == [0.0, 0.0]   # nothing owed, no exposure
    assert exposure_profile(values)[1] == pytest.approx(pfe)                     # the 97.5% quantile by default


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


def test_the_calibration_by_hand():
    # four days: sample standard deviations (n - 1 in the denominator), 250 days a year and the 1-year rate by default,
    # whose volatility is sigma B(0, 1)
    d_rate, d_log_fx, a = np.array([1.0, -2.0, 0.5, 1.5]) * 1e-3, np.array([4.0, -6.0, 1.0, 3.0]) * 1e-3, 0.03
    sample_sd = {name: np.sqrt(np.sum((x - x.mean()) ** 2) / 3) for name, x in [("rate", d_rate), ("fx", d_log_fx)]}
    estimate = calibrate_rate_and_fx(d_rate, d_log_fx, a)
    assert estimate["sigma"] == pytest.approx(sample_sd["rate"] * np.sqrt(250) * a / (1 - np.exp(-a)))
    assert estimate["sigma_fx"] == pytest.approx(sample_sd["fx"] * np.sqrt(250))
    assert estimate["rho"] == pytest.approx(stats.pearsonr(d_rate, d_log_fx)[0])


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
    assert expected_positive_exposure(times, ee, horizon=0.5) == pytest.approx((4 + 2) * 0.25 / 0.5)
    # by default both average over the first year of a longer profile
    longer_times, longer_ee = np.array([0, 0.5, 1.0, 1.5, 2.0]), np.array([0.0, 2.0, 1.0, 8.0, 8.0])
    assert expected_positive_exposure(longer_times, longer_ee) == pytest.approx((2 + 1) * 0.5)
    assert effective_epe(longer_times, longer_ee) == pytest.approx((2 + 2) * 0.5)


def test_collateral_leaves_only_the_change_over_the_margin_period_and_ignores_payments():
    values = np.array([[0.0, 5.0, 7.0, 4.0], [0.0, -2.0, -1.0, -6.0]])          # two paths
    assert collateralised_values(values).tolist() == [[0.0, 5.0, 2.0, -3.0], [0.0, -2.0, 1.0, -5.0]]
    # a payment of 3 received on the first path at the last step explains its drop in value: no loss is left
    payments = np.array([[0.0, 0.0, 0.0, 3.0], [0.0, 0.0, 0.0, 0.0]])
    assert collateralised_values(values, payments).tolist() == [[0.0, 5.0, 2.0, 0.0], [0.0, -2.0, 1.0, -5.0]]


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
    assert supervisory_duration(1, 10) == pytest.approx(6.8939738, rel=1e-6)    # a 9-year swap starting in a year


def test_sa_ccr_nets_within_a_maturity_bucket_and_correlates_the_buckets():
    # interest rate trades fall into buckets by end date: under a year, one to five years, over five years. Each adds
    # delta x notional x supervisory duration (exp(-5% S) - exp(-5% E)) / 5% x maturity factor to its bucket, and the
    # buckets combine with correlations of 70% between neighbours and 30% between the first and the third
    def duration(start, end):
        return (np.exp(-0.05 * start) - np.exp(-0.05 * end)) / 0.05

    trades = [{"kind": "ir", "notional": 10e6, "start": 0.0, "end": 0.5, "delta": 1},     # factor sqrt(0.5)
              {"kind": "ir", "notional": 15e6, "start": 0.0, "end": 1.0, "delta": 1},     # one year: the second bucket
              {"kind": "ir", "notional": 20e6, "start": 0.0, "end": 5.0, "delta": -1},    # five years: still the second
              {"kind": "ir", "notional": 25e6, "start": 1.0, "end": 6.0, "delta": 1}]     # starts in a year: the third
    buckets = np.array([10e6 * duration(0, 0.5) * np.sqrt(0.5),
                        15e6 * duration(0, 1) - 20e6 * duration(0, 5),
                        25e6 * duration(1, 6)])
    correlation = np.array([[1.0, 0.7, 0.3], [0.7, 1.0, 0.7], [0.3, 0.7, 1.0]])
    add_on = 0.005 * np.sqrt(buckets @ correlation @ buckets)
    ead, parts = sa_ccr_ead(trades)
    assert ead == pytest.approx(1.4 * add_on, rel=1e-12)
    assert parts == {"replacement cost": 0.0, "add-on, interest rates": pytest.approx(add_on, rel=1e-12),
                     "add-on, FX": 0.0, "multiplier": 1.0}


def test_sa_ccr_replacement_cost_collateral_and_multiplier_by_hand():
    # two forwards on one currency pair net before the 4% add-on; the multiplier, min(1, 5% + 95% exp((V - C) /
    # (2 x 95% x add-on))), falls below 1 when the trades are worth less than the collateral, and the replacement cost
    # max(V - C, 0) counts what is owed beyond it
    trades = [{"kind": "fx", "notional": 9e6, "maturity": 0.75, "delta": 1},
              {"kind": "fx", "notional": 4e6, "maturity": 0.5, "delta": -1}]
    add_on = 0.04 * (9e6 * np.sqrt(0.75) - 4e6 * np.sqrt(0.5))                       # 198,632

    def multiplier(net):
        return 0.05 + 0.95 * np.exp(net / (2 * 0.95 * add_on))

    for value, collateral, replacement, factor in [(0.0, 0.0, 0.0, 1.0),
                                                   (-1e5, 0.0, 0.0, multiplier(-1e5)),           # 0.779
                                                   (2e4, 5e4, 0.0, multiplier(-3e4)),            # 0.927
                                                   (5e4, 2e4, 3e4, 1.0)]:
        ead, parts = sa_ccr_ead(trades, value, collateral)
        assert ead == pytest.approx(1.4 * (replacement + factor * add_on), rel=1e-12)
        assert parts == {"replacement cost": replacement, "add-on, interest rates": 0.0,
                         "add-on, FX": pytest.approx(add_on, rel=1e-12), "multiplier": pytest.approx(factor, rel=1e-12)}
    # the same netting set in millions of euros gives the EAD in millions: nothing depends on the unit of account
    in_millions = [dict(trade, notional=trade["notional"] / 1e6) for trade in trades]
    assert sa_ccr_ead(in_millions, -0.1)[0] == pytest.approx(sa_ccr_ead(trades, -1e5)[0] / 1e6, rel=1e-12)
    # a forward settling in two days counts as ten business days: maturity factor sqrt(10 / 250) = 0.2
    two_days = {"kind": "fx", "notional": 1e6, "maturity": 2 / 250, "delta": 1}
    assert sa_ccr_ead([two_days])[0] == pytest.approx(1.4 * 0.04 * 1e6 * 0.2, rel=1e-12)
