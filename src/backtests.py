"""
Statistical tests for forecasts and risk models, shared by notebooks 03 and 04.

- Coverage of quantile forecasts and VaR-type limits: Kupiec's proportion-of-failures test, the exact binomial
  test, Christoffersen's independence test and the Basel traffic light (Kupiec, 1995; Christoffersen, 1998;
  Basel Committee on Banking Supervision, 1996).
- Expected Shortfall: the Z2 test of Acerbi and Szekely (2014).
- Forecast accuracy: the Diebold-Mariano and Giacomini-White tests on daily loss differences.

Each test is checked against a reference in tests/test_backtests.py.
"""

import numpy as np
import statsmodels.api as sm
from scipy import stats
from scipy.special import xlogy


def kupiec(hits, p):
    """Proportion-of-failures test: is the hit rate equal to p? Returns (LR statistic, p-value), chi-squared(1)."""
    hits = np.asarray(hits, dtype=int)
    n, x = len(hits), hits.sum()
    lr = -2 * (xlogy(n - x, 1 - p) + xlogy(x, p) - xlogy(n - x, 1 - x / n) - xlogy(x, x / n))
    return lr, stats.chi2.sf(lr, 1)


def christoffersen(hits):
    """Independence test: does a hit on one day change the chance of a hit on the next? Returns (LR, p-value)."""
    hits = np.asarray(hits, dtype=int)
    a, b = hits[:-1], hits[1:]
    n00, n01 = np.sum((a == 0) & (b == 0)), np.sum((a == 0) & (b == 1))
    n10, n11 = np.sum((a == 1) & (b == 0)), np.sum((a == 1) & (b == 1))
    p01 = n01 / (n00 + n01) if n00 + n01 else 0.0
    p11 = n11 / (n10 + n11) if n10 + n11 else 0.0
    p = (n01 + n11) / len(b)
    lr = -2 * (xlogy(n00 + n10, 1 - p) + xlogy(n01 + n11, p)
               - xlogy(n00, 1 - p01) - xlogy(n01, p01) - xlogy(n10, 1 - p11) - xlogy(n11, p11))
    return lr, stats.chi2.sf(lr, 1)


def traffic_light(x, n, p):
    """Basel traffic light for any level: the zone follows the binomial probability of seeing at most x hits."""
    cumulative = stats.binom.cdf(x, n, p)
    return "green" if cumulative < 0.95 else ("yellow" if cumulative < 0.9999 else "red")


def backtest(hits, p, min_days_independence=100):
    """All tests for one sequence of daily hits. The exact binomial test is valid for any sample size; Kupiec's
    test is its large-sample version; Christoffersen's test is run only on samples of min_days_independence or more."""
    hits = np.asarray(hits, dtype=int)
    n, x = len(hits), int(hits.sum())
    lr_uc, p_uc = kupiec(hits, p)
    result = {"days": n, "hits": x, "hit rate": x / n, "expected": p,
              "binomial p": stats.binomtest(x, n, p).pvalue, "Kupiec p": p_uc,
              "Christoffersen p": np.nan, "conditional coverage p": np.nan, "zone": traffic_light(x, n, p)}
    if n >= min_days_independence:
        lr_ind, p_ind = christoffersen(hits)
        result["Christoffersen p"], result["conditional coverage p"] = p_ind, stats.chi2.sf(lr_uc + lr_ind, 2)
    return result


def acerbi_szekely_z2(flows, limit, es, samples, alpha, n_sim=2000, seed=42):
    """Z2 test of Expected Shortfall (Acerbi & Szekely, 2014): Z2 = mean(X_t I_t / (alpha ES_t)) + 1, with X_t the
    outcome, I_t = 1 when the loss exceeds the limit (VaR or CFaR), and ES_t and the limit as positive losses.
    Z2 is about 0 when ES is right and negative when it understates the losses. The p-value simulates each day's
    outcome from that day's forecast distribution, given as a sample in `samples`. Returns (Z2, p-value)."""
    flows, limit, es = (np.asarray(v, dtype=float) for v in (flows, limit, es))
    scale = np.divide(1.0, alpha * es, out=np.zeros_like(es), where=es > 0)        # a day without exposure adds 0
    z2 = np.mean(flows * (flows < -limit) * scale) + 1
    rng = np.random.default_rng(seed)
    sims = np.column_stack([rng.choice(s, size=n_sim) for s in samples])           # n_sim simulations x days
    z2_sim = np.mean(sims * (sims < -limit) * scale, axis=1) + 1
    return z2, np.mean(z2_sim <= z2)


def diebold_mariano(loss_difference, max_lags=7):
    """Diebold-Mariano test of equal accuracy on a series of loss differences (A minus B; negative: A better),
    with Newey-West errors over max_lags days. Returns (statistic, p-value)."""
    d = np.asarray(loss_difference, dtype=float)
    fit = sm.OLS(d, np.ones(len(d))).fit(cov_type="HAC", cov_kwds={"maxlags": max_lags})
    return fit.tvalues[0], fit.pvalues[0]


def giacomini_white(loss_difference):
    """Giacomini-White conditional test of equal accuracy, with a constant and yesterday's loss difference as
    instruments: the statistic is n times the uncentred R-squared of regressing 1 on the instruments times the loss
    difference. Returns (statistic, p-value), chi-squared(2)."""
    d = np.asarray(loss_difference, dtype=float)
    z = np.column_stack([np.ones(len(d) - 1), d[:-1]]) * d[1:, None]
    statistic = len(z) * sm.OLS(np.ones(len(z)), z).fit().rsquared       # no constant: statsmodels uses uncentred R²
    return statistic, 1 - stats.chi2.cdf(statistic, df=2)
