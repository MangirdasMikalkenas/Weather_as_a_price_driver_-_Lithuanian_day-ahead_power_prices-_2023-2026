"""
Download ERA5 hourly data for the Baltic Sea region from the Copernicus CDS.

Period: 2023-01 .. 2026-08, one request per month. The script is resumable: a month
counts as finished only when its completion marker exists, and the marker is written
after the download and the extraction have both succeeded.
Variables: 100 m wind (u, v), 2 m temperature, surface solar radiation downwards.

Network and HTTP errors are retried automatically by the cdsapi client itself.
If a month still fails (e.g. the request fails on the CDS side), re-run the script.

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

import cdsapi

DATASET = "reanalysis-era5-single-levels"
OUT_DIR = Path("data/raw/era5")
AREA = [66, 10, 53.5, 30]  # North, West, South, East: Baltics, Finland, S/C Sweden, N Poland
VARIABLES = [
    "100m_u_component_of_wind",
    "100m_v_component_of_wind",
    "2m_temperature",
    "surface_solar_radiation_downwards",
]
START = (2023, 1)
END = (2026, 8)  # set END = START to test with a single month first
MAX_WORKERS = 4  # parallel CDS requests
DONE_MARKER = ".download_complete"


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
    tag = f"{year}_{month:02d}"
    month_dir = OUT_DIR / tag
    marker = month_dir / DONE_MARKER
    if marker.exists():
        return f"{tag}: already downloaded, skipped"

    month_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = OUT_DIR / f"era5_{tag}.zip.part"
    try:
        cdsapi.Client().retrieve(DATASET, build_request(year, month), str(tmp_path))
        if not zipfile.is_zipfile(tmp_path):
            raise RuntimeError("downloaded file is not a valid zip archive")
        with zipfile.ZipFile(tmp_path) as zf:
            bad_member = zf.testzip()  # verifies the checksum of every file in the archive
            if bad_member is not None:
                raise RuntimeError(f"corrupted file in archive: {bad_member}")
            for old_file in month_dir.glob("*.nc"):  # leftovers of an interrupted attempt
                old_file.unlink()
            zf.extractall(month_dir)
    finally:
        tmp_path.unlink(missing_ok=True)  # never leave partial downloads behind

    marker.touch()  # written only after download and extraction have both succeeded
    return f"{tag}: done"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = list(months(START, END))
    print(f"Submitting {len(jobs)} monthly requests to the CDS ({MAX_WORKERS} at a time)...")
    failed = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(download_month, y, m): (y, m) for y, m in jobs}
        for future in as_completed(futures):
            year, month = futures[future]
            try:
                print(future.result())
            except Exception as exc:
                failed.append(f"{year}_{month:02d}")
                print(f"{year}_{month:02d}: FAILED - {exc}")

    if failed:
        print(f"{len(failed)} month(s) failed: {', '.join(sorted(failed))}. Re-run the script to retry them.")
    else:
        print("All months downloaded.")


if __name__ == "__main__":
    main()
