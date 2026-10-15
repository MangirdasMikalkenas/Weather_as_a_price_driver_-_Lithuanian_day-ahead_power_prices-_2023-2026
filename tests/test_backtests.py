"""The statistical tests of src/backtests.py, each checked against an independent reference."""

import numpy as np
import pytest
from scipy import stats
from scipy.signal import lfilter
from statsmodels.stats.contingency_tables import mcnemar

from backtests import (acerbi_szekely_z2, backtest, christoffersen, diebold_mariano, diebold_mariano_small_sample,
                       ewma_volatility, giacomini_white, kupiec, paired_exceptions, pla_zone, traffic_light, var_es,
                       volatility_scaled)


def hits_with(x, n):
    return np.r_[np.ones(x, dtype=int), np.zeros(n - x, dtype=int)]


def test_traffic_light_reproduces_the_basel_table():
    # Basel Committee (1996): 250 days at 99% -> 0-4 exceptions green, 5-9 yellow, 10 or more red
    zones = [traffic_light(x, 250, 0.01) for x in range(13)]
    assert zones == ["green"] * 5 + ["yellow"] * 5 + ["red"] * 3


@pytest.mark.parametrize("x", [35, 50, 65])
def test_kupiec_agrees_with_the_exact_binomial_test_in_large_samples(x):
    _, p_kupiec = kupiec(hits_with(x, 1000), 0.05)
    assert p_kupiec == pytest.approx(stats.binomtest(x, 1000, 0.05).pvalue, abs=0.01)


def test_kupiec_misleads_in_small_samples_which_is_why_the_exact_test_is_used():
    # 26 days, a 10% tail and no hits: Kupiec rejects (p = 0.019), the exact test does not (p = 0.104)
    _, p_kupiec = kupiec(np.zeros(26, dtype=int), 0.10)
    assert p_kupiec == pytest.approx(0.019, abs=0.001)
    assert stats.binomtest(0, 26, 0.10).pvalue == pytest.approx(0.104, abs=0.001)


@pytest.mark.parametrize("hits", [np.array([0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0]),
                                  np.array([0, 0, 1, 0, 0, 1, 1])])       # as many 0-0 as 0-1 transitions
def test_christoffersen_matches_a_markov_likelihood_written_out_by_hand(hits):
    pairs = list(zip(hits[:-1], hits[1:]))
    p01 = sum(1 for a, b in pairs if a == 0 and b == 1) / sum(1 for a, _ in pairs if a == 0)
    p11 = sum(1 for a, b in pairs if a == 1 and b == 1) / sum(1 for a, _ in pairs if a == 1)
    p = sum(b for _, b in pairs) / len(pairs)
    loglik_markov = sum(np.log((p11 if a else p01) if b else (1 - p11 if a else 1 - p01)) for a, b in pairs)
    loglik_independent = sum(np.log(p if b else 1 - p) for _, b in pairs)
    lr, _ = christoffersen(hits)
    assert lr == pytest.approx(2 * (loglik_markov - loglik_independent))


@pytest.mark.parametrize("hits", [np.zeros(250, dtype=int), np.ones(250, dtype=int)])
def test_christoffersen_has_nothing_to_test_without_both_hits_and_misses(hits):
    # a year without exceptions (or with nothing else) has no transition to compare: LR 0 and p = 1, not 0 / 0
    assert christoffersen(hits) == (0.0, 1.0)


def markov_hits(n, p01, p11, rng):
    hits = np.zeros(n, dtype=int)
    for t in range(1, n):
        hits[t] = rng.random() < (p11 if hits[t - 1] else p01)
    return hits


def test_christoffersen_has_the_right_size_and_detects_clustering():
    rng = np.random.default_rng(0)
    size = np.mean([christoffersen((rng.random(500) < 0.1).astype(int))[1] < 0.05 for _ in range(1000)])
    power = np.mean([christoffersen(markov_hits(500, 0.05, 0.5, rng))[1] < 0.05 for _ in range(200)])
    assert 0.03 <= size <= 0.07
    assert power > 0.95


