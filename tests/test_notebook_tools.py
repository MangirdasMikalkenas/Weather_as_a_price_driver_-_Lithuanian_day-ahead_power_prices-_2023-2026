# The helpers of src/notebook_tools.py.

import warnings

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from notebook_tools import count_warnings, describe_warnings, fill_gaps, fingerprint, fmt_p, git_version, p_text, save_figure


def test_fingerprint_is_stable_and_reacts_to_any_change_in_the_data():
    table = pd.DataFrame({"day": pd.date_range("2026-01-01", periods=3), "real": [True, False, True], "x": [1.0, 2.0, 3.0]})
    design = {"lasso": {0: np.ones((5, 3))}, "lgb": table, "settings": {"num_leaves": 31, "half_life": 180.0}}
    assert fingerprint(design) == fingerprint(design)
    changed = table.copy()
    changed.loc[1, "x"] = 2.0001
    assert fingerprint({**design, "lgb": changed}) != fingerprint(design)
    assert fingerprint({"settings": design["settings"], "lgb": table, "lasso": design["lasso"]}) == fingerprint(design)


def test_fingerprint_reacts_to_a_change_in_the_code():
    def model_a(x):
        return x + 1

    def model_b(x):
        return x + 2

    assert fingerprint(model_a) != fingerprint(model_b)


def test_fill_gaps_uses_only_past_values():
    index = pd.date_range("2026-01-01", periods=72, freq="h")
    series = pd.Series(np.arange(72, dtype=float), index=index)
    gaps = series.copy()
    gaps.iloc[[0, 10, 30, 31, 32, 33, 34]] = np.nan
    filled = fill_gaps(gaps.to_frame("x"))["x"]
    assert np.isnan(filled.iloc[0])                       # nothing earlier to fill the first hour with
    assert filled.iloc[10] == series.iloc[9]               # a short gap takes the last value
    assert filled.iloc[32] == series.iloc[29]              # the first 3 hours of a long gap take the last value
    assert filled.iloc[34] == filled.iloc[10]              # later hours take the same hour a day earlier
    assert (filled.dropna() <= series[filled.notna()]).all()   # the test series rises, so no value comes from the future


def test_count_warnings_counts_by_type_and_message():
    with count_warnings() as counts:
        for _ in range(3):
            warnings.warn("did not converge", RuntimeWarning)
        warnings.warn("other", UserWarning)
    assert counts == {"RuntimeWarning (did not converge)": 3, "UserWarning (other)": 1}
    assert describe_warnings({}) == ""
    assert "3 x RuntimeWarning" in describe_warnings(counts)


def test_git_version_outside_a_repository(tmp_path):
    assert git_version(tmp_path) == "unknown"


def test_save_figure_writes_svg_and_png(tmp_path):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    save_figure(fig, "chart", tmp_path)
    plt.close(fig)
    assert (tmp_path / "chart.svg").stat().st_size > 0 and (tmp_path / "chart.png").stat().st_size > 0


@pytest.mark.parametrize("p, sentence, cell", [(0.0004, "p < 0.001", "<0.001"), (0.0412, "p = 0.041", "0.041"),
                                               (np.nan, None, "n/a")])
def test_p_values_are_never_shown_as_zero(p, sentence, cell):
    if sentence is not None:
        assert fmt_p(p) == sentence
    assert p_text(p) == cell
