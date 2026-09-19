-- Analysis layer: one row per hour with a Lithuanian price and everything we know about that hour.

CREATE OR REPLACE VIEW lt_hourly AS
WITH base AS (
    SELECT
        p.ts_utc,
        (p.ts_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Vilnius' AS ts_local,
        p.price_lt AS price,
        p.price_lv, p.price_ee, p.price_fi, p.price_se4, p.price_pl,
        g.wind_mw, g.solar_mw, g.total_generation_mw,
        l.load_mw, l.load_forecast_mw,
        f.wind_forecast_mw, f.solar_forecast_mw,
        w.wind_cf_lt, w.wind_cf_lv, w.wind_cf_ee, w.wind_cf_fi, w.wind_cf_se,
        w.wind_cf_no, w.wind_cf_dk, w.wind_cf_pl, w.wind_cf_de,
        w.wind_speed_lt_ms, w.temp_lt_c, w.solar_rad_lt_wm2
    FROM price_hourly_wide p
    LEFT JOIN lt_generation_hourly   g ON g.ts_utc = p.ts_utc
    LEFT JOIN lt_load_hourly         l ON l.ts_utc = p.ts_utc
    LEFT JOIN lt_res_forecast_hourly f ON f.ts_utc = p.ts_utc
    LEFT JOIN weather_hourly         w ON w.ts_utc = p.ts_utc
    WHERE p.price_lt IS NOT NULL
),
with_calendar AS (
    SELECT
        *,
        CAST(ts_local AS DATE) AS date_local,
        hour(ts_local)         AS hour_local,
        isodow(ts_local)       AS weekday,      -- 1 = Monday ... 7 = Sunday
        month(ts_local)        AS month_local,
        load_mw - wind_mw - solar_mw AS residual_load_mw  -- NULL if any part is missing
    FROM base
)
SELECT
    c.*,
    lag24.price_lt  AS price_lag_24h,   -- same hour yesterday
    lag168.price_lt AS price_lag_168h,  -- same hour a week ago
    gas.ttf_eur_mwh                     -- last TTF close BEFORE the delivery day
FROM with_calendar c
LEFT JOIN price_hourly_wide lag24  ON lag24.ts_utc  = c.ts_utc - INTERVAL 24 HOUR
LEFT JOIN price_hourly_wide lag168 ON lag168.ts_utc = c.ts_utc - INTERVAL 168 HOUR
ASOF LEFT JOIN gas_daily gas ON c.date_local > gas.trade_date;
