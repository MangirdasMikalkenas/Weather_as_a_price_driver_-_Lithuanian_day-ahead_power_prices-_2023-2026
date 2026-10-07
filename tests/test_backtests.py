# The statistical tests of src/backtests.py, each checked against an independent reference.

import numpy as np
import pytest
import statsmodels.api as sm
from scipy import stats

from backtests import acerbi_szekely_z2, backtest, christoffersen, diebold_mariano, giacomini_white, kupiec, traffic_light


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


def test_christoffersen_matches_a_markov_likelihood_written_out_by_hand():
    hits = np.array([0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0])
    pairs = list(zip(hits[:-1], hits[1:]))
    p01 = sum(1 for a, b in pairs if a == 0 and b == 1) / sum(1 for a, _ in pairs if a == 0)
    p11 = sum(1 for a, b in pairs if a == 1 and b == 1) / sum(1 for a, _ in pairs if a == 1)
    p = sum(b for _, b in pairs) / len(pairs)
    loglik_markov = sum(np.log((p11 if a else p01) if b else (1 - p11 if a else 1 - p01)) for a, b in pairs)
    loglik_independent = sum(np.log(p if b else 1 - p) for _, b in pairs)
    lr, _ = christoffersen(hits)
    assert lr == pytest.approx(2 * (loglik_markov - loglik_independent))


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


def test_diebold_mariano_matches_a_newey_west_statistic_computed_by_hand():
    rng = np.random.default_rng(2)
    d, lags = rng.normal(0.1, 1, 300), 7
    e, n = d - d.mean(), len(d)
    gamma = [np.sum(e[k:] * e[:n - k]) / n for k in range(lags + 1)]
    long_run_variance = gamma[0] + 2 * sum((1 - k / (lags + 1)) * gamma[k] for k in range(1, lags + 1))
    statistic, p_value = diebold_mariano(d, max_lags=lags)
    assert statistic == pytest.approx(d.mean() / np.sqrt(long_run_variance / n))
    assert p_value == pytest.approx(2 * stats.norm.sf(abs(statistic)))


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
