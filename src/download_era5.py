"""
Download ERA5 hourly data for the Baltic Sea region from the Copernicus CDS.

Period: 2023-01 .. 2026-08, one request per month (resumable: finished months are skipped).
Variables: 100 m wind (u, v), 2 m temperature, surface solar radiation downwards.

Setup (once):
  1. pip install -U cdsapi
  2. Put your CDS personal access token into ~/.cdsapirc:
         url: https://cds.climate.copernicus.eu/api
         key: <PERSONAL-ACCESS-TOKEN>
  3. Accept the dataset licence on the "ERA5 hourly data on single levels" page.

Run from the repository root:  python src/download_era5.py
"""

import calendar
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DATASET = "reanalysis-era5-single-levels"
OUT_DIR = Path("data/raw/era5")
AREA = [70, 10, 53.5, 32]  # North, West, South, East: Baltics, Finland, S/C Sweden, N Poland
VARIABLES = [
    "100m_u_component_of_wind",
    "100m_v_component_of_wind",
    "2m_temperature",
    "surface_solar_radiation_downwards",
]
START = (2023, 1)
END = (2023, 2)  # set END = START to test with a single month first
MAX_WORKERS = 4  # parallel CDS requests


def months(start, end):
    """Yield (year, month) tuples from start to end, inclusive."""
    year, month = start
    while (year, month) <= end:
        yield year, month
        month += 1
        if month == 13:
            year, month = year + 1, 1


def build_request(year, month):
    n_days = calendar.monthrange(year, month)[1]
    return {
        "product_type": ["reanalysis"],
        "variable": VARIABLES,
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "day": [f"{d:02d}" for d in range(1, n_days + 1)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "data_format": "netcdf",
        # Instantaneous (wind, temperature) and accumulated (radiation) variables
        # are delivered as two separate .nc files, so we ask for a zip.
        "download_format": "zip",
        "area": AREA,
    }


def download_month(year, month):
    import cdsapi  # imported here so the rest of the module works without it

    tag = f"{year}_{month:02d}"
    month_dir = OUT_DIR / tag
    if any(month_dir.glob("*.nc")):
        return f"{tag}: already downloaded, skipped"

    month_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = OUT_DIR / f"era5_{tag}.download"
    cdsapi.Client().retrieve(DATASET, build_request(year, month), str(tmp_path))

    if zipfile.is_zipfile(tmp_path):
        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(month_dir)
        tmp_path.unlink()
    else:  # a single NetCDF file came back
        tmp_path.rename(month_dir / f"era5_{tag}.nc")
    return f"{tag}: done"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = list(months(START, END))
    print(f"Submitting {len(jobs)} monthly requests to the CDS ({MAX_WORKERS} at a time)...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(download_month, y, m): (y, m) for y, m in jobs}
        for future in as_completed(futures):
            year, month = futures[future]
            try:
                print(future.result())
            except Exception as exc:  # keep going; rerun the script to retry failed months
                print(f"{year}_{month:02d}: FAILED - {exc}")


if __name__ == "__main__":
    main()