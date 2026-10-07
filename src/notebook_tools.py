"""
Helpers shared by the notebooks: saving charts, formatting results, filling gaps with past values only, and
the pieces of the versioned cache of notebook 03 (fingerprints, the git version and warning counts).

The notebooks import them after adding src/ to the path:
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from notebook_tools import save_figure, fmt_p
They are tested in tests/test_notebook_tools.py.
"""

import hashlib
import inspect
import subprocess
import warnings
from contextlib import contextmanager
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd


def connect(db_path):
    """Open the database read-only with one thread. With several threads DuckDB adds floating-point numbers in an
    order that changes from run to run, so the last digits of averages and sums differ between runs; with one thread
    every read is bitwise identical, which keeps the results and the cache keys of notebook 03 reproducible."""
    con = duckdb.connect(str(db_path), read_only=True)
    con.execute("SET threads TO 1")
    return con


def save_figure(fig, name, folder):
    """Save a chart twice: SVG stays sharp at any width (used in results_analysis.md), PNG suits slides.
    The SVG carries no date and uses fixed element ids, so an unchanged chart gives an unchanged file and git shows
    a figure as modified only when the chart itself changed."""
    with matplotlib.rc_context({"svg.hashsalt": "lt-power"}):
        fig.savefig(Path(folder) / f"{name}.svg", bbox_inches="tight", metadata={"Date": None})
    fig.savefig(Path(folder) / f"{name}.png", dpi=150, bbox_inches="tight")


def effect(model, name, scale=1.0):
    """Coefficient of one variable with its 95% confidence interval and p-value, times `scale`."""
    ci = model.conf_int().loc[name] * scale
    return pd.Series({
        "effect": model.params[name] * scale,
        "ci_low": ci.min(),
        "ci_high": ci.max(),
        "p_value": model.pvalues[name],
    })


def fmt_p(p):
    """p-value in a sentence. A p-value is never exactly 0, so very small values are shown as an upper bound."""
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def p_text(p):
    """p-value in a table cell: <0.001 for very small values and n/a when there is none."""
    return "n/a" if pd.isna(p) else ("<0.001" if p < 0.001 else f"{p:.3f}")


def show(table, decimals=3):
    """Round a results table for display, with p-values written by p_text."""
    out = table.round(decimals)
    if "p_value" in out.columns:
        out["p_value"] = table["p_value"].map(p_text)
    return out


def show_p(table):
    """A results table for display with p-values written by p_text and the other columns unchanged."""
    return table.assign(p_value=table["p_value"].map(p_text))


def verdict(ok):
    return "supported" if ok else "not supported"


def fill_gaps(frame):
    """Fill gaps with past values only: up to 3 hours with the last value, longer ones with the same hour a day earlier."""
    frame = frame.ffill(limit=3)
    for _ in range(7):
        frame = frame.fillna(frame.shift(24))
    return frame


def fingerprint(*objects):
    """A short hash of code and data: functions by their source text, tables and arrays by their content."""
    h = hashlib.sha256()

    def add(obj):
        if inspect.isfunction(obj):
            try:
                h.update(inspect.getsource(obj).encode())
            except (OSError, TypeError):
                h.update(obj.__code__.co_code)
        elif isinstance(obj, (pd.DataFrame, pd.Series)):
            h.update(pd.util.hash_pandas_object(obj, index=True).to_numpy().tobytes())
            h.update(repr(list(obj.columns) if isinstance(obj, pd.DataFrame) else obj.name).encode())
        elif isinstance(obj, np.ndarray):
            h.update(repr((obj.shape, obj.dtype)).encode())
            h.update(np.ascontiguousarray(obj).tobytes())
        elif isinstance(obj, dict):
            for k in sorted(obj, key=repr):
                add(k)
                add(obj[k])
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                add(item)
        else:
            h.update(repr(obj).encode())

    for obj in objects:
        add(obj)
    return h.hexdigest()[:12]


def git_version(root):
    """The commit of the running code, marked when the SQL or Python code has uncommitted changes."""
    try:
        git = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        dirty = git("status", "--porcelain", "--untracked-files=no", "--", "sql", "src")
        return git("rev-parse", "--short", "HEAD") + (" + uncommitted changes" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


@contextmanager
def count_warnings():
    """Record every warning raised inside the block; on exit, the yielded dict counts them by type and message."""
    counts = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield counts
    for w in caught:
        label = f"{w.category.__name__} ({str(w.message).splitlines()[0][:70]})"
        counts[label] = counts.get(label, 0) + 1


def describe_warnings(counts):
    return "" if not counts else "; warnings: " + ", ".join(f"{n} x {label}" for label, n in counts.items())
