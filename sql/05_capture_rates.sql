-- Capture price: the average price a technology actually earns, weighted by its hourly output.
-- Capture rate: capture price divided by the plain (baseload) average price.
-- A rate below 1 means the technology produces mostly when prices are low.

CREATE OR REPLACE VIEW capture_rates_monthly AS
WITH monthly AS (
    SELECT
        date_trunc('month', ts_local)                    AS month,
        count(*)                                         AS hours,
        avg(price)                                       AS baseload_price,
        sum(wind_mw * price)  / nullif(sum(wind_mw), 0)  AS wind_capture_price,
        sum(solar_mw * price) / nullif(sum(solar_mw), 0) AS solar_capture_price
    FROM lt_hourly
    GROUP BY 1
)
SELECT
    month,
    hours,
    baseload_price,
    wind_capture_price,
    wind_capture_price / baseload_price  AS wind_capture_rate,
    solar_capture_price,
    solar_capture_price / baseload_price AS solar_capture_rate
FROM monthly
ORDER BY month;
