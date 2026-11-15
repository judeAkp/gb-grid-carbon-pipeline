import pandas as pd
import pytest

from src.transform import (build_dim_fuel, build_dim_time, classify_fuel,
                           run_quality_checks)


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