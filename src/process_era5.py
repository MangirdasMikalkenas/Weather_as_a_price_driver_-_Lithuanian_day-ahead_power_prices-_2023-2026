"""
Turn the ERA5 grid into hourly weather indices per country.

Input : data/raw/era5/YYYY_MM/*.nc  (written by download_era5.py)
Output: data/processed/era5_regions.csv with the columns expected by sql/01_schema.sql:
        ts_utc, region, wind_speed_100m_ms, wind_cf, t2m_c, ssrd_wm2

How the indices are built:
- A region is the land area of a country (Natural Earth borders, via regionmask),
  so offshore wind farms are not represented.
- Averages are area-weighted: ERA5 grid cells get smaller towards the north.
- wind_cf: a generic turbine power curve is applied to the 100 m wind in every grid cell
  and the result is averaged. It is an index of the onshore wind resource, not actual output.
- ssrd is accumulated over the hour BEFORE its timestamp. It is shifted back by one hour,
  so every value describes the hour that starts at ts_utc - the same convention as prices.

Requirements: pip install regionmask   (downloads the Natural Earth borders on first run)
Run from the repository root:  python src/process_era5.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import regionmask
import xarray as xr

RAW_DIR = Path("data/raw/era5")
OUT_FILE = Path("data/processed/era5_regions.csv")

REGIONS = {
    "LT": "Lithuania", "LV": "Latvia", "EE": "Estonia", "FI": "Finland", "SE": "Sweden",
    "NO": "Norway", "DK": "Denmark", "PL": "Poland", "DE": "Germany",
}

# Generic modern onshore turbine: cut-in, rated and cut-out wind speed (m/s)
V_IN, V_RATED, V_OUT = 3.0, 12.0, 25.0


def capacity_factor(wind_speed):
    """Share of rated power (0..1): cubic rise from cut-in to rated, zero above cut-out."""
    cf = ((wind_speed**3 - V_IN**3) / (V_RATED**3 - V_IN**3)).clip(0, 1)
    return cf.where((wind_speed >= V_IN) & (wind_speed < V_OUT), 0.0)


def load_month(month_dir):
    """Return the (instantaneous, accumulated) datasets of one month, whatever the file names."""
    instant = accum = None
    for path in sorted(month_dir.glob("*.nc")):
        with xr.open_dataset(path) as ds:
            ds = ds.load()
        if "valid_time" in ds.coords:
            ds = ds.rename({"valid_time": "time"})
        ds = ds.drop_vars(["number", "expver"], errors="ignore")
        if "u100" in ds:
            instant = ds
        elif "ssrd" in ds:
            accum = ds
    if instant is None or accum is None:
        raise RuntimeError(f"{month_dir.name}: expected one instantaneous and one accumulated file")
    return instant, accum


def region_weights(lon, lat):
    """Weights (region, latitude, longitude): cos(latitude) inside a country, 0 elsewhere."""
    countries = regionmask.defined_regions.natural_earth_v5_0_0.countries_50
    numbers = [countries.map_keys(name) for name in REGIONS.values()]
    mask = countries.mask_3D(lon, lat).sel(region=numbers)
    mask = mask.drop_vars(["names", "abbrevs"], errors="ignore").assign_coords(region=list(REGIONS))
    cells = mask.sum(("latitude", "longitude")).to_series()
    print("Grid cells per region:", cells.to_dict())
    if (cells == 0).any():
        raise RuntimeError("Some regions have no grid cells - check AREA in download_era5.py")
    return mask * np.cos(np.deg2rad(lat))


def regional_means(ds, weights):
    """Area-weighted mean of every variable for every region -> long DataFrame."""
    means = ds.weighted(weights).mean(("latitude", "longitude"))
    df = means.to_dataframe().reset_index().rename(columns={"time": "ts_utc"})
    return df[["ts_utc", "region", *ds.data_vars]]


def main():
    month_dirs = sorted(d for d in RAW_DIR.iterdir() if (d / ".download_complete").exists())
    if not month_dirs:
        raise SystemExit(f"No finished months in {RAW_DIR}. Run download_era5.py first.")
    print(f"Processing {len(month_dirs)} months: {month_dirs[0].name} .. {month_dirs[-1].name}")

    first_instant, _ = load_month(month_dirs[0])
    weights = region_weights(first_instant.longitude, first_instant.latitude)

    instant_parts, accum_parts = [], []
    for month_dir in month_dirs:
        instant, accum = load_month(month_dir)

        wind_speed = np.sqrt(instant["u100"] ** 2 + instant["v100"] ** 2)
        inst = xr.Dataset({
            "wind_speed_100m_ms": wind_speed,
            "wind_cf": capacity_factor(wind_speed),
            "t2m_c": instant["t2m"] - 273.15,
        })
        acc = xr.Dataset({"ssrd_wm2": accum["ssrd"] / 3600})               # J/m2 per hour -> W/m2
        acc = acc.assign_coords(time=acc["time"] - pd.Timedelta(hours=1))  # label by hour start

        instant_parts.append(regional_means(inst, weights))
        accum_parts.append(regional_means(acc, weights))
        print(f"{month_dir.name}: done")

    df = pd.concat(instant_parts).merge(pd.concat(accum_parts), on=["ts_utc", "region"], how="left")
    df = df.sort_values(["region", "ts_utc"])

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False, float_format="%.4f")
    print(f"\nWrote {len(df):,} rows to {OUT_FILE}")
    print(df.groupby("region")[["wind_speed_100m_ms", "wind_cf", "t2m_c", "ssrd_wm2"]].mean().round(2))


if __name__ == "__main__":
    main()
