"""
Download euro-area interest rates and the EUR/USD exchange rate from the ECB Data Portal (no key needed).

Output, in data/raw/ecb/:
    yield_curve.csv  date, curve, tenor_years, rate_pct
                     zero-coupon (spot) rates, Svensson model, continuously compounded, in %, for two curves:
                     AAA: AAA-rated euro-area central government bonds (a proxy for the risk-free curve)
                     all: all euro-area central government bonds, so it moves with sovereign spreads
    eurusd.csv       date, usd_per_eur            ECB euro foreign exchange reference rate (US dollars per euro)

Notebook 05 uses them for a small bank portfolio (a bond, an interest rate swap and an FX forward) and for the
supervisory interest rate shocks of IRRBB. ECB statistics may be reused with the source acknowledged.

Run from the repository root:  python src/download_ecb.py
"""

import io
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path("data/raw/ecb")
START, END = "2015-01-01", "2026-09-30"
API = "https://data-api.ecb.europa.eu/service/data"
CURVES = {"AAA": "G_N_A", "all": "G_N_C"}
TENORS = {"3M": 0.25, "6M": 0.5, "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7, "10Y": 10, "15Y": 15, "20Y": 20, "30Y": 30}


def fetch(flow, key):
    """One ECB series request in SDMX-CSV; the KEY column identifies each series."""
    response = requests.get(f"{API}/{flow}/{key}", params={"startPeriod": START, "endPeriod": END, "format": "csvdata"},
                            timeout=120)
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    frames = []
    for name, instrument in CURVES.items():
        raw = fetch("YC", f"B.U2.EUR.4F.{instrument}.SV_C_YM." + "+".join(f"SR_{t}" for t in TENORS))
        tenor = raw["KEY"].str.rsplit(".", n=1).str[-1].str.removeprefix("SR_")
        frames.append(pd.DataFrame({"date": pd.to_datetime(raw["TIME_PERIOD"]).dt.date, "curve": name,
                                    "tenor_years": tenor.map(TENORS),
                                    "rate_pct": pd.to_numeric(raw["OBS_VALUE"], errors="coerce")}).dropna())
    curve = pd.concat(frames).sort_values(["curve", "date", "tenor_years"])
    curve.to_csv(OUT_DIR / "yield_curve.csv", index=False)
    for name, part in curve.groupby("curve"):
        complete = part.groupby("date")["tenor_years"].count().eq(len(TENORS)).sum()
        print(f"yield_curve.csv, {name}: {part['date'].nunique():,} days ({complete:,} with all {len(TENORS)} tenors), "
              f"{part['date'].min()} .. {part['date'].max()}")

    raw = fetch("EXR", "D.USD.EUR.SP00.A")
    fx = pd.DataFrame({"date": pd.to_datetime(raw["TIME_PERIOD"]).dt.date,
                       "usd_per_eur": pd.to_numeric(raw["OBS_VALUE"], errors="coerce")}).dropna().sort_values("date")
    fx.to_csv(OUT_DIR / "eurusd.csv", index=False)
    print(f"eurusd.csv: {len(fx):,} days, {fx['date'].min()} .. {fx['date'].max()}")


if __name__ == "__main__":
    main()
