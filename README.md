# GB Grid Carbon Pipeline

An end-to-end data pipeline that pulls half-hourly electricity generation and
carbon intensity data for Great Britain from the NESO Carbon Intensity API,
reshapes it into a star schema in SQL Server, and answers six analytical
questions in SQL.

## What it does
API -> raw JSON snapshot -> pandas (flatten, validate) -> SQL Server
(dim_fuel, dim_time, fact_generation, fact_intensity) -> SQL analysis

## Findings (September 2026)
- Renewables supplied 55.4% of GB electricity on average (range 21.4%-81.0%).
- Wind averaged 38.0% versus gas 21.2% - wind was the single largest source.
- The grid was twice as carbon intensive at 19:00 local time (~150 gCO2/kWh)
  as at 13:00 (~74) - evening demand peak versus midday solar.
- Weekends averaged 92 gCO2/kWh against 114 on weekdays (~19% cleaner).
- 59% of half-hour periods came in above the published forecast
  (mean bias +5.6 gCO2/kWh) - the forecast is slightly optimistic.

## How to run
    pip install -r requirements.txt
    python -m src.main --month 2026-09
    pytest -q

Requires SQL Server with a database called DE_Learning, and ODBC Driver 18.
The pipeline is idempotent: running it twice for the same month does not
duplicate rows. Each run is recorded in dbo.pipeline_runs.

## Data quality
The load is refused if the fuel mix for any period does not sum to ~100%,
if duplicate (period, fuel) rows exist, if any percentage is outside 0-100,
or if a period is missing fuels. Checks live in src/transform.py and are
covered by tests.

## Design notes
- Periods are attributed by their END timestamp, so a 23:30->00:00 period
  belongs to the month it ends in. Month reloads are therefore idempotent.
- Surrogate keys (time_key, fuel_key) are assigned deterministically from
  sorted values, not IDENTITY, so reloads reproduce identical keys.
- Percentages use DECIMAL(5,2); a CHECK constraint enforces 0-100.

## Attribution
Contains data from the Carbon Intensity API by National Energy System
Operator (NESO), https://carbonintensity.org.uk, licensed under CC BY 4.0.

## What I'd do next
Regional intensity, incremental loading of only new periods, Airflow
orchestration, and a Power BI dashboard on the fact tables.