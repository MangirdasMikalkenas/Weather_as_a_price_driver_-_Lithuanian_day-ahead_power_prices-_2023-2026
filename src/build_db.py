"""
Build the DuckDB database data/lt_power.duckdb from the files in data/ and the SQL in sql/.

The database is rebuilt from scratch on every run, so it never has to be edited by hand
and is not committed to Git. Sources that are not available yet are skipped and their
tables stay empty; the views still work and fill up once the data is there.

Run from the repository root:  python src/build_db.py
Use in a notebook:
    import duckdb
    con = duckdb.connect("data/lt_power.duckdb", read_only=True)
    df = con.sql("SELECT * FROM lt_hourly").df()
"""

import glob
from pathlib import Path

import duckdb

DB_PATH = Path("data/lt_power.duckdb")
SQL_DIR = Path("sql")
SCHEMA_FILE = "01_schema.sql"
VIEW_FILES = ["02_clean.sql", "03_analysis_table.sql", "04_quality_checks.sql", "05_capture_rates.sql"]

# table -> (file pattern, SELECT reading those files; {files} is replaced with the pattern)
SOURCES = {
    "entsoe_raw": (
        "data/raw/entsoe/*.csv",
        "SELECT ts_utc, zone, dataset, series, value FROM read_csv('{files}', header = true, "
        "types = {{'ts_utc': 'TIMESTAMP', 'value': 'DOUBLE'}})",
    ),
    "era5_regions": (
        "data/processed/era5_regions.csv",
        "SELECT ts_utc, region, wind_speed_100m_ms, wind_cf, t2m_c, ssrd_wm2 "
        "FROM read_csv('{files}', header = true, types = {{'ts_utc': 'TIMESTAMP'}})",
    ),
    "gas_daily": (
        "data/raw/gas/ttf_daily.csv",
        "SELECT trade_date, ttf_eur_mwh FROM read_csv('{files}', header = true, "
        "types = {{'trade_date': 'DATE', 'ttf_eur_mwh': 'DOUBLE'}})",
    ),
}


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.unlink(missing_ok=True)  # always start from an empty database
    con = duckdb.connect(str(DB_PATH))

    con.execute((SQL_DIR / SCHEMA_FILE).read_text())

    for table, (pattern, select) in SOURCES.items():
        if not glob.glob(pattern):
            print(f"{table}: no files at {pattern}, left empty")
            continue
        con.execute(f"INSERT INTO {table} {select.format(files=pattern)}")
        rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"{table}: {rows:,} rows loaded")

    for name in VIEW_FILES:
        con.execute((SQL_DIR / name).read_text())
        print(f"{name}: views created")

    print("\nData quality checks (0 = no problems found):")
    print(con.sql("SELECT * FROM qa_summary"))
    rows = con.execute("SELECT count(*) FROM lt_hourly").fetchone()[0]
    print(f"lt_hourly: {rows:,} hours ready for analysis")
    con.close()


if __name__ == "__main__":
    main()