def test_backtest_runs_the_independence_test_only_on_long_samples():
    assert np.isnan(backtest(hits_with(3, 26), 0.1)["Christoffersen p"])
    assert not np.isnan(backtest(hits_with(15, 150), 0.1)["Christoffersen p"])
    assert np.isnan(backtest(hits_with(5, 99), 0.05)["Christoffersen p"])           # from 100 days on
    assert not np.isnan(backtest(hits_with(5, 100), 0.05)["Christoffersen p"])


def test_backtest_reports_each_test_and_the_zone():
    # three exceptions at 99% in 250 days, two of them on consecutive days; the conditional coverage test adds the
    # Kupiec and Christoffersen statistics, chi-squared with 2 degrees of freedom (Christoffersen, 1998)
    hits = np.zeros(250, dtype=int)
    hits[[40, 41, 180]] = 1
    lr_uc, p_uc = kupiec(hits, 0.01)
    lr_ind, p_ind = christoffersen(hits)
    assert backtest(hits, 0.01) == {
        "days": 250, "hits": 3, "hit rate": 0.012, "expected": 0.01,
        "binomial p": pytest.approx(stats.binomtest(3, 250, 0.01).pvalue), "Kupiec p": pytest.approx(p_uc),
        "Christoffersen p": pytest.approx(p_ind),
        "conditional coverage p": pytest.approx(stats.chi2.sf(lr_uc + lr_ind, 2)), "zone": "green"}


def tail_forecast(sample, level):
    q = np.quantile(sample, 1 - level)
    return -q, -sample[sample <= q].mean()


def test_acerbi_szekely_is_near_zero_when_right_and_negative_when_losses_are_understated():
    rng = np.random.default_rng(1)
    days, level = 600, 0.975
    samples = [rng.normal(0, 1, 500) for _ in range(days)]
    limit, es = map(np.array, zip(*(tail_forecast(s, level) for s in samples)))
    z2_right, p_right = acerbi_szekely_z2(rng.normal(0, 1, days), limit, es, samples, alpha=1 - level)
    z2_wrong, p_wrong = acerbi_szekely_z2(rng.normal(0, 1.5, days), limit, es, samples, alpha=1 - level)
    assert abs(z2_right) < 0.35 and p_right > 0.05
    assert z2_wrong < -0.5 and p_wrong < 0.01


def test_acerbi_szekely_z2_by_hand():
    # four days at alpha = 2.5%: day 1 loses 3 against a limit of 1 and an ES of 1, so it adds -3 / (2.5% x 1) = -120;
    # day 2 gains; day 3 has no exposure (ES 0) and adds nothing; day 4 loses exactly its limit, which is not an
    # exception. Z2 = -120 / 4 + 1 = -29. When each day's outcome is certain (its sample is that outcome alone), every
    # simulated Z2 equals the observed one and the p-value, the share at or below it, is 1
    flows, limit, es = [-3, 1, -1, -2], [1, 2, 0, 2], [1, 5, 0, 4]
    assert acerbi_szekely_z2(flows, limit, es, [[flow] for flow in flows], alpha=0.025) == (-29.0, 1.0)


def test_acerbi_szekely_p_value_is_the_share_of_simulated_z2_at_or_below_the_observed():
    # day 1 (limit 1, ES 2) loses 3 or gains 2 with equal chances, and loses 3; day 2 (limit 1, ES 0.5) is forecast to
    # lose exactly its limit, never an exception, and loses nothing. At alpha = 50%, Z2 = (-3 / 1 + 0) / 2 + 1 = -0.5,
    # the simulated Z2 is -0.5 or 1 with equal chances, and p is about 0.5; the default seed gives it every time
    flows, limit, es, samples = [-3.0, 0.0], [1.0, 1.0], [2.0, 0.5], [[-3.0, 2.0], [-1.0]]
    z2, p = acerbi_szekely_z2(flows, limit, es, samples, alpha=0.5)
    assert z2 == -0.5 and p == pytest.approx(0.5, abs=0.05)
    assert [acerbi_szekely_z2(flows, limit, es, samples, alpha=0.5)[1] for _ in range(2)] == [p, p]


