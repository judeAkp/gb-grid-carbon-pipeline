"""Load processed data into the destination."""
"""Load transformed DataFrames into SQL Server, idempotently."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from config import PIPELINE_NAME, engine_url
from src.transform import build_tables

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


def ensure_fuel_members(conn, dim_fuel):
    existing_rows = conn.execute(text(
        "SELECT fuel_key, fuel_name "
        "FROM dbo.dim_fuel WITH (UPDLOCK, HOLDLOCK)"
    )).fetchall()
    existing_fuels = {fuel_name: int(fuel_key)
                      for fuel_key, fuel_name in existing_rows}
    next_fuel_key = max(existing_fuels.values(), default=0) + 1
    source_to_database_key = {}

    insert_missing = text(
        "INSERT INTO dbo.dim_fuel "
        "(fuel_key, fuel_name, fuel_group, is_renewable) "
        "SELECT :fuel_key, :fuel_name, :fuel_group, :is_renewable "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM dbo.dim_fuel WITH (UPDLOCK, HOLDLOCK) "
        "WHERE fuel_name = :fuel_name)"
    )
    for row in dim_fuel.to_dict("records"):
        source_key = int(row["fuel_key"])
        fuel_name = row["fuel_name"]
        database_key = existing_fuels.get(fuel_name)
        if database_key is None:
            if next_fuel_key > 255:
                raise OverflowError("dim_fuel TINYINT key capacity is exhausted")
            database_key = next_fuel_key
            conn.execute(insert_missing, {
                "fuel_key": database_key,
                "fuel_name": fuel_name,
                "fuel_group": row["fuel_group"],
                "is_renewable": int(row["is_renewable"]),
            })
            existing_fuels[fuel_name] = database_key
            next_fuel_key += 1
        source_to_database_key[source_key] = database_key

    return source_to_database_key


def remap_fuel_keys(frame, source_to_database_key):
    remapped = frame.copy()
    remapped_keys = remapped["fuel_key"].map(source_to_database_key)
    if remapped_keys.isna().any():
        raise RuntimeError("fuel key is absent from dim_fuel")
    remapped["fuel_key"] = remapped_keys.astype("int64")
    return remapped


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

        loaded_tables = dict(tables)
        fuel_key_map = ensure_fuel_members(conn, dim_fuel)
        loaded_tables["dim_fuel"] = remap_fuel_keys(
            tables["dim_fuel"], fuel_key_map
        )
        loaded_tables["fact_generation"] = remap_fuel_keys(
            tables["fact_generation"], fuel_key_map
        )

        dim_time.to_sql("dim_time", conn, schema="dbo", if_exists="append", index=False)
        loaded_tables["fact_generation"].to_sql(
            "fact_generation", conn, schema="dbo", if_exists="append", index=False
        )
        loaded_tables["fact_intensity"].to_sql(
            "fact_intensity", conn, schema="dbo", if_exists="append", index=False
        )

        verify_counts(conn, loaded_tables, month_start)

        finished = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        conn.execute(text(
            "INSERT INTO dbo.pipeline_runs (pipeline_name, month_start, started_at_utc, "
            "finished_at_utc, rows_generation, rows_intensity, status, message) "
            "VALUES (:p, :m, :s, :f, :g, :i, 'success', :msg)"),
            {"p": PIPELINE_NAME, "m": month_start, "s": started, "f": finished,
             "g": len(loaded_tables["fact_generation"]),
             "i": len(loaded_tables["fact_intensity"]),
             "msg": "quality checks passed"})

    print(f"✅ loaded {len(tables['fact_generation'])} generation rows, "
          f"{len(tables['fact_intensity'])} intensity rows")
    return loaded_tables


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

    tables = build_tables(raw_payload, month)
    load_month(tables, date.fromisoformat(f"{month}-01"))


if __name__ == "__main__":
    load_latest_month("2026-09")