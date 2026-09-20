"""
Download daily TTF natural gas prices from Yahoo Finance.

Ticker TTF=F is the Dutch TTF Natural Gas Calendar Month future, quoted in EUR/MWh.
The front-month contract rolls every month, so this is a proxy for the gas price level.
Yahoo data is for personal use only, so the file stays in data/ and is not committed.

Output: data/raw/gas/ttf_daily.csv with the columns expected by sql/01_schema.sql:
        trade_date, ttf_eur_mwh

Requirements: pip install yfinance
Run from the repository root:  python src/download_gas.py
"""

from pathlib import Path

import yfinance as yf

TICKER = "TTF=F"
START = "2022-12-01"  # a month early, so that 1 January 2023 has a previous close
END = "2026-09-01"    # exclusive
OUT_FILE = Path("data/raw/gas/ttf_daily.csv")


def main():
    df = yf.download(TICKER, start=START, end=END, auto_adjust=False, progress=False)
    if df.empty:
        raise SystemExit("No data returned. Check your internet connection or try again later.")

    close = df["Close"]
    if close.ndim == 2:  # newer yfinance versions return one column per ticker
        close = close[TICKER]

    out = close.dropna().rename("ttf_eur_mwh").rename_axis("trade_date").reset_index()
    out["trade_date"] = out["trade_date"].dt.date

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_FILE, index=False, float_format="%.3f")
    print(f"Wrote {len(out)} trading days to {OUT_FILE}: {out['trade_date'].min()} .. {out['trade_date'].max()}")
    print(out["ttf_eur_mwh"].describe().round(2))


if __name__ == "__main__":
    main()
