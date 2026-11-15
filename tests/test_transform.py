import json
import logging
from datetime import date

import pandas as pd
import pytest

import src.load as loader
import src.main as pipeline
import src.transform as transform
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


def test_pipeline_filters_boundary_rows_before_building_facts(
    monkeypatch, caplog
):
    fuels = (
        "biomass", "coal", "gas", "hydro", "imports",
        "nuclear", "other", "solar", "wind",
    )
    generationmix = [
        {"fuel": fuel, "perc": 100.0 if fuel == "wind" else 0.0}
        for fuel in fuels
    ]
    generation = [
        {
            "from": "2026-08-31T23:30Z",
            "to": "2026-09-01T00:00Z",
            "generationmix": generationmix,
        },
        {
            "from": "2026-09-30T23:30Z",
            "to": "2026-10-01T00:00Z",
            "generationmix": generationmix,
        },
    ]
    intensity = [
        {
            "from": period["from"],
            "to": period["to"],
            "intensity": {
                "forecast": 100,
                "actual": 95,
                "index": "moderate",
            },
        }
        for period in generation
    ]
    monkeypatch.setattr(
        pipeline, "extract_month",
        lambda month: {"generation": generation, "intensity": intensity},
    )
    monkeypatch.setattr(pipeline, "write_processed_csvs", lambda *args: None)
    loaded = {}

    def fake_load_month(tables, month_start):
        loaded.update(tables=tables, month_start=month_start)
        return tables

    monkeypatch.setattr(pipeline, "load_month", fake_load_month)

    actual_build_facts = transform.build_facts
    facts_input_rows = {}

    def capture_build_facts(generation_long, intensity_data, dim_time, dim_fuel):
        facts_input_rows["generation"] = len(generation_long)
        facts_input_rows["intensity"] = len(intensity_data)
        return actual_build_facts(
            generation_long, intensity_data, dim_time, dim_fuel
        )

    monkeypatch.setattr(transform, "build_facts", capture_build_facts)
    with caplog.at_level(logging.INFO, logger="pipeline"):
        assert pipeline.run("2026-09") == 0

    assert facts_input_rows == {"generation": 9, "intensity": 1}
    assert len(loaded["tables"]["fact_generation"]) == 9
    assert len(loaded["tables"]["fact_intensity"]) == 1
    assert loaded["month_start"] == date(2026, 9, 1)
    assert "extracted 18 generation rows -> in-month 9" in caplog.text
    assert "extracted 2 intensity rows -> in-month 1" in caplog.text


def test_load_latest_month_uses_shared_table_builder(tmp_path, monkeypatch):
    month = "2026-09"
    snapshot_dir = tmp_path / month
    snapshot_dir.mkdir()
    payload = {"generation": [], "intensity": []}
    (snapshot_dir / "generation_test.json").write_text(
        json.dumps(payload["generation"]), encoding="utf-8"
    )
    (snapshot_dir / "intensity_test.json").write_text(
        json.dumps(payload["intensity"]), encoding="utf-8"
    )
    monkeypatch.setattr(loader, "RAW_ROOT", tmp_path)

    tables = {"sentinel": object()}
    builder_call = {}
    load_call = {}

    def fake_build_tables(raw_payload, requested_month):
        builder_call.update(payload=raw_payload, month=requested_month)
        return tables

    def fake_load_month(built_tables, month_start):
        load_call.update(tables=built_tables, month_start=month_start)

    monkeypatch.setattr(loader, "build_tables", fake_build_tables)
    monkeypatch.setattr(loader, "load_month", fake_load_month)

    loader.load_latest_month(month)

    assert builder_call == {"payload": payload, "month": month}
    assert load_call == {"tables": tables, "month_start": date(2026, 9, 1)}


def test_ensure_fuel_members_appends_and_remaps_new_fuel_keys():
    class FakeResult:
        def __init__(self, rows=()):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def __init__(self):
            self.fuels = [(1, "gas"), (2, "wind")]
            self.executed = []

        def execute(self, statement, params=None):
            sql = str(statement)
            self.executed.append((sql, params))
            if sql.startswith("SELECT fuel_key, fuel_name"):
                return FakeResult(self.fuels)
            if sql.startswith("INSERT INTO dbo.dim_fuel"):
                self.fuels.append((params["fuel_key"], params["fuel_name"]))
            return FakeResult()

    connection = FakeConnection()
    dim_fuel = pd.DataFrame({
        "fuel_key": [1, 2, 3],
        "fuel_name": ["coal", "gas", "wind"],
        "fuel_group": ["fossil", "fossil", "renewable"],
        "is_renewable": [0, 0, 1],
    })
    fact_generation = pd.DataFrame({
        "time_key": [1, 1, 1],
        "fuel_key": [1, 2, 3],
        "percentage": [0.0, 50.0, 50.0],
    })

    fuel_key_map = loader.ensure_fuel_members(connection, dim_fuel)
    remapped_dim = loader.remap_fuel_keys(dim_fuel, fuel_key_map)
    remapped_facts = loader.remap_fuel_keys(fact_generation, fuel_key_map)

    insert_sql, insert_params = next(
        (sql, params)
        for sql, params in connection.executed
        if sql.startswith("INSERT INTO dbo.dim_fuel")
    )
    assert "WHERE NOT EXISTS" in insert_sql
    assert "UPDLOCK, HOLDLOCK" in insert_sql
    assert insert_params["fuel_key"] == 3
    assert insert_params["fuel_name"] == "coal"
    assert connection.fuels == [(1, "gas"), (2, "wind"), (3, "coal")]
    assert remapped_dim["fuel_key"].tolist() == [3, 1, 2]
    assert remapped_facts["fuel_key"].tolist() == [3, 1, 2]


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
