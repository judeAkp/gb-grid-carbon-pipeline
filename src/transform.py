"""Transform source data into the pipeline's processed format."""
"""Transform raw NESO payloads into tidy dimension and fact DataFrames."""

import pandas as pd

from config import (EXPECTED_FUELS, FOSSIL_FUELS, MIX_SUM_MAX,
                    MIX_SUM_MIN, RENEWABLE_FUELS)


def classify_fuel(fuel):
    if fuel in RENEWABLE_FUELS:
        return "renewable"
    if fuel in FOSSIL_FUELS:
        return "fossil"
    return "other"


def build_generation_long(raw_generation):
    """One row per half-hour period per fuel: 1440 periods x 9 fuels = 12,960 rows."""
    rows = []
    for period in raw_generation:
        for entry in period["generationmix"]:
            rows.append({
                "period_start_utc": period["from"],
                "period_end_utc": period["to"],
                "fuel": entry["fuel"],
                "percentage": entry["perc"],
            })
    return pd.DataFrame(rows)


def build_intensity(raw_intensity):
    return pd.DataFrame([
        {
            "period_start_utc": item["from"],
            "period_end_utc": item["to"],
            "forecast_gco2_kwh": item["intensity"]["forecast"],
            "actual_gco2_kwh": item["intensity"]["actual"],
            "intensity_index": item["intensity"]["index"],
        }
        for item in raw_intensity
    ])

def build_dim_time(generation_long, month):
    """Half-hourly time dimension. Attributed by period END so months don't overlap."""
    dim = (generation_long[["period_start_utc", "period_end_utc"]]
           .drop_duplicates("period_start_utc")
           .assign(period_end=lambda d: pd.to_datetime(d["period_end_utc"], utc=True))
           .sort_values("period_end")
           .reset_index(drop=True))

    start = pd.Timestamp(f"{month}-01", tz="UTC")
    end = start + pd.offsets.MonthBegin(1)
    dim = dim[(dim["period_end"] >= start) & (dim["period_end"] < end)].reset_index(drop=True)

    local = dim["period_end"].dt.tz_convert("Europe/London")
    dim["time_key"] = dim.index + 1                       # deterministic key
    dim["local_date"] = local.dt.date
    dim["local_hour"] = local.dt.hour
    dim["day_of_week"] = local.dt.day_name()
    dim["is_weekend"] = (local.dt.dayofweek >= 5).astype(int)
    dim["month_start"] = start.date()
    return dim


def build_dim_fuel(generation_long):
    dim = (generation_long[["fuel"]].drop_duplicates()
           .sort_values("fuel").reset_index(drop=True))
    dim["fuel_group"] = dim["fuel"].map(classify_fuel)
    dim["is_renewable"] = (dim["fuel_group"] == "renewable").astype(int)
    dim["fuel_key"] = dim.index + 1                       # deterministic key
    return dim



def build_facts(generation_long, intensity, dim_time, dim_fuel):
    time_lookup = dim_time[["period_start_utc", "time_key"]]
    fuel_lookup = dim_fuel[["fuel", "fuel_key"]]

    fact_generation = (generation_long
                       .merge(time_lookup, on="period_start_utc")
                       .merge(fuel_lookup, on="fuel")
                       [["time_key", "fuel_key", "percentage"]])

    fact_intensity = (intensity
                      .merge(time_lookup, on="period_start_utc")
                      [["time_key", "forecast_gco2_kwh",
                        "actual_gco2_kwh", "intensity_index"]])
    return fact_generation, fact_intensity


def run_quality_checks(generation_long, intensity):
    """Return a list of failures. Empty list = safe to load."""
    failures = []
    mix_sum = generation_long.groupby("period_start_utc")["percentage"].sum()

    if generation_long.duplicated(["period_start_utc", "fuel"]).any():
        failures.append("duplicate (period, fuel) rows")
    if not mix_sum.between(MIX_SUM_MIN, MIX_SUM_MAX).all():
        failures.append(f"fuel mix does not sum to ~100 "
                        f"(min {mix_sum.min():.1f}, max {mix_sum.max():.1f})")
    if not generation_long["percentage"].between(0, 100).all():
        failures.append("percentage outside 0-100")
    if generation_long.groupby("period_start_utc").size().ne(EXPECTED_FUELS).any():
        failures.append("a period does not have the expected number of fuels")
    if intensity[["actual_gco2_kwh", "forecast_gco2_kwh"]].isna().any().any():
        failures.append("null carbon intensity values")
    return failures


class DataQualityError(RuntimeError):
    def __init__(self, failures):
        self.failures = failures
        super().__init__("Data quality checks failed: " + "; ".join(failures))


def build_tables(payload, month):
    generation = build_generation_long(payload["generation"])
    intensity = build_intensity(payload["intensity"])

    failures = run_quality_checks(generation, intensity)
    if failures:
        raise DataQualityError(failures)

    dim_time = build_dim_time(generation, month)
    in_month_periods = dim_time["period_start_utc"]
    generation_in_month = generation.loc[
        generation["period_start_utc"].isin(in_month_periods)
    ].copy()
    intensity_in_month = intensity.loc[
        intensity["period_start_utc"].isin(in_month_periods)
    ].copy()
    dim_fuel = build_dim_fuel(generation_in_month)
    fact_generation, fact_intensity = build_facts(
        generation_in_month, intensity_in_month, dim_time, dim_fuel
    )

    return {
        "dim_fuel": dim_fuel,
        "dim_time": dim_time,
        "fact_generation": fact_generation,
        "fact_intensity": fact_intensity,
    }
