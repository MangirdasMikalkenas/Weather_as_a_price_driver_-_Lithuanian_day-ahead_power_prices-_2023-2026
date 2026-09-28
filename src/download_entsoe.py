"""
Download ENTSO-E Transparency Platform data for Lithuania and neighbouring bidding zones.

Output: one CSV per dataset / zone / month in data/raw/entsoe/, in a tidy "long" format
    ts_utc, zone, dataset, series, value
All timestamps are converted to UTC. Data are requested one month at a time and saved as
one file per month (dataset_zone_YYYY_MM.csv); files from earlier runs with one file per
year (dataset_zone_YYYY.csv) are kept, and for those years only the months from EXTEND_FROM
onwards are downloaded. Server errors are retried
a few times; a month that still fails is reported and retried on the next run, because
existing files are skipped. Delete a file to download it again.
The API token never appears in printed messages.

Day-ahead prices are hourly until 2025-09-30 and 15-minute from 2025-10-01 (SDAC 15-min MTU);
they are stored as published and aggregated to hours later.

Nordic hydro reservoir filling (weekly, MWh of stored energy) starts in 2015: the years
before 2023 are only used to compute what a "normal" filling level is for each week.

Day-ahead load, wind and solar forecasts are downloaded for Lithuania and the zones around it
(the price forecast in question 3 uses the neighbours' forecasts too), and so is the capacity
that the grid operators offer to the day-ahead market coupling on each Baltic border (an input
to the auction; ENTSO-E publishes no day-ahead NTC for these borders). A border is written
FROM-TO, e.g. SE_4-LT is the capacity from SE4 into Lithuania.

The data run to 26 September 2026, so that September can serve as a fresh test period for the
price forecasts. Years that were downloaded earlier as one file (up to August 2026) are kept, and
only the months from EXTEND_FROM onwards are added to them as monthly files.

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
END = pd.Timestamp("2026-09-27", tz=TZ)          # exclusive: data up to 26 September 2026
EXTEND_FROM = pd.Timestamp("2026-09-01", tz=TZ)  # the end of the earlier download

PRICE_ZONES = ["LT", "LV", "EE", "FI", "SE_4", "PL"]
FORECAST_ZONES = ["LT", "LV", "EE", "FI", "SE_3", "SE_4", "PL", "DE_LU"]
HYDRO_ZONES = ["NO_1", "NO_2", "NO_3", "NO_4", "NO_5", "SE_1", "SE_2", "SE_3", "SE_4", "FI"]
BORDERS = ["SE_4-LT", "LT-SE_4", "PL-LT", "LT-PL", "LV-LT", "LT-LV", "EE-LV", "LV-EE", "FI-EE", "EE-FI"]

# dataset name -> (zones, first year, query function)
DATASETS = {
    "da_price": (PRICE_ZONES, 2023, lambda c, z, s, e: c.query_day_ahead_prices(z, start=s, end=e)),
    "generation": (["LT"], 2023, lambda c, z, s, e: c.query_generation(z, start=s, end=e, nett=True)),
    "load": (["LT"], 2023, lambda c, z, s, e: c.query_load(z, start=s, end=e)),
    "load_forecast": (FORECAST_ZONES, 2023, lambda c, z, s, e: c.query_load_forecast(z, start=s, end=e)),
    "wind_solar_forecast": (FORECAST_ZONES, 2023,
                            lambda c, z, s, e: c.query_wind_and_solar_forecast(z, start=s, end=e)),
    "hydro_reservoirs": (HYDRO_ZONES, 2015,
                         lambda c, z, s, e: c.query_aggregate_water_reservoirs_and_hydro_storage(
                             z, start=s, end=e)),
    "offered_capacity": (BORDERS, 2023,
                         lambda c, z, s, e: c.query_offered_capacity(
                             *z.split("-"), start=s, end=e, contract_marketagreement_type="A01", implicit=True)),
}


def years(first_year):
    """Years from first_year up to the one containing END (exclusive)."""
    year = first_year
    while pd.Timestamp(f"{year}-01-01", tz=TZ) < END:
        yield year
        year += 1


def month_ranges(year):
    """Yield (month, start, end) in local time, end exclusive."""
    for month in range(1, 13):
        start = pd.Timestamp(f"{year}-{month:02d}-01", tz=TZ)
        if start >= END:
            return
        yield month, start, min(start + pd.offsets.MonthBegin(1), END)


def fetch(client, query, zone, start, end, api_key, attempts=3):
    """Run one query and retry server errors. Returns None when ENTSO-E has no data."""
    for attempt in range(1, attempts + 1):
        try:
            return query(client, zone, start, end)
        except NoMatchingDataError:
            return None
        except Exception as exc:  # network and server errors (e.g. HTTP 5xx)
            message = str(exc).replace(api_key, "***")  # error URLs contain the token
            if attempt == attempts:
                raise RuntimeError(message) from None
            wait = 10 * 3 ** (attempt - 1)  # 10 s, then 30 s
            print(f"    attempt {attempt} failed ({message[:60]}...), retrying in {wait} s")
            time.sleep(wait)


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

    counts = {"downloaded": 0, "no data": 0, "failed": 0}
    for dataset, (zones, first_year, query) in DATASETS.items():
        for zone in zones:
            for year in years(first_year):
                year_file = (OUT_DIR / f"{dataset}_{zone}_{year}.csv").exists()  # an earlier download
                for month, start, end in month_ranges(year):
                    if year_file and start < EXTEND_FROM:
                        continue  # already in the file for the whole year
                    path = OUT_DIR / f"{dataset}_{zone}_{year}_{month:02d}.csv"
                    if path.exists():
                        continue
                    try:
                        obj = fetch(client, query, zone, start, end, api_key)
                    except RuntimeError as exc:
                        print(f"{path.name}: FAILED - {exc} (re-run the script to retry)")
                        counts["failed"] += 1
                        continue
                    if obj is None:
                        print(f"{path.name}: no data")
                        counts["no data"] += 1
                        continue
                    df = to_long(obj, start, end, zone, dataset)
                    df.to_csv(path, index=False)
                    print(f"{path.name}: {len(df):,} rows")
                    counts["downloaded"] += 1
                    time.sleep(1)  # be gentle with the API
    print(f"\nDone: {counts['downloaded']} files downloaded, {counts['no data']} months without data, "
          f"{counts['failed']} failed" + (" - run the script again to retry them." if counts["failed"] else "."))


if __name__ == "__main__":
    main()
