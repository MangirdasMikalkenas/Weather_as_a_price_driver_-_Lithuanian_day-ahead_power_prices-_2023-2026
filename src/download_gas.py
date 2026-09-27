"""
Download daily TTF natural gas prices and a carbon price proxy from Yahoo Finance.

Ticker TTF=F is the Dutch TTF Natural Gas Calendar Month future, quoted in EUR/MWh.
The front-month contract rolls every month, so this is a proxy for the gas price level.
Ticker KRBN is an exchange-traded fund that holds carbon allowance futures, of which EU
allowances (EUA) are the largest part; it is quoted in USD and used only as a proxy for how the
carbon price moves. (KEUA, a fund of EU allowances only, is no longer listed on Yahoo Finance.)
Yahoo data is for personal use only, so the files stay in data/ and are not committed.

Output (columns expected by sql/01_schema.sql):
    data/raw/gas/ttf_daily.csv        trade_date, ttf_eur_mwh
    data/raw/gas/eua_proxy_daily.csv  trade_date, eua_proxy

Requirements: pip install yfinance
Run from the repository root:  python src/download_gas.py
"""

from pathlib import Path

import yfinance as yf

START = "2022-12-01"  # a month early, so that 1 January 2023 has a previous close
END = "2026-09-27"    # exclusive
TICKERS = {  # ticker -> (output file, value column)
    "TTF=F": (Path("data/raw/gas/ttf_daily.csv"), "ttf_eur_mwh"),
    "KRBN": (Path("data/raw/gas/eua_proxy_daily.csv"), "eua_proxy"),
}


def main():
    for ticker, (out_file, column) in TICKERS.items():
        df = yf.download(ticker, start=START, end=END, auto_adjust=False, progress=False)
        if df.empty:
            print(f"{ticker}: no data returned. Check your internet connection or try again later.")
            continue

        close = df["Close"]
        if close.ndim == 2:  # newer yfinance versions return one column per ticker
            close = close[ticker]

        out = close.dropna().rename(column).rename_axis("trade_date").reset_index()
        out["trade_date"] = out["trade_date"].dt.date

        out_file.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(out_file, index=False, float_format="%.3f")
        print(f"{ticker}: {len(out)} trading days to {out_file}: {out['trade_date'].min()} .. {out['trade_date'].max()}")


if __name__ == "__main__":
    main()
