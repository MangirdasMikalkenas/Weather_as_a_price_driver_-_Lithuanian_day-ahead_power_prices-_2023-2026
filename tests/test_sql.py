# The SQL layer, built on a small synthetic dataset: views, quality checks, 15-minute prices and the
# pre-auction cleaning of the Lithuanian load forecast.

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

SQL = Path(__file__).resolve().parents[1] / "sql"
VIEW_FILES = ["02_clean.sql", "03_analysis_table.sql", "04_quality_checks.sql", "05_capture_rates.sql"]


def raw_rows():
    rng = np.random.default_rng(0)
    hours = pd.date_range("2026-08-01", "2026-09-30 23:00", freq="h")
    load = 1400 + rng.normal(0, 20, len(hours))
    forecast = load * 1.01
    load[500] *= 3              # a spike in the actual load: the published forecast for that hour is right
    rows = [pd.DataFrame({"ts_utc": hours, "zone": "LT", "dataset": "load", "series": "Actual Load", "value": load}),
            pd.DataFrame({"ts_utc": hours, "zone": "LT", "dataset": "load_forecast", "series": "Forecasted Load",
                          "value": forecast})]
    hourly = hours[hours < "2026-09-15"]
    rows.append(pd.DataFrame({"ts_utc": hourly, "zone": "LT", "dataset": "da_price", "series": "da_price", "value": 80.0}))
    quarters = pd.date_range("2026-09-15", "2026-09-30 23:45", freq="15min")
    rows.append(pd.DataFrame({"ts_utc": quarters, "zone": "LT", "dataset": "da_price", "series": "da_price",
                              "value": np.tile([60.0, 70.0, 80.0, 90.0], len(quarters) // 4)}))
    return pd.concat(rows, ignore_index=True), hours[500]


@pytest.fixture(scope="module")
def db():
    raw, spike_hour = raw_rows()
    con = duckdb.connect()
    con.execute((SQL / "01_schema.sql").read_text())
    con.execute("INSERT INTO entsoe_raw SELECT * FROM raw")
    for name in VIEW_FILES:
        con.execute((SQL / name).read_text())
    yield con, spike_hour
    con.close()


def test_every_view_builds_and_every_quality_check_reports(db):
    con, _ = db
    checks = con.sql("SELECT * FROM qa_summary").df()
    assert len(checks) == 8
    assert checks.set_index("check_name").loc["missing LT price hours", "problems"] == 0


def test_quarter_hour_prices_are_averaged_to_hours(db):
    con, _ = db
    row = con.sql("SELECT price_eur_mwh, n_intervals FROM price_hourly WHERE ts_utc = TIMESTAMP '2026-09-20 10:00'").fetchone()
    assert row == (75.0, 4)


def test_the_forecasting_input_never_uses_the_actual_load_of_the_same_hour(db):
    con, spike_hour = db
    same_hour_rule, pre_auction_rule = con.execute(
        "SELECT load_forecast_mw, load_forecast_exante_mw FROM lt_load_hourly WHERE ts_utc = ?", [spike_hour]).fetchone()
    assert same_hour_rule is None            # removed by comparing with the outcome (explanatory notebooks only)
    assert pre_auction_rule is not None      # kept: a week earlier the load was normal


def test_lt_hourly_keeps_the_fixed_analysis_period(db):
    con, _ = db
    last_fixed = con.sql("SELECT max(ts_local) FROM lt_hourly").fetchone()[0]
    last_all = con.sql("SELECT max(ts_local) FROM lt_hourly_all").fetchone()[0]
    assert last_fixed < pd.Timestamp("2026-09-01") <= last_all
