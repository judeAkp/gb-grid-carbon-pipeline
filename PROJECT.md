# GB Grid Carbon Pipeline — Project Brief

| Project detail | Description |
|---|---|
| Author | Jude Akp |
| Status | In progress — Week 4, Month 1 |
| Stack | Python (`requests`, `pandas`), SQL Server (T-SQL), SQL analysis |

## 1. The problem

The Great Britain electricity grid publishes half-hourly data about:

- how much electricity came from each fuel, such as wind, gas, nuclear, and
  solar; and
- how carbon-intensive that electricity was, measured in gCO2 per kWh.

The goal is to turn this raw feed into a reliable, queryable dataset that
supports analysis and whose results can be checked.

### Why this project?

It combines public British data, a real API, nested JSON, an analytical story,
and data that can be reused with attribution under CC BY 4.0.

## 2. Data source

| Property | Details |
|---|---|
| API | [NESO Carbon Intensity API](https://api.carbonintensity.org.uk) |
| Authentication | None; no API key is required |
| Endpoints | `/generation/{from}/{to}` for fuel mix; `/intensity/{from}/{to}` for forecast and actual carbon intensity |
| Grain | 30-minute settlement periods for Great Britain; Northern Ireland is excluded |
| Timestamps | UTC (`Z`); reporting attributes use `Europe/London` |
| Fuel rows | September 2026 returns 1,441 raw periods (12,969 fuel rows); month attribution produces 1,440 time periods |
| Licence | CC BY 4.0; attribution is required, and the API itself must not be resold |

> **Boundary note:** The API response includes an interval at the month
> boundary. The pipeline attributes periods by their end timestamp, so the
> transformed month has 1,440 periods even though the raw response has 1,441.

### Required attribution

Include this attribution in the README:

> Contains data from the Carbon Intensity API by National Energy System
> Operator (NESO), https://carbonintensity.org.uk, licensed under CC BY 4.0.

## 3. Questions the dataset must answer

1. What share of Great Britain electricity came from renewables—wind, hydro,
   solar, and biomass—in September 2026, and how did it vary by day?
2. Which local hours are cleanest and most carbon-intensive?
3. What were the cleanest and dirtiest days of the month?
4. How did wind compare with gas as a source of electricity?
5. Is carbon intensity lower at weekends than on weekdays?
6. How often was actual carbon intensity higher than forecast?

## 4. Architecture

```text
NESO API
   |
   | src/extract.py — retry, timeout, save raw JSON snapshots
   v
data/raw/YYYY-MM/ — immutable, gitignored, replayable snapshots
   |
   | src/transform.py — flatten JSON, build dimensions and facts, validate
   v
In-memory pandas DataFrames
   |
   | src/load.py — create tables and load idempotently
   v
SQL Server: DE_Learning
   | dim_fuel, dim_time, fact_generation, fact_intensity, pipeline_runs
   |
   | sql/analysis.sql
   v
Answers to the six questions above
```

> **Implementation note:** `data/processed/` is reserved for optional
> processed exports. The current pipeline passes transformed DataFrames
> directly to SQL Server; it does not write per-table CSV files there.

## 5. Design decisions

- **Keep raw data.** Save each API response as a timestamped JSON snapshot so
  transformations can be rerun without another download.
- **Use a star schema.** Keep generation and intensity in separate fact tables
  that share `dim_time`. Store renewable/fossil/other classifications in
  `dim_fuel`, not in every fact row.
- **Use deterministic keys.** Assign `time_key` and `fuel_key` from sorted
  values rather than `IDENTITY`, so repeated runs reproduce the same keys.
- **Make month loads idempotent.** Delete and reinsert that month's time and
  fact rows inside one transaction; verify row counts after insertion.
- **Enforce a data-quality gate.** Stop before loading if a period's fuel mix
  does not sum to approximately 100%, duplicate period/fuel rows exist, a
  percentage is outside 0–100, a period has the wrong number of fuels, or
  actual/forecast intensity is null.
- **Keep time zones explicit.** Store source timestamps in UTC and derive
  reporting attributes in `Europe/London`, including daylight-saving changes.

## 6. Definition of done

- `python -m src.main --month 2026-09` runs extraction, transformation,
  validation, and loading from an empty database.
- Running the same month twice does not duplicate its rows.
- Quality-check failures prevent loading and return a failure exit code.
- `dbo.pipeline_runs` records successful runs, including row counts and status.
- `sql/analysis.sql` answers all six questions and documents expected results.
- At least three pytest tests pass with `pytest -q`.
- The README explains setup and execution, reports findings, and includes the
  required data attribution.
- The pipeline can be explained in two minutes without notes.

## 7. Future work

- Add regional carbon-intensity analysis.
- Load only missing periods.
- Add orchestration with Airflow or Prefect.
- Build a Grafana or Power BI dashboard on the fact tables.