def test_diebold_mariano_matches_a_newey_west_statistic_computed_by_hand():
    rng = np.random.default_rng(2)
    d, lags = rng.normal(0.1, 1, 300), 7
    e, n = d - d.mean(), len(d)
    gamma = [np.sum(e[k:] * e[:n - k]) / n for k in range(lags + 1)]
    long_run_variance = gamma[0] + 2 * sum((1 - k / (lags + 1)) * gamma[k] for k in range(1, lags + 1))
    statistic, p_value = diebold_mariano(d, max_lags=lags)
    assert statistic == pytest.approx(d.mean() / np.sqrt(long_run_variance / n))
    assert p_value == pytest.approx(2 * stats.norm.sf(abs(statistic)))
    assert diebold_mariano(d) == (statistic, p_value)                    # a week of lags by default


def test_diebold_mariano_rejects_about_five_percent_of_equally_accurate_forecasts():
    rng = np.random.default_rng(3)
    size = np.mean([diebold_mariano(rng.normal(0, 1, 250))[1] < 0.05 for _ in range(1000)])
    assert 0.03 <= size <= 0.08


def test_giacomini_white_matches_the_quadratic_form_computed_by_hand():
    rng = np.random.default_rng(4)
    d = rng.normal(0.2, 1, 200)
    z = np.column_stack([np.ones(len(d) - 1), d[:-1]]) * d[1:, None]
    ones = np.ones(len(z))
    by_hand = ones @ z @ np.linalg.solve(z.T @ z, z.T @ ones)          # n times the uncentred R-squared
    statistic, p_value = giacomini_white(d)
    assert statistic == pytest.approx(by_hand)
    assert p_value == pytest.approx(stats.chi2.sf(by_hand, 2))


def test_small_sample_diebold_mariano_matches_the_cosine_estimator_written_out_by_hand():
    d = np.random.default_rng(5).normal(0.3, 1, 26)
    n, b = len(d), 3                                      # floor(0.4 x 26^(2/3)) = floor(3.51) = 3 cosines
    projections = [np.sqrt(2 / n) * sum(np.cos(np.pi * j * (t - 0.5) / n) * (d[t - 1] - d.mean()) for t in range(1, n + 1))
                   for j in range(1, b + 1)]
    by_hand = d.mean() / np.sqrt(np.mean(np.square(projections)) / n)
    statistic, p_value, b_used = diebold_mariano_small_sample(d)
    assert b_used == b
    assert statistic == pytest.approx(by_hand)
    assert p_value == pytest.approx(2 * stats.t.sf(abs(by_hand), b))
    assert diebold_mariano_small_sample(d[:8])[2] == 1                   # eight days: floor(0.4 x 4) = 1 cosine


def ar1(n, rho, rng, burn=50):
    return lfilter([1.0], [1.0, -rho], rng.standard_normal(n + burn))[burn:]


def test_on_26_days_the_newey_west_test_over_rejects_and_the_small_sample_test_does_not():
    # September has 26 forecast days in notebook 03. Equal accuracy is true in every simulated sample.
    rng = np.random.default_rng(6)
    iid = [rng.normal(0, 1, 26) for _ in range(2000)]
    autocorrelated = [ar1(26, 0.3, rng) for _ in range(2000)]
    assert np.mean([diebold_mariano(d)[1] < 0.05 for d in iid[:1000]]) > 0.10     # about 15% instead of 5%
    for sample in (iid, autocorrelated):
        assert 0.025 <= np.mean([diebold_mariano_small_sample(d)[1] < 0.05 for d in sample]) <= 0.085


