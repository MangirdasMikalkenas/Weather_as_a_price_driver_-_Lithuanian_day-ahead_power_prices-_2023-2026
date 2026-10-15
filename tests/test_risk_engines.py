"""The risk engines of src/risk_engines.py, checked against answers known in advance: which days a forecast may use,
on which market the scenarios are revalued, VaR and ES of samples whose quantiles are known exactly or in closed
form, volatility scaling, and a stress period chosen without hindsight."""

import numpy as np
import pytest
from scipy import stats

from backtests import var_es
from risk_engines import (apply_changes, block_bootstrap_rows, daily_changes, history_window, levels_from_changes,
                          most_stressful_window, rolling_scenario_pnl, scenario_pnl, tail_forecasts)

LOSSES = -np.arange(1, 251, dtype=float)       # 250 outcomes with losses of 1, 2, ..., 250


def one_factor(levels, kind="absolute"):
    # the levels, daily changes and kind of change of a single risk factor x, as scenario_pnl takes them
    return {"x": levels}, {"x": daily_changes(levels, kind)}, {"x": kind}


def linear(x):
    return x


@pytest.mark.parametrize("kind", ["absolute", "log"])
def test_each_days_change_applied_to_that_day_gives_the_next_day(kind):
    levels = np.exp(np.random.default_rng(1).normal(0, 0.01, (50, 3)).cumsum(axis=0))
    assert apply_changes(levels[:-1], daily_changes(levels, kind), kind) == pytest.approx(levels[1:])


def test_changes_are_absolute_unless_said_otherwise_and_other_kinds_are_refused():
    levels = np.array([1.0, 1.5, 0.5])
    assert daily_changes(levels).tolist() == [0.5, -1.0]
    assert apply_changes(1.0, np.array([0.5, -1.0])).tolist() == [1.5, 0.0]
    assert levels_from_changes(1.0, np.array([0.5, -1.0])).tolist() == [1.0, 1.5, 0.5]
    with pytest.raises(ValueError, match="unknown kind of change: relative"):
        daily_changes(levels, "relative")
    with pytest.raises(ValueError, match="unknown kind of change: relative"):
        apply_changes(1.0, levels, "relative")


def test_a_forecast_uses_only_the_changes_known_at_the_close_of_the_day_before():
    levels = 100 + np.random.default_rng(2).normal(0, 1, 601).cumsum()
    levels[401:] -= 50                                    # a crash from day 400 to day 401 (row 400 of the changes)
    assert history_window(402, 250).tolist() == list(range(151, 401))
    pnl = {t: scenario_pnl(linear, *one_factor(levels), t, history_window(t, 250)) for t in (401, 402)}
    assert pnl[401].min() > -10                           # the forecast for day 401, made at the close of day 400
    assert pnl[402].min() == pytest.approx(levels[401] - levels[400])     # the next forecast includes the crash


def test_the_scenarios_are_revalued_on_the_market_of_the_day_before():
    # x is i on day i and rises by 1 a day: a position worth x squared gains (t - 1 + 1)^2 - (t - 1)^2 = 2t - 1 on
    # day t; applied to the market of day t or of day t - 2, the same changes would give 2t + 1 or 2t - 3
    levels = np.arange(1000, dtype=float)
    pnl = scenario_pnl(lambda x: x ** 2, *one_factor(levels), 300, history_window(300, 250))
    assert pnl == pytest.approx(np.full(250, 599.0))


@pytest.mark.parametrize("kind", ["absolute", "log"])
def test_historical_simulation_var_matches_the_normal_and_lognormal_closed_forms(kind):
    # 20,000 daily changes with a volatility of 20%, all used for the day after the last, when the factor stands at
    # 1.25: a million units of a factor that moves by normal absolute changes lose z(99%) x 20% x a million at the 99%
    # VaR; of a price that moves by normal log changes, 1.25 x (1 - exp(-z(99%) x 20%)) x a million, a fifth less than
    # its linear approximation
    sigma, n = 0.20, 20_000
    changes = np.random.default_rng(3).normal(0, sigma, n)
    path = np.r_[0, changes.cumsum()] - changes.sum()
    levels = 1.25 + path if kind == "absolute" else 1.25 * np.exp(path)
    pnl = scenario_pnl(lambda x: 1e6 * x, *one_factor(levels, kind), n + 1, history_window(n + 1, n))
    z = stats.norm.ppf(0.99)
    closed_form = 1e6 * sigma * z if kind == "absolute" else 1e6 * 1.25 * (1 - np.exp(-sigma * z))
    assert var_es(pnl)[0] == pytest.approx(closed_form, rel=0.04)


def test_filtered_scenarios_take_the_volatility_forecast_for_the_day_ahead():
    # changes are sigma x z with a known sigma on every row: rescaled to the forecast for day t (row t - 1), the
    # scenarios are sigma[t - 1] x z, whatever the volatility of the days they come from
    rng = np.random.default_rng(4)
    sigma, z = rng.uniform(0.5, 3.0, 600), rng.standard_normal(600)
    levels = np.r_[0, (sigma * z).cumsum()]
    rows = history_window(400, 250)
    pnl = scenario_pnl(linear, {"x": levels}, {"x": sigma * z}, {"x": "absolute"}, 400, rows, scale={"x": sigma})
    assert pnl == pytest.approx(sigma[399] * z[rows])


