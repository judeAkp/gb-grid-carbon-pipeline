"""Load processed data into the destination."""
"""Load transformed DataFrames into SQL Server, idempotently."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from config import PIPELINE_NAME, engine_url
from src.transform import (
    build_dim_fuel,
    build_dim_time,
    build_facts,
    build_generation_long,
    build_intensity,
    run_quality_checks,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DDL_PATH = PROJECT_ROOT / "sql" / "ddl.sql"
RAW_ROOT = PROJECT_ROOT / "data" / "raw"


def get_engine():
    return create_engine(engine_url(), fast_executemany=True)


def ensure_tables(engine):
    ddl = DDL_PATH.read_text(encoding="utf-8")
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    with engine.begin() as conn:
        for statement in statements:
            if "CREATE TABLE" in statement:
                name = statement.split("dbo.")[1].split()[0]
                if conn.execute(text(
                        f"SELECT OBJECT_ID('dbo.{name}', 'U')")).scalar() is None:
                    conn.execute(text(statement))


def delete_month(conn, month_start):
    """Idempotency: remove the month before inserting it again."""
    for table in ("fact_generation", "fact_intensity"):
        conn.execute(text(f"DELETE FROM dbo.{table} WHERE time_key IN "
                          "(SELECT time_key FROM dbo.dim_time WHERE month_start = :m)"),
                     {"m": month_start})
    conn.execute(text("DELETE FROM dbo.dim_time WHERE month_start = :m"),
                 {"m": month_start})


def load_month(tables, month_start):
    engine = get_engine()
    ensure_tables(engine)
    started = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    dim_fuel = tables["dim_fuel"].rename(columns={"fuel": "fuel_name"})[
        ["fuel_key", "fuel_name", "fuel_group", "is_renewable"]
    ]
    dim_time = tables["dim_time"].drop(columns=["period_end"]).copy()
    for column in ("period_start_utc", "period_end_utc"):
        dim_time[column] = pd.to_datetime(dim_time[column], utc=True).dt.tz_localize(None)

    with engine.begin() as conn:
        delete_month(conn, month_start)

        # dims first (facts reference them)
        if conn.execute(text("SELECT COUNT(*) FROM dbo.dim_fuel")).scalar() == 0:
            dim_fuel.to_sql(
                "dim_fuel", conn, schema="dbo", if_exists="append", index=False
            )

        dim_time.to_sql("dim_time", conn, schema="dbo", if_exists="append", index=False)
        tables["fact_generation"].to_sql("fact_generation", conn,
                                         schema="dbo", if_exists="append", index=False)
        tables["fact_intensity"].to_sql("fact_intensity", conn,
                                        schema="dbo", if_exists="append", index=False)

        verify_counts(conn, tables, month_start)

        finished = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        conn.execute(text(
            "INSERT INTO dbo.pipeline_runs (pipeline_name, month_start, started_at_utc, "
            "finished_at_utc, rows_generation, rows_intensity, status, message) "
            "VALUES (:p, :m, :s, :f, :g, :i, 'success', :msg)"),
            {"p": PIPELINE_NAME, "m": month_start, "s": started, "f": finished,
             "g": len(tables["fact_generation"]), "i": len(tables["fact_intensity"]),
             "msg": "quality checks passed"})

    print(f"✅ loaded {len(tables['fact_generation'])} generation rows, "
          f"{len(tables['fact_intensity'])} intensity rows")


def verify_counts(conn, tables, month_start):
    """Raise if the database doesn't hold what we just sent it."""
    for table, expected in (("fact_generation", len(tables["fact_generation"])),
                            ("fact_intensity", len(tables["fact_intensity"]))):
        actual = conn.execute(text(
            f"SELECT COUNT(*) FROM dbo.{table} AS fact "
            "JOIN dbo.dim_time AS time_dim ON fact.time_key = time_dim.time_key "
            "WHERE time_dim.month_start = :month_start"),
            {"month_start": month_start}).scalar()
        if actual != expected:
            raise RuntimeError(f"{table}: expected {expected} rows, found {actual}")
    print("✅ row-count verification passed")


def load_latest_month(month):
    snapshot_dir = RAW_ROOT / month
    generation_files = {
        path.stem.split("_", 1)[1]: path
        for path in snapshot_dir.glob("generation_*.json")
    }
    intensity_files = {
        path.stem.split("_", 1)[1]: path
        for path in snapshot_dir.glob("intensity_*.json")
    }
    matching_stamps = generation_files.keys() & intensity_files.keys()
    if not matching_stamps:
        raise FileNotFoundError(
            f"No matching generation/intensity snapshots found in {snapshot_dir}"
        )

    stamp = max(matching_stamps)
    print(f"Using raw snapshot set {stamp} for {month}.")
    raw_payload = {
        "generation": json.loads(
            generation_files[stamp].read_text(encoding="utf-8")
        ),
        "intensity": json.loads(
            intensity_files[stamp].read_text(encoding="utf-8")
        ),
    }

    generation_long = build_generation_long(raw_payload["generation"])
    intensity = build_intensity(raw_payload["intensity"])
    failures = run_quality_checks(generation_long, intensity)
    if failures:
        raise RuntimeError("Data quality checks failed: " + "; ".join(failures))

    dim_time = build_dim_time(generation_long, month)
    dim_fuel = build_dim_fuel(generation_long)
    fact_generation, fact_intensity = build_facts(
        generation_long, intensity, dim_time, dim_fuel
    )
    load_month(
        {
            "dim_fuel": dim_fuel,
            "dim_time": dim_time,
            "fact_generation": fact_generation,
            "fact_intensity": fact_intensity,
        },
        date.fromisoformat(f"{month}-01"),
    )


if __name__ == "__main__":
    load_latest_month("2026-09")