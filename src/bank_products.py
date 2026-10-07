"""
Pricing and interest rate shocks for the small bank portfolio of notebook 05.

- Zero curves: continuously compounded zero rates at fixed tenors, linear in the tenor and flat beyond the ends.
  Because the portfolio keeps a constant maturity, its cash-flow times never change, so the interpolation is a fixed
  matrix and thousands of scenario curves are revalued with one matrix product.
- Instruments: a fixed-coupon bullet bond, a payer interest rate swap (single curve) and an FX forward that receives
  US dollars against euros, all valued in euros by full revaluation.
- IRRBB: the six standardised shocks of the Basel Committee (2016) and the post-shock lower bound of the EBA
  guidelines (EBA/GL/2022/14).

Every function is checked against a closed-form result in tests/test_bank_products.py.
"""

import numpy as np


def interpolation_matrix(tenors, times):
    # Matrix W with W @ rates = the zero rates at `times`, interpolated linearly between `tenors`, flat outside.
    tenors, times = np.asarray(tenors, float), np.asarray(times, float)
    w = np.zeros((len(times), len(tenors)))
    for i, t in enumerate(times):
        if t <= tenors[0]:
            w[i, 0] = 1.0
        elif t >= tenors[-1]:
            w[i, -1] = 1.0
        else:
            k = np.searchsorted(tenors, t) - 1
            share = (t - tenors[k]) / (tenors[k + 1] - tenors[k])
            w[i, k], w[i, k + 1] = 1 - share, share
    return w


def discount_factors(rates, tenors, times):
    # Discount factors exp(-r(t) t) at `times` for one curve (vector of rates) or many (scenarios x tenors).
    times = np.asarray(times, float)
    return np.exp(-(np.asarray(rates, float) @ interpolation_matrix(tenors, times).T) * times)


def bond_value(rates, tenors, notional, coupon, maturity):
    # Value of a bullet bond paying an annual `coupon` (decimal) for `maturity` whole years.
    times = np.arange(1, maturity + 1, dtype=float)
    df = discount_factors(rates, tenors, times)
    return notional * (coupon * df.sum(axis=-1) + df[..., -1])


def par_rate(rates, tenors, maturity):
    # Annual fixed rate that gives a swap (or bond) of `maturity` years a value of par: (1 - DF(T)) / sum DF(t_i).
    df = discount_factors(rates, tenors, np.arange(1, maturity + 1, dtype=float))
    return (1 - df[..., -1]) / df.sum(axis=-1)


def payer_swap_value(rates, tenors, notional, fixed_rate, maturity):
    # Value of paying `fixed_rate` annually and receiving floating for `maturity` years, with one curve for
    # discounting and forwarding (the floating leg is then worth 1 - DF(T) per unit of notional).
    df = discount_factors(rates, tenors, np.arange(1, maturity + 1, dtype=float))
    return notional * ((1 - df[..., -1]) - fixed_rate * df.sum(axis=-1))


def fx_forward_value(rates, tenors, usd_per_eur, usd_notional, strike_eur, maturity, usd_rate):
    # Value in euros of receiving `usd_notional` US dollars against paying `strike_eur` euros at `maturity` years.
    # The US dollar rate is a constant `usd_rate`: the portfolio has no US dollar curve.
    df_eur = discount_factors(rates, tenors, [maturity])[..., 0]
    return usd_notional * np.exp(-usd_rate * maturity) / np.asarray(usd_per_eur, float) - strike_eur * df_eur


def fx_forward_strike(rates, tenors, usd_per_eur, usd_notional, maturity, usd_rate):
    # Euro amount that gives the FX forward a value of zero at inception (covered interest parity).
    df_eur = discount_factors(rates, tenors, [maturity])[..., 0]
    return usd_notional * np.exp(-usd_rate * maturity) / (usd_per_eur * df_eur)


EUR_SHOCK_SIZES_BP = {"parallel": 200, "short": 250, "long": 100}   # Basel Committee (2016), Annex 2, euro


def supervisory_shocks(times, sizes=EUR_SHOCK_SIZES_BP):
    # The six standardised shocks (decimal rate changes) at maturities `times` in years: parallel up and down,
    # steepener, flattener, short rates up and down. Short shocks fade as exp(-t/4), long shocks grow as 1 - exp(-t/4).
    times = np.asarray(times, float)
    short = sizes["short"] / 1e4 * np.exp(-times / 4)
    long = sizes["long"] / 1e4 * (1 - np.exp(-times / 4))
    parallel = sizes["parallel"] / 1e4 * np.ones_like(times)
    return {"parallel up": parallel, "parallel down": -parallel,
            "steepener": -0.65 * np.abs(short) + 0.9 * np.abs(long),
            "flattener": 0.8 * np.abs(short) - 0.6 * np.abs(long),
            "short rates up": short, "short rates down": -short}


def eba_lower_bound(times):
    # Post-shock lower bound of EBA/GL/2022/14: -150 bp at maturity 0, rising by 3 bp a year to 0 at 50 years.
    return np.minimum(-0.015 + 0.0003 * np.asarray(times, float), 0.0)


def shocked_rates(base, times, shock):
    # Shocked zero rates with the EBA lower bound; where the observed rate is already below the bound, the observed
    # rate is the bound, so the bound never raises a rate.
    base = np.asarray(base, float)
    return np.maximum(base + shock, np.minimum(eba_lower_bound(times), base))
