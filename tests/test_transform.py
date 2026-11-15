import pandas as pd
import pytest

from src.transform import (build_dim_fuel, build_dim_time, classify_fuel,
                           run_quality_checks)
from src.main import write_processed_csvs


def test_classify_fuel():
    assert classify_fuel("wind") == "renewable"
    assert classify_fuel("gas") == "fossil"
    assert classify_fuel("nuclear") == "other"


def test_dim_fuel_keys_are_deterministic():
    df = pd.DataFrame({"period_start_utc": ["a", "a", "a"],
                       "fuel": ["wind", "gas", "solar"]})
    first = build_dim_fuel(df)
    second = build_dim_fuel(df)
    assert first["fuel_key"].tolist() == second["fuel_key"].tolist()
    assert first["fuel_key"].tolist() == [1, 2, 3]      # sorted: gas, solar, wind


def test_period_attributed_to_end_timestamp():
    """The 23:30->00:00 period must belong to the month it ENDS in."""
    df = pd.DataFrame({
        "period_start_utc": ["2026-08-31T23:30Z", "2026-09-01T00:00Z"],
        "period_end_utc":   ["2026-09-01T00:00Z", "2026-09-01T00:30Z"],
        "fuel": ["wind", "wind"],
        "percentage": [30.0, 31.0],
    })
    dim = build_dim_time(df, "2026-09")
    assert len(dim) == 2
    assert dim["local_date"].astype(str).tolist() == ["2026-09-01", "2026-09-01"]


def test_quality_gate_catches_bad_mix():
    bad = pd.DataFrame({
        "period_start_utc": ["t1", "t1"],
        "fuel": ["wind", "gas"],
        "percentage": [10.0, 10.0],          # sums to 20, not ~100
    })
    good_intensity = pd.DataFrame({"actual_gco2_kwh": [100], "forecast_gco2_kwh": [90]})
    failures = run_quality_checks(bad, good_intensity)
    assert any("sum to ~100" in f for f in failures)


def test_quality_gate_catches_duplicates():
    dup = pd.DataFrame({
        "period_start_utc": ["t1", "t1"],
        "fuel": ["wind", "wind"],
        "percentage": [50.0, 50.0],
    })
    good_intensity = pd.DataFrame({"actual_gco2_kwh": [100], "forecast_gco2_kwh": [90]})
    assert any("duplicate" in f for f in run_quality_checks(dup, good_intensity))


def test_processed_csvs_include_all_tables_and_a_100_row_sample(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.PROCESSED_DIR", tmp_path)
    tables = {
        "dim_fuel": pd.DataFrame({
            "fuel_key": [1],
            "fuel": ["wind"],
            "fuel_group": ["renewable"],
            "is_renewable": [1],
        }),
        "dim_time": pd.DataFrame({
            "period_start_utc": ["2026-09-01T00:00Z"],
            "period_end_utc": ["2026-09-01T00:30Z"],
            "period_end": [pd.Timestamp("2026-09-01T00:30Z")],
            "time_key": [1],
        }),
        "fact_generation": pd.DataFrame({
            "time_key": range(1, 121),
            "fuel_key": [1] * 120,
            "percentage": [50.0] * 120,
        }),
        "fact_intensity": pd.DataFrame({
            "time_key": [1],
            "forecast_gco2_kwh": [100],
            "actual_gco2_kwh": [95],
            "intensity_index": ["moderate"],
        }),
    }

    write_processed_csvs("2026-09", tables)

    assert pd.read_csv(tmp_path / "dim_fuel_2026-09.csv").columns.tolist() == [
        "fuel_key", "fuel_name", "fuel_group", "is_renewable"
    ]
    assert "period_end" not in pd.read_csv(
        tmp_path / "dim_time_2026-09.csv"
    ).columns
    assert len(pd.read_csv(tmp_path / "fact_generation_2026-09.csv")) == 120
    assert len(pd.read_csv(tmp_path / "fact_intensity_2026-09.csv")) == 1
    assert len(pd.read_csv(tmp_path / "fact_generation_sample.csv")) == 100
