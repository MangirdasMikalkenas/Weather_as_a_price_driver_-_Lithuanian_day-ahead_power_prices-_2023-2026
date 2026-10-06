# Weather as a price driver: Lithuanian day-ahead power prices, 2023–2026

This project measures how the weather moves the Lithuanian day-ahead electricity price, what wind and solar output is worth, and how accurately tomorrow's prices can be forecast from public data. It joins 32,135 hourly prices (January 2023 – August 2026, with September 2026 kept as a clean forecast test) with ERA5 weather, ENTSO-E grid data and fuel prices. Wind across the Baltic Sea region is the weather variable that moves the price most, and the size of its effect depends strongly on interconnector availability; solar's market value has fallen sharply while wind's has not; and a forecast built only on information available before the auction has a 41% lower error than repeating yesterday's prices. The full results, with recommendations for a trading desk and an asset owner, are in **[results_analysis.md](results_analysis.md)**. It also backtests its own uncertainty estimates the way banks test Value-at-Risk models ([notebook 04](notebooks/04_risk_backtesting.ipynb), [section 14 of the analysis](results_analysis.md#14-the-80-intervals-under-predict-price-spikes-and-a-250-day-cash-flow-at-risk-for-a-solar-ppa-fails-in-summer)).

**For a model-validation reader:** [VALIDATION_SUMMARY.md](VALIDATION_SUMMARY.md) rates the models and their backtests on one page, with decisions and findings by severity.

## Key results

- A typical windy hour was 17 €/MWh (19%) cheaper than a typical calm one (−7.6 €/MWh per +10 percentage points of Baltic wind capacity factor), and Nordic wind moved the price about as much as Baltic wind (−7.4 against −7.6 €/MWh, with overlapping confidence intervals).
- While the Estlink 2 cable was out (December 25, 2024 – June 20, 2025), +10 percentage points of wind were associated with an extra price reduction of 5.1–8.1 €/MWh, depending on the specification, in a single 177-day event; the turbines added in 2024–2025 did not change the effect.
- Solar's capture rate fell from 0.87 to 0.54 between January–August 2023 and January–August 2026, while wind's showed no downward trend; wind farms held back 18% of their output in negative-price hours, 0.8% of their 2025 production.
- The forecast's mean absolute error was 24.8 €/MWh against 41.8 €/MWh for repeating yesterday's prices; an improved version was a further 5% better on September 2026 (Diebold–Mariano p < 0.001, Giacomini–White p = 0.070), and a battery scheduled with the forecast earned 89% of the perfect-foresight profit.
- Replacing the wind forecast with the wind that actually blew made the day-ahead forecast 4% worse (p = 0.003), consistent with the auction pricing expectations rather than outcomes; this tests perfect hindsight, not a better forecast made before the auction.
- In backtests with exact binomial, Christoffersen, Basel traffic-light and Acerbi–Szekely tests, the forecast's 80% intervals under-predicted price spikes (the price exceeded the upper bound in 13.5% of hours against 10%), and a 99% cash-flow-at-risk for a solar PPA based on 250 days of history failed in summer (40 exceptions in 974 days against about 10); volatility scaling cut the exceptions to 24 and a full year of history to 14.

Eleven hypotheses were tested: six were supported, two partly supported and three not supported ([Appendix B of the analysis](results_analysis.md#appendix-b-hypotheses-and-verdicts)).

## Contents

- [Repository structure](#repository-structure)
- [Quick start](#quick-start)
- [Setup](#setup)
- [Data pipeline](#data-pipeline)
- [Database](#database)
- [Notebooks](#notebooks)
- [Updating to newer data](#updating-to-newer-data)
- [Reproducibility](#reproducibility)
- [Troubleshooting](#troubleshooting)
- [Data sources and attribution](#data-sources-and-attribution)
- [License](#license)

## Repository structure

```text
.
├── README.md
├── results_analysis.md          # results, recommendations and interpretation (top-down)
├── VALIDATION_SUMMARY.md        # one-page validation summary: decisions and findings by severity
├── requirements.txt             # the complete tested environment (pip freeze)
├── src/                         # data download, processing and database build
│   ├── download_entsoe.py
│   ├── download_era5.py
│   ├── process_era5.py
│   ├── download_gas.py
│   └── build_db.py
├── sql/                         # database schema, cleaning, analysis table, quality checks
│   ├── 01_schema.sql
│   ├── 02_clean.sql
│   ├── 03_analysis_table.sql
│   ├── 04_quality_checks.sql
│   └── 05_capture_rates.sql
├── notebooks/                   # code and section titles only; interpretation is in results_analysis.md
│   ├── 01_price_drivers.ipynb   # question 1: what drives the price (H1–H5)
│   ├── 02_wind_value.ipynb      # question 2: what wind and solar are worth (H6–H7)
│   ├── 03_forecast.ipynb        # question 3: forecasting tomorrow's prices (H8–H9)
│   └── 04_risk_backtesting.ipynb # backtesting the uncertainty: intervals and a solar PPA cash-flow-at-risk (H10–H11)
├── figures/                     # charts (SVG and PNG) and summary tables (CSV) written by the notebooks
└── data/                        # not committed: downloads, processed ERA5, database, forecast cache
    ├── raw/entsoe/              # one CSV per dataset, zone and month
    ├── raw/era5/                # one folder of NetCDF files per month
    ├── raw/gas/                 # TTF gas and the carbon price proxy
    ├── processed/era5_regions.csv
    ├── processed/q3_cache/      # stored forecasts of notebook 03, keyed by the code and data that produced them
    └── lt_power.duckdb          # rebuilt by src/build_db.py
```

`data/` and the credentials file `.env` are not committed and should stay in `.gitignore`.

## Quick start

Requires Python 3.12 (the results were produced with 3.12.3). All commands run from the repository root.

```bash
python3.12 -m venv .venv             # Python 3.12 (tested with 3.12.3); Windows: py -3.12 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# credentials (see Setup): ENTSOE_API_KEY in .env, Copernicus CDS token in ~/.cdsapirc

python src/download_entsoe.py        # ENTSO-E prices, generation, load, forecasts, reservoirs, capacities
python src/download_era5.py          # ERA5 weather grid, one request per month
python src/process_era5.py           # ERA5 grid -> hourly indices per country
python src/download_gas.py           # TTF gas and the carbon price proxy
python src/build_db.py               # rebuilds data/lt_power.duckdb and runs the quality checks

# run notebooks/01–04 in order with "Run All" in VS Code (Jupyter extension) or JupyterLab
```

| Step | Typical run time |
|---|---|
| `download_entsoe.py`, first run | 1–3 hours (about 3,000 monthly requests); later runs download only missing months |
| `download_era5.py` | several hours, depending on the Copernicus request queue |
| `process_era5.py` | a few minutes |
| `download_gas.py` | seconds |
| `build_db.py` | under a minute |
| Notebook 01 | a few minutes |
| Notebook 02 | under a minute |
| Notebook 03, first run | about 1.5–2 hours; later runs 5–8 minutes from the stored results |
| Notebook 04 | under a minute (it reads the stored results of notebook 03) |

## Setup

**Python.** The project was developed with Python 3.12.3. `requirements.txt` is the complete environment the results were produced with (`pip freeze`). The notebooks run in VS Code with the Jupyter extension; for JupyterLab, also run `pip install jupyterlab`.

**ENTSO-E token.** Register on the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/), request a RESTful API token and put it into a file `.env` in the repository root:

```text
ENTSOE_API_KEY=<your-token>
```

**Copernicus CDS token.** Create an account on the [Climate Data Store](https://cds.climate.copernicus.eu/), put your personal access token into `~/.cdsapirc` and accept the licence on the "ERA5 hourly data on single levels" page:

```text
url: https://cds.climate.copernicus.eu/api
key: <PERSONAL-ACCESS-TOKEN>
```

**Internet access** is also needed on the first run of `process_era5.py`, which downloads the Natural Earth country borders through `regionmask`.

## Data pipeline

### 1. ENTSO-E data: `src/download_entsoe.py`

Downloads ENTSO-E Transparency Platform data for Lithuania and the neighboring bidding zones through `entsoe-py`.

| Dataset | Zones | From | Content |
|---|---|---|---|
| `da_price` | LT, LV, EE, FI, SE_4, PL | 2023 | day-ahead prices; hourly until September 30, 2025, 15-minute from October 1, 2025 (SDAC 15-minute MTU), stored as published and aggregated to hours in SQL |
| `generation` | LT | 2023 | actual generation per production type (net) |
| `load` | LT | 2023 | actual total load |
| `load_forecast` | LT, LV, EE, FI, SE_3, SE_4, PL, DE_LU | 2023 | day-ahead load forecasts |
| `wind_solar_forecast` | LT, LV, EE, FI, SE_3, SE_4, PL, DE_LU | 2023 | day-ahead wind and solar forecasts |
| `hydro_reservoirs` | NO_1–NO_5, SE_1–SE_4, FI | 2015 | weekly stored energy (MWh); 2015–2022 only define the "normal" level of each week |
| `offered_capacity` | ten Baltic border directions | 2023 | capacity offered to the day-ahead market coupling (implicit allocation), an input to the auction |

- **Output.** One CSV per dataset, zone and month in `data/raw/entsoe/` (`dataset_zone_YYYY_MM.csv`), in a tidy long format: `ts_utc, zone, dataset, series, value`. All timestamps are converted to UTC and mark the start of the interval.
- **Borders** are written FROM-TO: `SE_4-LT` is the capacity from SE4 into Lithuania. The ten directions are SE_4↔LT, PL↔LT, LV↔LT, EE↔LV and FI↔EE. ENTSO-E publishes no day-ahead NTC for these borders, so the offered capacity is used instead.
- **Period.** Data run to September 26, 2026 (`END` is exclusive), so that September 2026 can serve as a fresh test period for the price forecasts. Files from an earlier download with one file per year (`dataset_zone_YYYY.csv`, up to August 2026) are kept; only the months from `EXTEND_FROM` onwards are added to them as monthly files.
- **Resumable.** Existing files are skipped, so a re-run downloads only what is missing; delete a file to download it again. Server errors are retried after 10 and 30 seconds; a month that still fails is reported and retried on the next run. A month that ENTSO-E has no data for is reported as "no data".
- **Security.** The API token never appears in printed messages; error URLs are masked.

### 2. ERA5 weather download: `src/download_era5.py`

Downloads ERA5 hourly data ("reanalysis-era5-single-levels") for the Baltic Sea region from the Copernicus Climate Data Store.

- **Period.** January 2023 – August 2026, one request per month.
- **Area.** 71.5°N, 4°E to 47°N, 32°E (the Nordic countries, the Baltic states, Poland and Germany).
- **Variables.** 100 m wind (u and v components), 2 m temperature, surface solar radiation downwards.
- **Format.** NetCDF in a zip: instantaneous variables (wind, temperature) and accumulated ones (radiation) arrive as two separate files, extracted to `data/raw/era5/YYYY_MM/`.
- **Resumable.** A month counts as finished only when its marker file `.download_complete` exists, written after both the download and the extraction have succeeded; the zip is checked before extraction and partial downloads are removed. Network and HTTP errors are retried by the `cdsapi` client; if a month still fails, re-run the script.
- **Parallel requests.** Four at a time (`MAX_WORKERS`). To test the setup with a single month first, set `END = START`.

### 3. ERA5 processing: `src/process_era5.py`

Turns the ERA5 grid into hourly weather indices for nine countries: LT, LV, EE, FI, SE, NO, DK, PL and DE.

- **Output.** `data/processed/era5_regions.csv` with the columns `ts_utc, region, wind_speed_100m_ms, wind_cf, t2m_c, ssrd_wm2`.
- **Regions.** The land area of each country (Natural Earth borders via `regionmask`), so offshore wind farms are not represented.
- **Averaging.** Area-weighted by the cosine of latitude, because ERA5 grid cells get smaller towards the north.
- **Wind capacity factor (`wind_cf`).** A generic onshore turbine power curve is applied to the 100 m wind in every grid cell and the result is averaged: output rises with the cube of the wind speed from the cut-in speed (3 m/s) to the rated speed (12 m/s) and is zero above the cut-out speed (25 m/s). It is an index of the onshore wind resource, not actual output.
- **Solar radiation (`ssrd_wm2`).** ERA5 accumulates radiation over the hour before its timestamp, in J/m². The values are divided by 3,600 to give W/m² and shifted back by one hour, so every value describes the hour that starts at `ts_utc`, the same convention as prices.

### 4. Gas and carbon prices: `src/download_gas.py`

Downloads daily closing prices from Yahoo Finance through `yfinance`.

| Ticker | Output | Meaning |
|---|---|---|
| `TTF=F` | `data/raw/gas/ttf_daily.csv` (`trade_date, ttf_eur_mwh`) | Dutch TTF natural gas front-month future, EUR/MWh; the contract rolls every month, so it is a proxy for the gas price level |
| `KRBN` | `data/raw/gas/eua_proxy_daily.csv` (`trade_date, eua_proxy`) | an exchange-traded fund holding carbon allowance futures, of which EU allowances are the largest part; quoted in USD and used only as a proxy for how the carbon price moves (KEUA, a fund of EU allowances only, is no longer listed on Yahoo Finance) |

The download starts a month early (December 1, 2022), so that January 1, 2023 has a previous close; `END` is exclusive. Yahoo Finance data are for personal use only, so the files stay in `data/` and are not committed.

### 5. Database: `src/build_db.py`

Builds the DuckDB database `data/lt_power.duckdb` from the files in `data/` and the SQL in `sql/`.

- The database is rebuilt from scratch on every run, so it never has to be edited by hand and is not committed.
- Sources that are not available yet are skipped and their tables stay empty; the views still work and fill up once the data are there.
- The SQL files run in order: `01_schema.sql` (tables), then `02_clean.sql`, `03_analysis_table.sql`, `04_quality_checks.sql` and `05_capture_rates.sql` (views).
- At the end the script prints the data quality checks and the number of hours in the analysis tables. A complete build prints the following (the quality-check table is shown in a simplified layout):

```text
entsoe_raw: 3,653,479 rows loaded
era5_regions: 289,224 rows loaded
gas_daily: 959 rows loaded
eua_daily: 957 rows loaded

Data quality checks (0 = no problems found):
missing LT price hours                   0
incomplete price hours                   0
duplicate raw rows                       0
prices out of range                      0
gaps in ERA5 series                      0
hydro weeks missing a zone (excluded)    7
load forecast hours cleaned (excluded)   174
load forecast hours cleaned before the auction   283

lt_hourly: 32,135 hours ready for analysis (questions 1-2, to August 2026)
lt_hourly_all: 32,759 hours (question 3, all available data)
```

The number of raw ENTSO-E rows can change slightly when ENTSO-E revises its data; `lt_hourly` should always have 32,135 hours.

## Database

All timestamps are UTC and mark the start of the interval they describe. MW values are averaged within the hour, so an hourly MW value equals the MWh of that hour.

| Layer | Object | Content |
|---|---|---|
| Raw tables (`01_schema.sql`) | `entsoe_raw` | all ENTSO-E data in long format |
| | `era5_regions` | hourly weather indices per country |
| | `gas_daily`, `eua_daily` | daily TTF gas and carbon proxy closes |
| Cleaned views (`02_clean.sql`) | `price_hourly`, `price_hourly_wide` | hourly day-ahead prices per zone (15-minute prices averaged), long and one column per zone |
| | `lt_generation_hourly` | Lithuanian generation by type; storage is net (negative while pumping or charging) |
| | `lt_load_hourly` | Lithuanian actual load and day-ahead forecast. A forecast of zero is a data error. `load_forecast_mw` also removes forecasts that miss the actual load of the same hour by more than 50%, which uses the outcome and serves notebooks 01–02 only; `load_forecast_exante_mw` instead compares with the actual load of the same hour a week earlier, known at the auction, and feeds the forecasts of notebook 03 |
| | `lt_res_forecast_hourly` | Lithuanian day-ahead wind and solar forecasts |
| | `forecast_hourly_zone` | day-ahead load, wind and solar forecasts per zone |
| | `ntc_hourly_border` | capacity offered to the day-ahead market coupling, per border and hour |
| | `weather_hourly` | ERA5 wind indices for every region, temperature and solar radiation for Lithuania |
| | `hydro_weekly` | Nordic reservoir levels per week against the 2015–2022 normal of the same week |
| Analysis views (`03_analysis_table.sql`) | `lt_hourly_all` | one row per hour with a Lithuanian price and everything known about that hour; all available hours (notebook 03) |
| | `lt_hourly` | the same, fixed to January 2023 – August 2026 (notebooks 01–02), so new data do not change their results |
| Quality checks (`04_quality_checks.sql`) | `qa_*`, `qa_summary` | missing and incomplete price hours, duplicates, prices outside the SDAC limits (−500 to +4,000 €/MWh), ERA5 gaps, incomplete hydro weeks, removed load forecasts |
| Capture rates (`05_capture_rates.sql`) | `capture_rates_monthly` | monthly capture prices and capture rates of wind and solar |

To use the database in Python:

```python
import duckdb

con = duckdb.connect("data/lt_power.duckdb", read_only=True)
df = con.sql("SELECT * FROM lt_hourly").df()
```

## Notebooks

The notebooks contain code and section titles only; the interpretation of every result is in [results_analysis.md](results_analysis.md), which refers to notebook sections as, for example, (01 §8.11). Each notebook saves its charts to `figures/` twice, as SVG (used in the analysis, sharp at any size) and PNG, together with CSV summary tables.

| Notebook | Question | Hypotheses | Data | Outputs |
|---|---|---|---|---|
| `01_price_drivers.ipynb` | How, and by how much, does the weather change the price? | H1–H5 | `lt_hourly` | 5 charts, `q1_summary.csv`, `q1_followup.csv` |
| `02_wind_value.ipynb` | What are wind and solar output worth, and how much wind output is held back at negative prices? | H6–H7 | `lt_hourly`, `capture_rates_monthly` | 5 charts, `q2_summary.csv` |
| `03_forecast.ipynb` | How accurately can tomorrow's hourly prices be forecast, and what is better information worth? | H8–H9 | `lt_hourly_all` and the neighbors' forecasts, capacities and carbon proxy | 8 charts, `q3_summary.csv`, `q3_followup.csv`, `q3_v2_summary.csv` |
| `04_risk_backtesting.ipynb` | How reliable are the uncertainty estimates: the forecast's 80% intervals and the cash-flow-at-risk of a solar PPA? | H10–H11 | `lt_hourly_all` and the stored intervals of notebook 03 | 3 charts, `q4_summary.csv` |

A complete run writes 49 files to `figures/`: 21 charts in two formats and 7 CSV tables.

**Notebook 03 in more detail.**

- **Information set.** Only information known at 12:00 CET on the day before delivery, the day-ahead auction deadline; days follow the auction's CET clock, and automatic checks confirm that no input uses later information (day-ahead wind and solar forecasts may be published after the auction; see section 14 of the analysis).
- **Periods.** Training to September 2025; validation October–December 2025 (settings only); test January–August 2026; clean test September 1–26, 2026, used for no decision.
- **Models.** A naive benchmark (yesterday's prices; last week's on Mondays and weekends), Lasso with one model per delivery hour, LightGBM, their average (fixed in advance as the main model), and an improved version (v2) chosen on the validation period; 80% prediction intervals by quantile regression averaging; a battery schedule optimized by linear programming.
- **Run time and cache.** The first full run takes about 1.5–2 hours. Long results are stored in `data/processed/q3_cache/` under a key that hashes the model code, the model inputs and the settings, so a change to any of them recomputes the affected results automatically and later runs take 5–8 minutes. Each stored result prints when, at which git commit and in how long it was computed, together with the warnings it raised and the Lasso safeguard counts; warnings are counted, not hidden. Deleting the folder forces a full recomputation. Setting `FAST = True` at the top runs a quick test of about 5 minutes with monthly re-training.
- **Determinism.** Results are reproducible for the same data: `SEED = 42`, LightGBM runs with `deterministic=True`, and Lasso runs single-threaded. A full re-run reproduced every number except v2's Lasso forecasts for September, whose error moved by 0.005 €/MWh, most likely because floating-point differences can change which of two nearly equal penalties the AIC selects.

## Updating to newer data

1. Move `END` (and `EXTEND_FROM`, the end of the previous download) in `src/download_entsoe.py`, `END` in `src/download_gas.py` and `END` in `src/download_era5.py`, then re-run the pipeline.
2. `lt_hourly` stays fixed at January 2023 – August 2026, so notebooks 01–02 keep their results; to extend them, change the date in `sql/03_analysis_table.sql`.
3. Re-run notebook 03; it recomputes its stored results automatically when the data or the code change. Any new model version should be judged only on data after September 26, 2026, the last day already used.

## Reproducibility

- **Provenance.** Every stored result of notebook 03 records its date, the git commit of the code and the warnings of its computation. Running the notebook from a committed state lets the commit identify the code exactly; the label notes uncommitted changes to `sql/` or `src/`.
- **Data vintages.** ENTSO-E revises published data, the most recent ERA5 months are preliminary (ERA5T) and Yahoo Finance history can be adjusted, so a rebuild at a later date may differ slightly from the committed results.
- **Fixed analysis period.** Notebooks 01–02 read `lt_hourly`, fixed to January 2023 – August 2026, so adding newer data does not change their results.
- **Packages.** `requirements.txt` pins every installed package to the version the results were produced with.

## Troubleshooting

| Message or symptom | Cause and fix |
|---|---|
| `ENTSOE_API_KEY not found` | Add the token to `.env` in the repository root. |
| `...: no data` in `download_entsoe.py` | ENTSO-E publishes nothing for that zone and month; nothing to fix. |
| `...: FAILED` in `download_entsoe.py` | A server error persisted after the retries; re-run the script, which retries only missing months. |
| A month fails in `download_era5.py` | Re-run the script; finished months are skipped. |
| `Some regions have no grid cells` | The ERA5 area does not cover a country; check `AREA` in `download_era5.py`. |
| `lt_hourly` does not have 32,135 hours | Some ENTSO-E or ERA5 months are missing; re-run the downloads and `build_db.py`. |
| Notebook 03 takes too long | Use `FAST = True` for a test run; the full results are stored after the first run. |
| Old charts in `figures/` | Delete the folder's contents and re-run the notebooks; every current file is recreated. |
| `No intervals in data/processed/q3_cache` in notebook 04 | Run notebook 03 with `FAST = False` first; notebook 04 reads the intervals it stores. |

## Data sources and attribution

- **ENTSO-E Transparency Platform** (https://transparency.entsoe.eu/): day-ahead prices, generation, load, day-ahead forecasts, hydro reservoir levels and offered capacities. The raw data are not included in this repository; download them with your own token under the platform's terms of use.
- **ERA5 hourly data on single levels** (Hersbach et al., 2023; https://doi.org/10.24381/cds.adbb2d47). *Contains modified Copernicus Climate Change Service information 2026. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains.*
- **Natural Earth** country borders (public domain), accessed through `regionmask`.
- **Yahoo Finance**, tickers `TTF=F` and `KRBN`, for personal, non-commercial use; the data are not redistributed.

The literature and market sources behind the analysis are listed in [Appendix C of results_analysis.md](results_analysis.md#appendix-c-references).

## License

Copyright (c) 2026 Mangirdas Mikalkėnas. All rights reserved.

This repository is published for portfolio purposes. You may view the code on GitHub and, solely to evaluate the author's work, download and run it.

No other rights are granted. You may not copy, modify, distribute or use any part of this code for any other purpose without the author's prior written permission.
