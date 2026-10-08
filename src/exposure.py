"""
Counterparty exposure of the bank portfolio's derivatives (notebook 05).

- Rates: a one-factor Hull-White model fitted exactly to today's euro zero curve, simulated exactly on a time grid.
- FX: the euro value of one US dollar, lognormal, drifting at the euro short rate minus a constant US dollar rate
  (its risk-neutral drift), correlated with the rate.
- Values on every path and date of a payer interest rate swap and of an FX forward, exposure profiles (EE, PFE),
  effective EPE as in the Basel internal model method, netting and variation margin with a margin period of risk.
- The regulatory benchmark: the standardised approach SA-CCR (Basel Committee on Banking Supervision, 2014).

Each function is checked in tests/test_exposure.py: the model reproduces today's curve, discounted prices are
martingales, trades at par are worth zero today, and SA-CCR matches a calculation by hand.
"""

import numpy as np

from bank_products import discount_factors


class HullWhite:
    """One-factor Hull-White model, dr = (theta(t) - a r) dt + sigma dW, fitted to an initial zero curve given as
    continuously compounded rates at `tenors`."""

    def __init__(self, rates, tenors, a, sigma):
        self.rates, self.tenors = np.asarray(rates, float), np.asarray(tenors, float)
        self.a, self.sigma = float(a), float(sigma)

    def p0(self, t):
        """Today's discount factors P(0, t)."""
        return discount_factors(self.rates, self.tenors, np.atleast_1d(np.asarray(t, float)))

    def f0(self, t, h=1e-4):
        """Today's instantaneous forward rates f(0, t) = -d ln P(0, t) / dt, by central differences."""
        t = np.atleast_1d(np.asarray(t, float))
        lo, hi = np.maximum(t - h, 0.0), t + h
        return -(np.log(self.p0(hi)) - np.log(self.p0(lo))) / (hi - lo)

    def b(self, t, maturity):
        return (1 - np.exp(-self.a * (maturity - t))) / self.a

    def zero_bond(self, t, maturity, r):
        """P(t, maturity) on each path, given the short rate r at time t (one value per path)."""
        b = self.b(t, maturity)
        log_a = (np.log(self.p0(maturity)[0] / self.p0(t)[0]) + b * self.f0(t)[0]
                 - self.sigma ** 2 / (4 * self.a) * (1 - np.exp(-2 * self.a * t)) * b ** 2)
        return np.exp(log_a - b * np.asarray(r, float))

    def simulate(self, times, normals):
        """Short rates on `times` (the first is 0) from standard normals of shape (paths, len(times) - 1), using the
        exact transition of the Ornstein-Uhlenbeck part and the deterministic shift that fits today's curve."""
        x = np.zeros((normals.shape[0], len(times)))
        for k in range(1, len(times)):
            dt = times[k] - times[k - 1]
            x[:, k] = (x[:, k - 1] * np.exp(-self.a * dt)
                       + self.sigma * np.sqrt((1 - np.exp(-2 * self.a * dt)) / (2 * self.a)) * normals[:, k - 1])
        shift = self.f0(times) + self.sigma ** 2 / (2 * self.a ** 2) * (1 - np.exp(-self.a * np.asarray(times))) ** 2
        return x + shift


def discount_along_paths(times, short_rates):
    """Bank-account discount factor exp(-integral of r) from 0 to each date, by the trapezoid rule."""
    integral = np.cumsum(0.5 * (short_rates[:, 1:] + short_rates[:, :-1]) * np.diff(times), axis=1)
    return np.hstack([np.ones((short_rates.shape[0], 1)), np.exp(-integral)])


def simulate_fx(times, short_rates, x0, foreign_rate, sigma, normals):
    """Euro value of one unit of foreign currency on each path: lognormal, with drift equal to the euro short rate
    (averaged over the step, as in discount_along_paths) minus the constant foreign rate."""
    x = np.empty_like(short_rates)
    x[:, 0] = x0
    for k in range(1, len(times)):
        dt = times[k] - times[k - 1]
        drift = 0.5 * (short_rates[:, k - 1] + short_rates[:, k]) - foreign_rate - 0.5 * sigma ** 2
        x[:, k] = x[:, k - 1] * np.exp(drift * dt + sigma * np.sqrt(dt) * normals[:, k - 1])
    return x


def payer_swap_paths(model, times, short_rates, notional, fixed_rate, maturity):
    """Value of a swap paying `fixed_rate` annually and receiving an annual floating rate (one curve) on each path
    and date, after that date's payment and zero from maturity, together with the net cash flows received on the
    payment dates. Each floating coupon is fixed at the start of its year, so between resets the floating leg is
    worth (1 + L) P(t, next payment) - P(t, maturity). Payment dates must lie on the time grid."""
    payments = np.arange(1, maturity + 1, dtype=float)
    values, flows = np.zeros_like(short_rates), np.zeros_like(short_rates)
    coupon = np.full(short_rates.shape[0], 1 / model.p0(1.0)[0] - 1)          # the first coupon, fixed today
    for k, t in enumerate(times):
        r = short_rates[:, k]
        if k > 0 and np.isclose(t, round(t)) and t <= maturity + 1e-9:        # a payment date
            flows[:, k] = notional * (coupon - fixed_rate)
            if t < maturity - 1e-9:
                coupon = 1 / model.zero_bond(t, t + 1, r) - 1                   # fix the next coupon
        if t >= maturity - 1e-9:
            continue
        remaining = payments[payments > t + 1e-9]
        bonds = np.column_stack([model.zero_bond(t, T, r) for T in remaining])
        values[:, k] = notional * ((1 + coupon) * bonds[:, 0] - bonds[:, -1] - fixed_rate * bonds.sum(axis=1))
    return values, flows


