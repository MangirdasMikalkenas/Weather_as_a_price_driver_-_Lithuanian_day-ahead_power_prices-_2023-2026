-- Raw layer. The tables are filled from the files in data/ by src/build_db.py.
-- All timestamps are UTC and mark the START of the interval they describe.

CREATE OR REPLACE TABLE entsoe_raw (
    ts_utc   TIMESTAMP NOT NULL,  -- interval start (60 or 15 minutes)
    zone     VARCHAR   NOT NULL,  -- LT, LV, EE, FI, SE_4, PL
    dataset  VARCHAR   NOT NULL,  -- da_price, generation, load, load_forecast, wind_solar_forecast
    series   VARCHAR   NOT NULL,  -- e.g. 'da_price', 'Wind Onshore', 'Solar', 'Actual Load'
    value    DOUBLE               -- EUR/MWh for prices, MW for everything else
);

CREATE OR REPLACE TABLE era5_regions (
    ts_utc              TIMESTAMP NOT NULL,  -- hour start
    region              VARCHAR   NOT NULL,  -- LT, LV, EE, FI, SE, NO, DK, PL, DE
    wind_speed_100m_ms  DOUBLE,              -- mean wind speed at 100 m, m/s
    wind_cf             DOUBLE,              -- estimated wind capacity factor, 0..1
    t2m_c               DOUBLE,              -- 2 m temperature, deg C
    ssrd_wm2            DOUBLE               -- mean solar radiation during the hour, W/m2
);

CREATE OR REPLACE TABLE gas_daily (
    trade_date   DATE NOT NULL,  -- trading day
    ttf_eur_mwh  DOUBLE          -- TTF front-month closing price, EUR/MWh
);
