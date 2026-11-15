WITH per_period AS (
    SELECT f.time_key,
           SUM(CASE WHEN fu.fuel_group = 'renewable' THEN f.percentage ELSE 0 END)
               AS renewable_pct
    FROM dbo.fact_generation f
    JOIN dbo.dim_fuel fu ON fu.fuel_key = f.fuel_key
    GROUP BY f.time_key
)
SELECT ROUND(AVG(renewable_pct), 2) AS avg_renewable_share_pct,
       ROUND(MIN(renewable_pct), 1) AS min_share,
       ROUND(MAX(renewable_pct), 1) AS max_share
FROM per_period;
-- Expected: 55.4% average, range 21.4% -> 81.0%

SELECT t.local_hour,
       ROUND(AVG(i.actual_gco2_kwh), 1) AS avg_gco2_per_kwh,
       COUNT(*) AS periods
FROM dbo.fact_intensity i
JOIN dbo.dim_time t ON t.time_key = i.time_key
GROUP BY t.local_hour
ORDER BY avg_gco2_per_kwh DESC;
-- Dirtiest: 19:00 local (~150). Cleanest: 13:00 local (~74), then 12:00 and 11:00

SELECT TOP 3 t.local_date,
       ROUND(AVG(i.actual_gco2_kwh), 1) AS avg_gco2_per_kwh
FROM dbo.fact_intensity i
JOIN dbo.dim_time t ON t.time_key = i.time_key
GROUP BY t.local_date
ORDER BY avg_gco2_per_kwh ASC;
-- Cleanest: 2026-09-19 (~60), then 09-18, then one more
-- Then flip to DESC for the dirtiest: 2026-09-22 (~190)

SELECT fu.fuel_name,
       ROUND(AVG(f.percentage), 2) AS avg_share_pct,
       ROUND(MAX(f.percentage), 1) AS peak_share_pct
FROM dbo.fact_generation f
JOIN dbo.dim_fuel fu ON fu.fuel_key = f.fuel_key
WHERE fu.fuel_name IN ('wind', 'gas')
GROUP BY fu.fuel_name
ORDER BY avg_share_pct DESC;
-- wind 38.0% average (peak well over 60%), gas 21.2%

SELECT t.is_weekend,
       ROUND(AVG(i.actual_gco2_kwh), 1) AS avg_gco2_per_kwh,
       COUNT(*) AS periods
FROM dbo.fact_intensity i
JOIN dbo.dim_time t ON t.time_key = i.time_key
GROUP BY t.is_weekend;
-- weekday ~114, weekend ~92  (about 19% cleaner)

SELECT ROUND(100.0 * SUM(CASE WHEN actual_gco2_kwh > forecast_gco2_kwh
                              THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_above_forecast,
       ROUND(AVG(actual_gco2_kwh - forecast_gco2_kwh), 1)        AS mean_bias
FROM dbo.fact_intensity;
-- Expected: ~59% of periods came in ABOVE forecast; mean bias about +5.6 gCO2/kWh
-- Interpretation: the forecasting model is slightly optimistic about how clean the grid will be.