def fx_forward_paths(model, times, short_rates, fx_eur_per_unit, foreign_notional, strike_eur, maturity, foreign_rate):
    """Value in euros of receiving `foreign_notional` units of foreign currency against `strike_eur` euros at
    `maturity`, on each path and date and zero from maturity, together with the settlement cash flow at maturity.
    The maturity must lie on the time grid."""
    values, flows = np.zeros_like(short_rates), np.zeros_like(short_rates)
    for k, t in enumerate(times):
        if np.isclose(t, maturity):
            flows[:, k] = foreign_notional * fx_eur_per_unit[:, k] - strike_eur
        if t >= maturity - 1e-9:
            continue
        euro_bond = model.zero_bond(t, maturity, short_rates[:, k])
        values[:, k] = (foreign_notional * fx_eur_per_unit[:, k] * np.exp(-foreign_rate * (maturity - t))
                        - strike_eur * euro_bond)
    return values, flows


def collateralised_values(values, cash_flows=None, mpor_steps=1):
    """Value left uncovered under variation margin with no threshold: the change over the margin period of risk
    (`mpor_steps` steps of the grid) in the value plus the cash flows received in that period, so that a payment
    is not mistaken for a loss. The first steps, before any margin call, keep the full value."""
    gains = values if cash_flows is None else values + np.cumsum(cash_flows, axis=1)
    out = values.copy()
    out[:, mpor_steps:] = gains[:, mpor_steps:] - gains[:, :-mpor_steps]
    return out


def exposure_profile(values, quantile=0.975):
    """Expected exposure and potential future exposure (a quantile of the exposure) at each date."""
    exposure = np.maximum(values, 0.0)
    return exposure.mean(axis=0), np.quantile(exposure, quantile, axis=0)


def expected_positive_exposure(times, expected_exposure, horizon=1.0):
    """EPE: the time average of the expected exposure over [0, horizon]."""
    keep = times <= horizon + 1e-9
    t, ee = times[keep], expected_exposure[keep]
    return float(np.sum(ee[:-1] * np.diff(t)) / (t[-1] - t[0]))


def effective_epe(times, expected_exposure, horizon=1.0):
    """Effective EPE of the internal model method: the time average over [0, horizon] of the effective expected
    exposure, the running maximum of EE."""
    keep = times <= horizon + 1e-9
    t, effective = times[keep], np.maximum.accumulate(expected_exposure[keep])
    return float(np.sum(effective[:-1] * np.diff(t)) / (t[-1] - t[0]))


def supervisory_duration(start, end):
    return (np.exp(-0.05 * start) - np.exp(-0.05 * end)) / 0.05


def sa_ccr_ead(trades, value=0.0, collateral=0.0, margined=False, mpor_days=10, alpha=1.4):
    """Exposure at default under SA-CCR for a netting set of interest rate swaps in one currency and FX forwards in
    one currency pair. Each trade is a dict: kind "ir" with notional, start, end (years) and delta (+1 or -1), or
    kind "fx" with notional (in the domestic currency), maturity and delta. Returns the EAD and its parts."""
    ir = np.zeros(3)
    fx_effective = 0.0
    for trade in trades:
        maturity = trade["end"] if trade["kind"] == "ir" else trade["maturity"]
        factor = 1.5 * np.sqrt(mpor_days / 250) if margined else np.sqrt(min(max(maturity, 10 / 250), 1.0))
        if trade["kind"] == "ir":
            bucket = 0 if trade["end"] < 1 else (1 if trade["end"] <= 5 else 2)
            ir[bucket] += trade["delta"] * trade["notional"] * supervisory_duration(trade["start"], trade["end"]) * factor
        else:
            fx_effective += trade["delta"] * trade["notional"] * factor
    d1, d2, d3 = ir
    addon_ir = 0.005 * np.sqrt(d1 ** 2 + d2 ** 2 + d3 ** 2 + 1.4 * d1 * d2 + 1.4 * d2 * d3 + 0.6 * d1 * d3)
    addon_fx = 0.04 * abs(fx_effective)
    addon = addon_ir + addon_fx
    replacement = max(value - collateral, 0.0)
    multiplier = min(1.0, 0.05 + 0.95 * np.exp((value - collateral) / (2 * 0.95 * addon))) if addon > 0 else 1.0
    ead = alpha * (replacement + multiplier * addon)
    return ead, {"replacement cost": replacement, "add-on, interest rates": addon_ir, "add-on, FX": addon_fx,
                 "multiplier": multiplier}
