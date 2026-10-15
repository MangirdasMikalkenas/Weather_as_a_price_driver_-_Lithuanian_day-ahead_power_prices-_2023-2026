"""
Statistical tests for forecasts and risk models, shared by notebooks 03 and 04.

- Coverage of quantile forecasts and VaR-type limits: Kupiec's proportion-of-failures test, the exact binomial
  test, Christoffersen's independence test and the Basel traffic light, applied as Basel-style binomial zones at
  other levels and sample sizes (Kupiec, 1995; Christoffersen, 1998; Basel Committee on Banking Supervision, 1996),
  and McNemar's paired test of two models' exceptions on the same days.
- Expected Shortfall: the Z2 test of Acerbi and Szekely (2014).
- Forecast accuracy: the Diebold-Mariano and Giacomini-White tests on daily loss differences, and a version of the
  Diebold-Mariano test for short samples (a month of days) with fixed-smoothing critical values.
- Historical-simulation VaR and ES with an explicit quantile convention, EWMA volatilities and volatility-scaled
  (filtered) historical scenarios, and the zones of the FRTB P&L attribution test (Basel Committee, MAR32).

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
    """Zones built like the Basel traffic light: green while the binomial probability of seeing at most x hits is
    below 95%, red from 99.99%, yellow in between. At 99% over 250 days these are the Basel zones (0-4 green, 5-9
    yellow, 10 or more red); at other levels or sample sizes they are Basel-style zones, not a regulatory test."""
    cumulative = stats.binom.cdf(x, n, p)
    return "green" if cumulative < 0.95 else ("yellow" if cumulative < 0.9999 else "red")


def paired_exceptions(hits_a, hits_b):
    """Do two VaR models backtested on the same days have the same exception rate? McNemar's exact test: only the days
    on which exactly one of the two has an exception count, and under the null each such day is equally likely to
    belong to either model. Like the binomial test, it treats days as independent. Returns (days with an exception of
    A only, days with an exception of B only, two-sided p-value)."""
    a, b = np.asarray(hits_a, dtype=bool), np.asarray(hits_b, dtype=bool)
    only_a, only_b = int(np.sum(a & ~b)), int(np.sum(b & ~a))
    p = stats.binomtest(only_a, only_a + only_b, 0.5).pvalue if only_a + only_b else 1.0
    return only_a, only_b, p


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


def diebold_mariano_small_sample(loss_difference, b=None):
    """Diebold-Mariano test for short samples: the long-run variance is the equal-weighted cosine (EWC) estimator,
    the mean of the squares of the first b cosine transforms of the demeaned loss differences, and the statistic is
    compared with a t distribution with b degrees of freedom (fixed-smoothing asymptotics). With the Newey-West
    variance and normal critical values, a 26-day sample rejects a true null about three times as often as the nominal
    5% (tests/test_backtests.py). b defaults to the rule of Lazarus, Lewis, Stock and Watson (2018), 0.4 n^(2/3)
    rounded down; see also Coroneo and Iacone (2020). Returns (statistic, p-value, b)."""
    d = np.asarray(loss_difference, dtype=float)
    n = len(d)
    b = b or max(1, int(np.floor(0.4 * n ** (2 / 3))))
    t = np.arange(1, n + 1)
    cosines = np.sqrt(2 / n) * np.cos(np.pi * np.outer(np.arange(1, b + 1), t - 0.5) / n)
    long_run_variance = np.mean((cosines @ (d - d.mean())) ** 2)
    statistic = np.sqrt(n) * d.mean() / np.sqrt(long_run_variance)
    return statistic, 2 * stats.t.sf(abs(statistic), b), b


def giacomini_white(loss_difference):
    """Giacomini-White conditional test of equal accuracy, with a constant and yesterday's loss difference as
    instruments: the statistic is n times the uncentred R-squared of regressing 1 on the instruments times the loss
    difference. Returns (statistic, p-value), chi-squared(2)."""
    d = np.asarray(loss_difference, dtype=float)
    z = np.column_stack([np.ones(len(d) - 1), d[:-1]]) * d[1:, None]
    statistic = len(z) * sm.OLS(np.ones(len(z)), z).fit().rsquared       # no constant: statsmodels uses uncentred R²
    return statistic, 1 - stats.chi2.cdf(statistic, df=2)


def var_es(pnl, var_level=0.99, es_level=0.975, method="linear"):
    """Historical-simulation VaR and Expected Shortfall of a P&L sample, both as positive losses. `method` is the
    numpy quantile convention: "linear" (numpy's default) interpolates between neighbouring outcomes, "inverted_cdf"
    takes an observed outcome; with 250 outcomes the 99% VaR is then the third-worst loss. ES is the mean of the
    outcomes at or below the (1 - es_level) quantile. Returns (VaR, ES)."""
    pnl = np.asarray(pnl, dtype=float)
    var = -np.quantile(pnl, 1 - var_level, method=method)
    cutoff = np.quantile(pnl, 1 - es_level, method=method)
    return var, -pnl[pnl <= cutoff].mean()


def ewma_volatility(changes, lam=0.94, warmup=30, floor=1e-16):
    """RiskMetrics (EWMA) volatility of each column of `changes`. Row i is the forecast for row i from the rows before
    it: sigma2[i] = lam sigma2[i-1] + (1 - lam) changes[i-1]^2, started at the variance of the first `warmup` rows and
    kept at or above `floor`, so that a series that stops moving cannot be divided by zero. Returns an array of the
    same shape as `changes`."""
    x = np.asarray(changes, dtype=float)
    flat = x.reshape(len(x), -1)
    var = np.empty_like(flat)
    var[0] = flat[:warmup].var(axis=0)
    for i in range(1, len(flat)):
        var[i] = lam * var[i - 1] + (1 - lam) * flat[i - 1] ** 2
    return np.sqrt(np.maximum(var, floor)).reshape(x.shape)


def volatility_scaled(changes, sigma, rows, now):
    """Filtered historical simulation (Hull & White, 1998): the past changes in `rows`, each rescaled from the
    volatility of its own day to the volatility forecast for row `now` (sigma as returned by ewma_volatility)."""
    return np.asarray(changes)[rows] * np.asarray(sigma)[now] / np.asarray(sigma)[rows]


PLA_GREEN = {"spearman": 0.80, "ks": 0.09}    # Basel Committee, MAR32: P&L attribution test, green zone
PLA_RED = {"spearman": 0.70, "ks": 0.12}      # red zone beyond these; amber in between


def pla_zone(spearman, ks, green=PLA_GREEN, red=PLA_RED):
    """Zone of the P&L attribution test (MAR32): green when the Spearman correlation of hypothetical and
    risk-theoretical P&L is above 0.80 and their Kolmogorov-Smirnov distance below 0.09; red when the correlation is
    below 0.70 or the distance above 0.12; amber otherwise."""
    if spearman > green["spearman"] and ks < green["ks"]:
        return "green"
    return "red" if spearman < red["spearman"] or ks > red["ks"] else "amber"
