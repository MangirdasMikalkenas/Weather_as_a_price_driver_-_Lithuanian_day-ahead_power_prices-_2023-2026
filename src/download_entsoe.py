"""
Download ENTSO-E Transparency Platform data for Lithuania and neighbouring bidding zones.

Output: one CSV per dataset / zone / year in data/raw/entsoe/, in a tidy "long" format
    ts_utc, zone, dataset, series, value
All timestamps are converted to UTC. Existing files are skipped, so the script can
simply be re-run after an error. Delete a file to download it again (for example the
current, incomplete year after moving END forward).

Day-ahead prices are hourly until 2025-09-30 and 15-minute from 2025-10-01 (SDAC 15-min MTU);
they are stored as published and aggregated to hours later.

Nordic hydro reservoir filling (weekly, MWh of stored energy) starts in 2015: the years
before 2023 are only used to compute what a "normal" filling level is for each week.

Setup: put your token into .env in the repository root
    ENTSOE_API_KEY=<your-token>

Run from the repository root:  python src/download_entsoe.py
"""

import os
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError

OUT_DIR = Path("data/raw/entsoe")
TZ = "Europe/Vilnius"
END = pd.Timestamp("2026-09-01", tz=TZ)  # exclusive: the last full month is August 2026

PRICE_ZONES = ["LT", "LV", "EE", "FI", "SE_4", "PL"]
HYDRO_ZONES = ["NO_1", "NO_2", "NO_3", "NO_4", "NO_5", "SE_1", "SE_2", "SE_3", "SE_4", "FI"]

# dataset name -> (zones, first year, query function)
DATASETS = {
    "da_price": (PRICE_ZONES, 2023, lambda c, z, s, e: c.query_day_ahead_prices(z, start=s, end=e)),
    "generation": (["LT"], 2023, lambda c, z, s, e: c.query_generation(z, start=s, end=e, nett=True)),
    "load": (["LT"], 2023, lambda c, z, s, e: c.query_load(z, start=s, end=e)),
    "load_forecast": (["LT"], 2023, lambda c, z, s, e: c.query_load_forecast(z, start=s, end=e)),
    "wind_solar_forecast": (["LT"], 2023,
                            lambda c, z, s, e: c.query_wind_and_solar_forecast(z, start=s, end=e)),
    "hydro_reservoirs": (HYDRO_ZONES, 2015,
                         lambda c, z, s, e: c.query_aggregate_water_reservoirs_and_hydro_storage(
                             z, start=s, end=e)),
}


def year_ranges(first_year):
    """Yield (year, start, end) in local time, end exclusive."""
    year = first_year
    while True:
        start = pd.Timestamp(f"{year}-01-01", tz=TZ)
        if start >= END:
            return
        yield year, start, min(pd.Timestamp(f"{year + 1}-01-01", tz=TZ), END)
        year += 1


def to_long(obj, start, end, zone, dataset):
    """Tidy an entsoe-py Series/DataFrame: keep [start, end), drop duplicates, UTC, long format."""
    if isinstance(obj, pd.Series):
        obj = obj.to_frame(name=dataset)
    # entsoe-py truncates inclusively, so the first timestamp of the next year would be
    # duplicated across files; keep a half-open interval and drop repeated timestamps.
    obj = obj[(obj.index >= start) & (obj.index < end)].copy()
    obj = obj[~obj.index.duplicated(keep="first")]
    obj.columns = [" / ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in obj.columns]
    obj.index = obj.index.tz_convert("UTC").tz_localize(None)
    obj.index.name = "ts_utc"
    long = obj.reset_index().melt(id_vars="ts_utc", var_name="series", value_name="value")
    long.insert(1, "zone", zone)
    long.insert(2, "dataset", dataset)
    return long.dropna(subset=["value"])


def main():
    load_dotenv()
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        raise SystemExit("ENTSOE_API_KEY not found. Add it to the .env file in the repository root.")
    client = EntsoePandasClient(api_key=api_key)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for dataset, (zones, first_year, query) in DATASETS.items():
        for zone in zones:
            for year, start, end in year_ranges(first_year):
                path = OUT_DIR / f"{dataset}_{zone}_{year}.csv"
                if path.exists():
                    print(f"{path.name}: exists, skipped")
                    continue
                try:
                    obj = query(client, zone, start, end)
                except NoMatchingDataError:
                    print(f"{path.name}: no data")
                    continue
                except Exception as exc:  # network errors etc.; re-run the script to retry
                    print(f"{path.name}: FAILED - {exc}")
                    continue
                df = to_long(obj, start, end, zone, dataset)
                df.to_csv(path, index=False)
                print(f"{path.name}: {len(df):,} rows")
                time.sleep(1)  # be gentle with the API


if __name__ == "__main__":
    main()