def test_var_and_es_follow_the_stated_quantile_convention():
    pnl = -np.arange(1, 251, dtype=float)                 # 250 days with losses of 1, 2, ..., 250
    assert var_es(pnl) == pytest.approx((247.51, 247.0))  # interpolated VaR; ES = mean of the 7 worst losses
    assert var_es(pnl, method="inverted_cdf") == pytest.approx((248.0, 247.0))   # VaR = the third-worst loss
    # the ES takes the convention too, which matters where the two select different outcomes: of four losses at 70%,
    # "linear" cuts at a loss of 3.1 and keeps only the worst, "inverted_cdf" cuts at the second-worst and keeps two
    four = np.array([-4.0, -3.0, -2.0, -1.0])
    assert var_es(four, es_level=0.7)[1] == pytest.approx(4.0)
    assert var_es(four, es_level=0.7, method="inverted_cdf")[1] == pytest.approx(3.5)


@pytest.mark.parametrize("spearman, ks, zone", [(0.85, 0.05, "green"), (0.80, 0.05, "amber"), (0.85, 0.09, "amber"),
                                                 (0.70, 0.12, "amber"), (0.69, 0.05, "red"), (0.85, 0.121, "red")])
def test_pla_zones_follow_the_mar32_thresholds(spearman, ks, zone):
    assert pla_zone(spearman, ks) == zone


def test_ewma_volatility_follows_the_riskmetrics_recursion_column_by_column():
    x = np.random.default_rng(7).normal(0, [1.0, 2.0], (80, 2))
    lam, warmup = 0.94, 30
    sigma = ewma_volatility(x, lam, warmup)
    for j in range(2):
        var = [np.var(x[:warmup, j])]
        for i in range(1, len(x)):
            var.append(lam * var[-1] + (1 - lam) * x[i - 1, j] ** 2)
        assert sigma[:, j] == pytest.approx(np.sqrt(var))
    assert ewma_volatility(x[:, 0], lam, warmup) == pytest.approx(sigma[:, 0])       # one series works too
    assert ewma_volatility(x, lam) == pytest.approx(sigma)                           # a warm-up of 30 rows by default


def test_volatility_scaling_carries_past_changes_to_the_current_volatility():
    # volatility doubles halfway: rescaled to the second regime, the first half's changes take its volatility
    rng = np.random.default_rng(8)
    x = np.r_[rng.normal(0, 1, 3000), rng.normal(0, 2, 3000)]
    sigma = ewma_volatility(x)
    scaled = volatility_scaled(x, sigma, np.arange(1000, 2900), len(x) - 1)
    assert np.std(scaled) == pytest.approx(sigma[-1], rel=0.1)
    assert sigma[-500:].mean() == pytest.approx(2.0, rel=0.1) and sigma[2000:2900].mean() == pytest.approx(1.0, rel=0.1)


def test_the_paired_test_counts_the_days_with_one_exception_and_matches_mcnemar():
    # 10 days with an exception of A only and 2 of B only (3 shared): p = 2 P(X <= 2), X ~ Binomial(12, 0.5)
    a = np.r_[np.ones(13, dtype=int), np.zeros(85, dtype=int)]
    b = np.r_[np.zeros(10, dtype=int), np.ones(5, dtype=int), np.zeros(83, dtype=int)]
    assert paired_exceptions(a, b) == pytest.approx((10, 2, 2 * (1 + 12 + 66) / 2 ** 12))
    table = [[np.sum(a & b), np.sum(a & (1 - b))], [np.sum((1 - a) & b), np.sum((1 - a) & (1 - b))]]
    assert paired_exceptions(a, b)[2] == pytest.approx(mcnemar(table, exact=True).pvalue)
    assert paired_exceptions(a, a)[2] == 1.0                                       # no day tells them apart
    assert paired_exceptions(a.astype(float), b.astype(float)) == paired_exceptions(a, b)   # hits given as 0.0 and 1.0

