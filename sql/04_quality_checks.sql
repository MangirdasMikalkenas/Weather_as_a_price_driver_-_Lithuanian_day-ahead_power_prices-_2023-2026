-- Data quality checks. Every view lists problems, so an empty view means "all good".
-- qa_summary counts the problems of every check in one table.

-- Hours between the first and the last Lithuanian price that have no price at all.
CREATE OR REPLACE VIEW qa_missing_price_hours AS
WITH bounds AS (
    SELECT min(ts_utc) AS first_ts, max(ts_utc) AS last_ts
    FROM price_hourly
    WHERE zone = 'LT'
),
expected AS (
    SELECT unnest(generate_series(first_ts, last_ts, INTERVAL 1 HOUR)) AS ts_utc
    FROM bounds
)
SELECT e.ts_utc
FROM expected e
LEFT JOIN price_hourly p ON p.ts_utc = e.ts_utc AND p.zone = 'LT'
WHERE p.ts_utc IS NULL;

-- Hours with an unexpected number of price intervals: 1 (hourly) or 4 (15-minute) is fine.
CREATE OR REPLACE VIEW qa_incomplete_price_hours AS
SELECT ts_utc, zone, n_intervals
FROM price_hourly
WHERE n_intervals NOT IN (1, 4);

-- The same raw value loaded twice.
CREATE OR REPLACE VIEW qa_duplicates AS
SELECT ts_utc, zone, dataset, series, count(*) AS n
FROM entsoe_raw
GROUP BY 1, 2, 3, 4
HAVING count(*) > 1;

-- Prices outside the harmonised SDAC limits (-500 .. +4000 EUR/MWh) can only be data errors.
CREATE OR REPLACE VIEW qa_price_out_of_range AS
SELECT *
FROM entsoe_raw
WHERE dataset = 'da_price' AND (value < -500 OR value > 4000);

-- Gaps in the hourly ERA5 series, found with a window function.
CREATE OR REPLACE VIEW qa_weather_gaps AS
SELECT region, ts_utc, gap
FROM (
    SELECT
        region,
        ts_utc,
        ts_utc - lag(ts_utc) OVER (PARTITION BY region ORDER BY ts_utc) AS gap
    FROM era5_regions
)
WHERE gap > INTERVAL 1 HOUR;

-- Hydro weeks where a bidding zone did not report. They are excluded from the normal and from
-- lt_hourly (the previous complete week is used instead), so this is a report, not an error.
CREATE OR REPLACE VIEW qa_hydro_missing_zones AS
SELECT *
FROM hydro_weekly
WHERE NOT is_complete;

CREATE OR REPLACE VIEW qa_summary AS
SELECT 'missing LT price hours' AS check_name, count(*) AS problems FROM qa_missing_price_hours
UNION ALL SELECT 'incomplete price hours',     count(*) FROM qa_incomplete_price_hours
UNION ALL SELECT 'duplicate raw rows',         count(*) FROM qa_duplicates
UNION ALL SELECT 'prices out of range',        count(*) FROM qa_price_out_of_range
UNION ALL SELECT 'gaps in ERA5 series',        count(*) FROM qa_weather_gaps
UNION ALL SELECT 'hydro weeks missing a zone (excluded)', count(*) FROM qa_hydro_missing_zones;
