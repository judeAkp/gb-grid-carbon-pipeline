-- Results are for September 2026, matching the committed data sample.
-- 1. Renewable share across half-hour periods
WITH per_period AS (
    SELECT f.time_key,
           SUM(CASE WHEN fu.fuel_group = 'renewable' THEN f.percentage ELSE 0 END)
               AS renewable_pct
    FROM dbo.fact_generation f
    JOIN dbo.dim_fuel fu ON fu.fuel_key = f.fuel_key
    JOIN dbo.dim_time t ON t.time_key = f.time_key
    WHERE t.month_start = '2026-09-01'
    GROUP BY f.time_key
)
SELECT ROUND(AVG(renewable_pct), 2) AS avg_renewable_share_pct,
       ROUND(MIN(renewable_pct), 1) AS min_share,
       ROUND(MAX(renewable_pct), 1) AS max_share
FROM per_period;

-- 2. Average carbon intensity by local hour
SELECT t.local_hour,
       ROUND(AVG(CAST(i.actual_gco2_kwh AS FLOAT)), 1) AS avg_gco2_per_kwh,
       COUNT(*) AS periods
FROM dbo.fact_intensity i
JOIN dbo.dim_time t ON t.time_key = i.time_key
WHERE t.month_start = '2026-09-01'
  AND t.local_date >= '2026-09-01'
  AND t.local_date < '2026-10-01'
GROUP BY t.local_hour
ORDER BY avg_gco2_per_kwh DESC;

-- 3. Three cleanest and dirtiest complete local days
WITH daily AS (
    SELECT t.local_date,
           AVG(CAST(i.actual_gco2_kwh AS FLOAT)) AS avg_gco2_per_kwh
    FROM dbo.fact_intensity i
    JOIN dbo.dim_time t ON t.time_key = i.time_key
    WHERE t.month_start = '2026-09-01'
      AND t.local_date >= '2026-09-01'
      AND t.local_date < '2026-10-01'
    GROUP BY t.local_date
    -- Require 48 half-hour periods so partial boundary days cannot rank.
    HAVING COUNT(*) = 48
),
ranked AS (
    SELECT local_date,
           avg_gco2_per_kwh,
           ROW_NUMBER() OVER (ORDER BY avg_gco2_per_kwh, local_date) AS clean_rank,
           ROW_NUMBER() OVER (ORDER BY avg_gco2_per_kwh DESC, local_date) AS dirty_rank
    FROM daily
)
SELECT ranking, rank_order, local_date,
       ROUND(avg_gco2_per_kwh, 1) AS avg_gco2_per_kwh
FROM (
    SELECT 'cleanest' AS ranking, clean_rank AS rank_order,
           local_date, avg_gco2_per_kwh
    FROM ranked
    WHERE clean_rank <= 3
    UNION ALL
    SELECT 'dirtiest', dirty_rank, local_date, avg_gco2_per_kwh
    FROM ranked
    WHERE dirty_rank <= 3
) AS daily_extremes
ORDER BY ranking, rank_order;

-- 4. Average and peak generation share for wind and gas
SELECT fu.fuel_name,
       ROUND(AVG(f.percentage), 2) AS avg_share_pct,
       ROUND(MAX(f.percentage), 1) AS peak_share_pct
FROM dbo.fact_generation f
JOIN dbo.dim_fuel fu ON fu.fuel_key = f.fuel_key
JOIN dbo.dim_time t ON t.time_key = f.time_key
WHERE fu.fuel_name IN ('wind', 'gas')
  AND t.month_start = '2026-09-01'
GROUP BY fu.fuel_name
ORDER BY avg_share_pct DESC;

-- 5. Average intensity on weekdays and weekends
SELECT t.is_weekend,
       CASE WHEN t.is_weekend = 1 THEN 'weekend' ELSE 'weekday' END AS day_type,
       ROUND(AVG(CAST(i.actual_gco2_kwh AS FLOAT)), 1) AS avg_gco2_per_kwh,
       COUNT(*) AS periods
FROM dbo.fact_intensity i
JOIN dbo.dim_time t ON t.time_key = i.time_key
WHERE t.month_start = '2026-09-01'
GROUP BY t.is_weekend;

-- 6. Actual intensity compared with forecast
SELECT ROUND(100.0 * SUM(CASE WHEN actual_gco2_kwh > forecast_gco2_kwh
                              THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_above_forecast,
       ROUND(AVG(CAST(actual_gco2_kwh - forecast_gco2_kwh AS FLOAT)), 1) AS mean_bias
FROM dbo.fact_intensity i
JOIN dbo.dim_time t ON t.time_key = i.time_key
WHERE t.month_start = '2026-09-01';
