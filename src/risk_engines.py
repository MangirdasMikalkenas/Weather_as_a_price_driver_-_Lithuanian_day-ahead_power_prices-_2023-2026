"""
Risk engines of notebooks 04 and 05, kept out of the notebooks so that they can be tested with known answers
(tests/test_risk_engines.py).

- Historical simulation with full revaluation: daily changes of the risk factors (absolute or logarithmic), applied to
  the market of the day before the forecast day and, optionally, rescaled to the current volatility (filtered
  historical simulation; Hull & White, 1998).
- The window of history that a forecast may use, and the most stressful window of a history (the stressed VaR and the
  stressed calibration of the exposure model).
- Rolling VaR-type limits and Expected Shortfall of a series of daily values known with a lag, plain or filtered (the
  cash-flow-at-risk of notebook 04).
- Synthetic histories for detection rates: blocks of consecutive observed daily changes (a circular block bootstrap)
  turned back into levels, and the scenario P&L of thousands of forecast days in one revaluation.
"""

import numpy as np

from backtests import var_es, volatility_scaled


def daily_changes(levels, kind="absolute"):
    """Row i: the change from day i to day i + 1, absolute (for levels such as rates, which can be negative) or
    logarithmic (for prices such as exchange rates)."""
    levels = np.asarray(levels, dtype=float)
    if kind == "absolute":
        return np.diff(levels, axis=0)
    if kind == "log":
        return np.diff(np.log(levels), axis=0)
    raise ValueError(f"unknown kind of change: {kind}")


def apply_changes(level, changes, kind="absolute"):
    """Scenario levels: today's `level` moved by each of `changes`, added or, for logarithmic changes, as a factor."""
    if kind == "absolute":
        return level + changes
    if kind == "log":
        return level * np.exp(changes)
    raise ValueError(f"unknown kind of change: {kind}")


def history_window(t, window):
    """Rows of the daily changes that a forecast for day t, made at the close of day t - 1, may use: the last
    `window` changes, the newest being the change from day t - 2 to day t - 1."""
    return np.arange(t - 1 - window, t - 1)


def scenario_pnl(revalue, levels, changes, kinds, t, rows, scale=None):
    """P&L distribution of day t, forecast at the close of day t - 1: the changes in `rows` applied to the market of
    day t - 1 and the portfolio revalued in full by revalue(**risk factors). `levels`, `changes` and `kinds` are dicts
    by risk factor. With `scale` (EWMA volatilities by risk factor), each change is first rescaled from the volatility
    of its own day to the forecast for day t (filtered historical simulation)."""
    today = {name: levels[name][t - 1] for name in levels}
    moved = {}
    for name in levels:
        change = changes[name][rows] if scale is None else volatility_scaled(changes[name], scale[name], rows, t - 1)
        moved[name] = apply_changes(today[name], change, kinds[name])
    return revalue(**moved) - revalue(**today)


def rolling_scenario_pnl(revalue, levels, changes, kinds, days, window, chunk=200):
    """scenario_pnl for many forecast days at once: row i is the P&L distribution of day days[i] from the `window`
    changes known at the close of the day before (history_window), with the same arithmetic but one revaluation for
    each chunk of days. Returns an array of shape (len(days), window)."""
    days = np.asarray(days)
    out = np.empty((len(days), window))
    for start in range(0, len(days), chunk):
        part = days[start:start + chunk]
        rows = part[:, None] - 1 - window + np.arange(window)
        today = {name: np.asarray(levels[name])[part - 1] for name in levels}
        moved = {name: apply_changes(today[name][:, None], np.asarray(changes[name])[rows], kinds[name])
                 for name in levels}
        flat = {name: value.reshape(len(part) * window, *value.shape[2:]) for name, value in moved.items()}
        out[start:start + len(part)] = revalue(**flat).reshape(len(part), window) - revalue(**today)[:, None]
    return out


def block_bootstrap_rows(n_rows, length, block, rng):
    """Rows of one synthetic history: `length` rows of a sample of `n_rows`, in blocks of `block` consecutive rows that
    start at random rows and wrap around the end of the sample (the circular block bootstrap of Politis & Romano,
    1992). Within a block the order of the days, and so the clustering of volatility, is kept."""
    starts = rng.integers(0, n_rows, size=-(-length // block))
    return ((starts[:, None] + np.arange(block)) % n_rows).ravel()[:length]


def levels_from_changes(start, changes, kind="absolute"):
    """The inverse of daily_changes: the levels of a history that starts at `start` and moves by `changes`."""
    start, changes = np.asarray(start, dtype=float), np.asarray(changes, dtype=float)
    path = np.cumsum(changes, axis=0)
    return np.concatenate([start[None], apply_changes(start, path, kind)])


def most_stressful_window(end, length, step, severity):
    """Rows of the most stressful window: of the windows of `length` rows that end before row `end` and start every
    `step` rows from row 0, the one with the largest severity(rows), such as a VaR or an effective EPE."""
    starts = np.arange(0, end - length + 1, step)
    values = [severity(np.arange(s, s + length)) for s in starts]
    best = starts[int(np.argmax(values))]
    return np.arange(best, best + length)


def tail_forecasts(values, days, window, levels, es_level, lag=1, sigma=None, method="linear"):
    """VaR-type limits at each of `levels` and the Expected Shortfall at `es_level`, as positive losses, for each day t
    in `days`, from the `window` values up to the end of day t - lag. With `sigma` (EWMA volatilities, sigma[i] the
    forecast for day i from the days before it), the history is standardised by its own volatility and rescaled by
    sigma[t - lag + 1], the forecast made with the data to the end of day t - lag (filtered historical simulation).
    Returns the limits (a dict by level), the ES and the sample, rescaled, that each forecast used."""
    values = np.asarray(values, dtype=float)
    standardised = values if sigma is None else values / sigma
    limits = {level: np.empty(len(days)) for level in levels}
    es, samples = np.empty(len(days)), []
    for i, t in enumerate(days):
        h = t - lag + 1                                     # the history ends at day t - lag
        sample = standardised[h - window:h]
        scale = 1.0 if sigma is None else sigma[h]
        for level in levels:
            limits[level][i] = scale * var_es(sample, var_level=level, es_level=level, method=method)[0]
        es[i] = scale * var_es(sample, var_level=es_level, es_level=es_level, method=method)[1]
        samples.append(scale * sample)
    return limits, es, samples
