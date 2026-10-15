"""
Pricing and interest rate shocks for the small bank portfolio of notebook 05.

- Zero curves: continuously compounded zero rates at fixed tenors, linear in the tenor and flat beyond the ends.
  Because the portfolio keeps a constant maturity, its cash-flow times never change, so the interpolation is a fixed
  matrix and thousands of scenario curves are revalued with one matrix product.
- Instruments: a fixed-coupon bullet bond, a payer interest rate swap (single curve) and an FX forward that receives
  US dollars against euros, all valued in euros by full revaluation.
- IRRBB: the six standardised shocks of the Basel Committee (2016) and the post-shock lower bound of Commission
  Delegated Regulation (EU) 2024/856, Article 3(7); the cash flows and present value of a stylised banking book, its
  economic value of equity with a payer-swap hedge, and the change in its net interest income over one year, with a
  floor on the rates paid on non-maturity deposits.

Every function is checked against a closed-form result in tests/test_bank_products.py.
"""

import numpy as np


def interpolation_matrix(tenors, times):
    """Matrix W with W @ rates = the zero rates at `times`, interpolated linearly between `tenors`, flat outside."""
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
    """Discount factors exp(-r(t) t) at `times` for one curve (vector of rates) or many (scenarios x tenors)."""
    times = np.asarray(times, float)
    return np.exp(-(np.asarray(rates, float) @ interpolation_matrix(tenors, times).T) * times)


def bond_value(rates, tenors, notional, coupon, maturity):
    """Value of a bullet bond paying an annual `coupon` (decimal) for `maturity` whole years."""
    times = np.arange(1, maturity + 1, dtype=float)
    df = discount_factors(rates, tenors, times)
    return notional * (coupon * df.sum(axis=-1) + df[..., -1])


def par_rate(rates, tenors, maturity):
    """Annual fixed rate that gives a swap (or bond) of `maturity` years a value of par: (1 - DF(T)) / sum DF(t_i)."""
    df = discount_factors(rates, tenors, np.arange(1, maturity + 1, dtype=float))
    return (1 - df[..., -1]) / df.sum(axis=-1)


def payer_swap_value(rates, tenors, notional, fixed_rate, maturity):
    """Value of paying `fixed_rate` annually and receiving floating for `maturity` years, with one curve for
    discounting and forwarding (the floating leg is then worth 1 - DF(T) per unit of notional)."""
    df = discount_factors(rates, tenors, np.arange(1, maturity + 1, dtype=float))
    return notional * ((1 - df[..., -1]) - fixed_rate * df.sum(axis=-1))


def fx_forward_value(rates, tenors, usd_per_eur, usd_notional, strike_eur, maturity, usd_rate):
    """Value in euros of receiving `usd_notional` US dollars against paying `strike_eur` euros at `maturity` years.
    The US dollar rate is a constant `usd_rate`: the portfolio has no US dollar curve."""
    df_eur = discount_factors(rates, tenors, [maturity])[..., 0]
    return usd_notional * np.exp(-usd_rate * maturity) / np.asarray(usd_per_eur, float) - strike_eur * df_eur


def fx_forward_strike(rates, tenors, usd_per_eur, usd_notional, maturity, usd_rate):
    """Euro amount that gives the FX forward a value of zero at inception (covered interest parity)."""
    df_eur = discount_factors(rates, tenors, [maturity])[..., 0]
    return usd_notional * np.exp(-usd_rate * maturity) / (usd_per_eur * df_eur)


EUR_SHOCK_SIZES_BP = {"parallel": 200, "short": 250, "long": 100}   # Basel Committee (2016), Annex 2, euro


def supervisory_shocks(times, sizes=EUR_SHOCK_SIZES_BP):
    """The six standardised shocks (decimal rate changes) at maturities `times` in years: parallel up and down,
    steepener, flattener, short rates up and down. Short shocks fade as exp(-t/4), long shocks grow as 1 - exp(-t/4)."""
    times = np.asarray(times, float)
    short = sizes["short"] / 1e4 * np.exp(-times / 4)
    long = sizes["long"] / 1e4 * (1 - np.exp(-times / 4))
    parallel = sizes["parallel"] / 1e4 * np.ones_like(times)
    return {"parallel up": parallel, "parallel down": -parallel,
            "steepener": -0.65 * np.abs(short) + 0.9 * np.abs(long),
            "flattener": 0.8 * np.abs(short) - 0.6 * np.abs(long),
            "short rates up": short, "short rates down": -short}


