-- Clean layer: everything aggregated to whole hours (UTC) and reshaped to one column per variable.
-- MW values are averaged within the hour, so an hourly MW value equals the MWh produced in that hour.

-- Day-ahead prices per zone. Since 2025-10-01 prices are 15-minute, so an hour has 4 of them.
CREATE OR REPLACE VIEW price_hourly AS
SELECT
    date_trunc('hour', ts_utc) AS ts_utc,
    zone,
    avg(value)                 AS price_eur_mwh,
    count(*)                   AS n_intervals   -- 1 = hourly price, 4 = four 15-min prices
FROM entsoe_raw
WHERE dataset = 'da_price'
GROUP BY 1, 2;

-- One row per hour, one price column per zone.
CREATE OR REPLACE VIEW price_hourly_wide AS
SELECT
    ts_utc,
    max(price_eur_mwh) FILTER (WHERE zone = 'LT')   AS price_lt,
    max(price_eur_mwh) FILTER (WHERE zone = 'LV')   AS price_lv,
    max(price_eur_mwh) FILTER (WHERE zone = 'EE')   AS price_ee,
    max(price_eur_mwh) FILTER (WHERE zone = 'FI')   AS price_fi,
    max(price_eur_mwh) FILTER (WHERE zone = 'SE_4') AS price_se4,
    max(price_eur_mwh) FILTER (WHERE zone = 'PL')   AS price_pl
FROM price_hourly
GROUP BY ts_utc;

-- Lithuanian generation. Storage is net (negative while pumping or charging).
CREATE OR REPLACE VIEW lt_generation_hourly AS
WITH per_series AS (
    SELECT date_trunc('hour', ts_utc) AS ts_utc, series, avg(value) AS mw
    FROM entsoe_raw
    WHERE dataset = 'generation' AND zone = 'LT'
    GROUP BY 1, 2
)
SELECT
    ts_utc,
    sum(mw) FILTER (WHERE series = 'Wind Onshore') AS wind_mw,
    sum(mw) FILTER (WHERE series = 'Solar')        AS solar_mw,
    sum(mw)                                        AS total_generation_mw
FROM per_series
GROUP BY ts_utc;

-- Lithuanian load: actual value and the day-ahead forecast.
-- Real day-ahead load forecasts miss by a few per cent. A forecast value of zero, or an hourly
-- forecast that misses the actual load by more than 50 %, is therefore a data error and set to NULL.
CREATE OR REPLACE VIEW lt_load_hourly AS
WITH hourly AS (
    SELECT
        date_trunc('hour', ts_utc)                                        AS ts_utc,
        avg(value) FILTER (WHERE dataset = 'load')                        AS load_mw,
        avg(value) FILTER (WHERE dataset = 'load_forecast' AND value > 0) AS load_forecast_raw_mw,
        count(*)   FILTER (WHERE dataset = 'load_forecast' AND value <= 0) AS n_zero_forecasts
    FROM entsoe_raw
    WHERE zone = 'LT' AND dataset IN ('load', 'load_forecast')
    GROUP BY 1
)
SELECT
    ts_utc,
    load_mw,
    load_forecast_raw_mw,
    n_zero_forecasts,
    CASE
        WHEN load_mw > 0 AND abs(load_forecast_raw_mw - load_mw) / load_mw > 0.5 THEN NULL
        ELSE load_forecast_raw_mw
    END AS load_forecast_mw
FROM hourly;

-- Day-ahead wind and solar generation forecasts for Lithuania.
CREATE OR REPLACE VIEW lt_res_forecast_hourly AS
SELECT
    date_trunc('hour', ts_utc)                        AS ts_utc,
    avg(value) FILTER (WHERE series = 'Wind Onshore') AS wind_forecast_mw,
    avg(value) FILTER (WHERE series = 'Solar')        AS solar_forecast_mw
FROM entsoe_raw
WHERE zone = 'LT' AND dataset = 'wind_solar_forecast'
GROUP BY 1;

-- ERA5 indices: wind for every region, temperature and solar radiation for Lithuania.
CREATE OR REPLACE VIEW weather_hourly AS
SELECT
    ts_utc,
    max(wind_cf)            FILTER (WHERE region = 'LT') AS wind_cf_lt,
    max(wind_cf)            FILTER (WHERE region = 'LV') AS wind_cf_lv,
    max(wind_cf)            FILTER (WHERE region = 'EE') AS wind_cf_ee,
    max(wind_cf)            FILTER (WHERE region = 'FI') AS wind_cf_fi,
    max(wind_cf)            FILTER (WHERE region = 'SE') AS wind_cf_se,
    max(wind_cf)            FILTER (WHERE region = 'NO') AS wind_cf_no,
    max(wind_cf)            FILTER (WHERE region = 'DK') AS wind_cf_dk,
    max(wind_cf)            FILTER (WHERE region = 'PL') AS wind_cf_pl,
    max(wind_cf)            FILTER (WHERE region = 'DE') AS wind_cf_de,
    max(wind_speed_100m_ms) FILTER (WHERE region = 'LT') AS wind_speed_lt_ms,
    max(t2m_c)              FILTER (WHERE region = 'LT') AS temp_lt_c,
    max(ssrd_wm2)           FILTER (WHERE region = 'LT') AS solar_rad_lt_wm2
FROM era5_regions
GROUP BY ts_utc;

-- Nordic hydro reservoirs: weekly stored energy per country and in total, compared with the
-- average of the same week of the year in 2015-2022 (the "normal" level for that week).
CREATE OR REPLACE VIEW hydro_weekly AS
WITH per_zone AS (
    SELECT
        -- Monday of the week; +12 h absorbs the zones' different UTC offsets at midnight
        CAST(date_trunc('week', ts_utc + INTERVAL 12 HOUR) AS DATE) AS week_start,
        split_part(zone, '_', 1)                                    AS country,  -- NO_1 -> NO
        value / 1000                                                AS gwh       -- MWh -> GWh
    FROM entsoe_raw
    WHERE dataset = 'hydro_reservoirs'
),
per_area AS (
    SELECT week_start, country AS area, sum(gwh) AS reservoir_gwh, count(*) AS n_zones
    FROM per_zone
    GROUP BY 1, 2
    UNION ALL
    SELECT week_start, 'NORDIC' AS area, sum(gwh), count(*)
    FROM per_zone
    GROUP BY 1
),
flagged AS (
    -- a week is complete when every zone of the area reported; otherwise the sum is too low
    SELECT *, n_zones = max(n_zones) OVER (PARTITION BY area) AS is_complete
    FROM per_area
),
normal AS (
    SELECT area, weekofyear(week_start) AS iso_week, avg(reservoir_gwh) AS normal_gwh
    FROM flagged
    WHERE is_complete AND isoyear(week_start) BETWEEN 2015 AND 2022
    GROUP BY 1, 2
)
SELECT
    f.week_start,
    f.area,
    f.n_zones,
    f.is_complete,
    f.reservoir_gwh,
    n.normal_gwh,
    f.reservoir_gwh - n.normal_gwh AS deviation_gwh  -- > 0: more water than normal
FROM flagged f
LEFT JOIN normal n ON n.area = f.area AND n.iso_week = weekofyear(f.week_start);