def test_the_stress_window_is_the_most_severe_one_known_at_the_time():
    # a moderate stress in rows 900-1149 and a severe one in rows 1600-1849: at row 1500 only the first is known
    changes = np.random.default_rng(5).normal(0, 1, 2000)
    changes[900:1150] *= 3
    changes[1600:1850] *= 6
    used = []

    def severity(rows):
        used.append(rows)
        return changes[rows].std()

    assert most_stressful_window(1500, 250, 20, severity).tolist() == list(range(900, 1150))
    assert max(rows.max() for rows in used) < 1500        # no row from row 1500 on was looked at
    assert all(rows.tolist() == list(range(rows[0], rows[0] + 250)) for rows in used)    # 250 consecutive rows each
    assert most_stressful_window(2000, 250, 20, severity).tolist() == list(range(1600, 1850))
    # the window that ends on the last row before the review date is a candidate, and with a step of one row the
    # search still stops there
    assert most_stressful_window(1850, 250, 20, severity).tolist() == list(range(1600, 1850))
    used.clear()
    most_stressful_window(1500, 250, 1, severity)
    assert max(rows.max() for rows in used) == 1499


def test_tail_forecasts_use_the_window_that_ends_lag_days_before():
    # the 250 days up to day t - lag lose 1, 2, ..., 250 in random order; every other day loses a million, so a
    # window shifted by one day would show it
    t, lag = 400, 2
    values = np.full(600, -1e6)
    values[t - lag - 249:t - lag + 1] = np.random.default_rng(6).permutation(LOSSES)
    limits, es, samples = tail_forecasts(values, [t], 250, (0.99, 0.975), 0.975, lag)
    assert limits[0.99][0] == pytest.approx(247.51)       # numpy's linear quantile: between the 3rd- and 4th-worst
    assert limits[0.975][0] == pytest.approx(243.775)     # between the 7th- and 8th-worst
    assert es[0] == pytest.approx(247.0)                  # the mean of the 7 worst losses
    assert sorted(samples[0]) == sorted(LOSSES)
    # by default a forecast is made at the close of the day before: for day t - 1 it uses the same window
    limits_next, es_next, _ = tail_forecasts(values, [t - 1], 250, (0.99, 0.975), 0.975)
    assert limits_next[0.99][0] == limits[0.99][0] and es_next[0] == es[0]


def test_tail_forecasts_pass_the_quantile_convention_to_the_limits_and_the_es():
    # four days that lose 4, 3, 2 and 1, at 70%: "linear" interpolates the limit to 3.1 and keeps only the worst loss
    # for the ES; "inverted_cdf" takes the second-worst loss as the limit and the two worst for the ES
    values = np.array([np.nan, -4.0, -3.0, -2.0, -1.0])                  # day 0 is outside the window of day 5
    for method, limit, shortfall in [("linear", 3.1, 4.0), ("inverted_cdf", 3.0, 3.5)]:
        limits, es, _ = tail_forecasts(values, [5], 4, (0.7,), 0.7, method=method)
        assert limits[0.7][0] == pytest.approx(limit) and es[0] == pytest.approx(shortfall)


def test_filtered_tail_forecasts_rescale_the_standardised_history_to_the_latest_volatility():
    # values are sigma x the losses above: standardised, the history is again losses of 1, ..., 250, carried to
    # sigma[t - lag + 1], the forecast made with the data to the end of day t - lag
    t, lag = 400, 2
    rng = np.random.default_rng(7)
    sigma, standardised = rng.uniform(0.5, 3.0, 600), np.full(600, -1e6)
    standardised[t - lag - 249:t - lag + 1] = rng.permutation(LOSSES)
    limits, es, _ = tail_forecasts(sigma * standardised, [t], 250, (0.99,), 0.975, lag, sigma=sigma)
    assert limits[0.99][0] == pytest.approx(sigma[t - lag + 1] * 247.51)
    assert es[0] == pytest.approx(sigma[t - lag + 1] * 247.0)


def test_rolling_scenario_pnl_equals_the_daily_engine_day_by_day():
    # a rate curve (absolute changes) and an exchange rate (log changes), revalued by a non-linear function
    rng = np.random.default_rng(8)
    rates = 0.02 + rng.normal(0, 0.001, (400, 3)).cumsum(axis=0)
    fx = 1.1 * np.exp(rng.normal(0, 0.005, 400).cumsum())
    levels, kinds = {"rates": rates, "fx": fx}, {"rates": "absolute", "fx": "log"}
    changes = {name: daily_changes(levels[name], kinds[name]) for name in levels}

    def revalue(rates, fx):
        return np.exp(-5 * rates).sum(axis=-1) * 1e6 / fx

    days = np.arange(251, 399)
    one_by_one = np.vstack([scenario_pnl(revalue, levels, changes, kinds, t, history_window(t, 250)) for t in days])
    assert rolling_scenario_pnl(revalue, levels, changes, kinds, days, 250, chunk=40) == pytest.approx(one_by_one)


def test_block_bootstrap_rows_are_blocks_of_consecutive_days_that_wrap_around():
    rows = block_bootstrap_rows(100, 250, 20, np.random.default_rng(9))
    assert len(rows) == 250 and rows.min() >= 0 and rows.max() < 100
    assert all(((block[1:] - block[:-1]) % 100 == 1).all() for block in np.split(rows[:240], 12))
    assert (rows == block_bootstrap_rows(100, 250, 20, np.random.default_rng(9))).all()      # reproducible
    # any row can start a block: with one-day blocks, 2,000 rows drawn from 10 include every one of them
    assert set(block_bootstrap_rows(10, 2000, 1, np.random.default_rng(10)).tolist()) == set(range(10))


@pytest.mark.parametrize("kind", ["absolute", "log"])
def test_levels_from_changes_rebuild_the_history(kind):
    levels = np.exp(np.random.default_rng(10).normal(0, 0.01, (60, 2)).cumsum(axis=0))
    assert levels_from_changes(levels[0], daily_changes(levels, kind), kind) == pytest.approx(levels)