def eba_lower_bound(times):
    """Post-shock lower bound of Delegated Regulation (EU) 2024/856, Article 3(7), drafted by the EBA: -150 bp at
    maturity 0, rising by 3 bp a year to 0 at 50 years."""
    return np.minimum(-0.015 + 0.0003 * np.asarray(times, float), 0.0)


def shocked_rates(base, times, shock):
    """Shocked zero rates with the post-shock lower bound. Where the observed rate is already below the bound, the
    observed rate is the bound (Article 3(7)), so the bound never raises a rate."""
    base = np.asarray(base, float)
    return np.maximum(base + shock, np.minimum(eba_lower_bound(times), base))


def shocked_curve(base_rate, scenario, sizes=EUR_SHOCK_SIZES_BP):
    """The zero curve after one of the six supervisory shocks, with the post-shock lower bound, as a function of the
    maturity like `base_rate`."""
    return lambda t: shocked_rates(base_rate(t), t, supervisory_shocks(t, sizes)[scenario])


def banking_book_cash_flows(item):
    """Times (years) and amounts of an item's principal and interest, paid once a year. `kind` is "bullet" (interest
    every year and the principal at `years`; a maturity that is not a whole number of years ends with a shorter
    period that earns interest in proportion to its length, so a 1.5-year item pays a coupon at 1 and half a coupon
    with the principal at 1.5; repaid at once when `years` is zero), "annuity" (level payments over `years` whole
    years) or "spread" (principal repaid in equal parts over `years` whole years, the behavioural profile of core
    non-maturity deposits). A maturity the schedule cannot represent raises ValueError instead of giving a wrong
    schedule."""
    amount, rate, years, kind = item["amount"], item["rate"], item["years"], item["kind"]
    if kind not in ("bullet", "annuity", "spread"):
        raise ValueError(f"unknown kind of item: {kind}")
    if years < 0:
        raise ValueError(f"negative maturity: {years}")
    if kind == "bullet":
        if years == 0:
            return np.array([0.0]), np.array([float(amount)])
        times = np.append(np.arange(1, np.ceil(years), dtype=float), float(years))   # whole years, then maturity
        flows = amount * rate * np.diff(np.r_[0.0, times])                            # interest for each period
        flows[-1] += amount
        return times, flows
    if years < 1 or years != int(years):
        raise ValueError(f"an item of kind {kind} needs a whole number of years, at least one: {years}")
    times = np.arange(1, int(years) + 1, dtype=float)
    if kind == "annuity":
        payment = amount * rate / (1 - (1 + rate) ** -years) if rate else amount / years
        return times, np.full(len(times), payment)
    return times, amount / years + amount * (1 - (times - 1) / years) * rate


def present_value(items, rate_at):
    """Present value of a dict of banking-book items, discounted at the continuously compounded zero rates
    rate_at(times)."""
    total = 0.0
    for item in items.values():
        times, flows = banking_book_cash_flows(item)
        total += float((flows * np.exp(-rate_at(times) * times)).sum())
    return total


def economic_value(assets, liabilities, rate_at, tenors, hedge_notional=0.0, hedge_rate=0.0, hedge_maturity=1):
    """Economic value of equity: the present value of the assets minus that of the liabilities (equity itself
    excluded), plus a banking-book swap that pays `hedge_rate` and receives floating, valued on the curve
    rate_at(tenors)."""
    hedge = payer_swap_value(rate_at(tenors), tenors, hedge_notional, hedge_rate, hedge_maturity)
    return present_value(assets, rate_at) - present_value(liabilities, rate_at) + hedge


def nii_change(assets, liabilities, shock, pass_through, deposit_floor=0.0, hedge_notional=0.0, hedge_reset=0.25):
    """Change in net interest income over one year, with a constant balance sheet, after a parallel `shock` (decimal).
    Items that reprice within the year (bullets of up to one year) earn the shock for the rest of it. Non-maturity
    deposits (items with non_maturity=True) pass on `pass_through` of the shock at once, but their rate does not fall
    below `deposit_floor`, and a rate already below the floor is kept (None: no floor). A hedge that pays fixed and
    receives floating earns the shock after its first reset, at `hedge_reset` years."""
    change = hedge_notional * shock * (1 - hedge_reset)
    for sign, items in [(1, assets), (-1, liabilities)]:
        for item in items.values():
            if item.get("non_maturity"):
                new_rate = item["rate"] + pass_through * shock
                if deposit_floor is not None:
                    new_rate = max(new_rate, min(deposit_floor, item["rate"]))
                change += sign * item["amount"] * (new_rate - item["rate"])
            elif item["kind"] == "bullet" and item["years"] <= 1:
                change += sign * item["amount"] * shock * (1 - item["years"])
    return change
