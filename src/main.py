"""Entry point: python -m src.main --month 2026-09"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from src.extract import extract_month
from src.load import load_month
from src.transform import DataQualityError, build_tables

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(message)s"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[logging.FileHandler("pipeline.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )


def write_processed_csvs(month, tables):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    processed_tables = {
        "dim_fuel": tables["dim_fuel"].rename(columns={"fuel": "fuel_name"})[
            ["fuel_key", "fuel_name", "fuel_group", "is_renewable"]
        ],
        "dim_time": tables["dim_time"].drop(columns=["period_end"]),
        "fact_generation": tables["fact_generation"].sort_values(
            ["time_key", "fuel_key"]
        ).reset_index(drop=True),
        "fact_intensity": tables["fact_intensity"].sort_values(
            "time_key"
        ).reset_index(drop=True),
    }

    log = logging.getLogger("pipeline")
    for table_name, frame in processed_tables.items():
        path = PROCESSED_DIR / f"{table_name}_{month}.csv"
        frame.to_csv(path, index=False)
        log.info("wrote %s", path.name)

    sample_path = PROCESSED_DIR / "fact_generation_sample.csv"
    processed_tables["fact_generation"].head(100).to_csv(sample_path, index=False)
    log.info("wrote %s (first 100 fact rows)", sample_path.name)


def run(month):
    log = logging.getLogger("pipeline")
    log.info("start %s for %s", "grid pipeline", month)

    payload = extract_month(month)
    extracted_generation_rows = sum(
        len(period["generationmix"]) for period in payload["generation"]
    )
    extracted_intensity_rows = len(payload["intensity"])
    try:
        tables = build_tables(payload, month)
    except DataQualityError as error:
        for failure in error.failures:
            log.error("quality check failed: %s", failure)
        log.error("aborting - nothing loaded")
        return 1

    log.info(
        "extracted %s generation rows -> in-month %s; "
        "extracted %s intensity rows -> in-month %s",
        f"{extracted_generation_rows:,}",
        f"{len(tables['fact_generation']):,}",
        f"{extracted_intensity_rows:,}",
        f"{len(tables['fact_intensity']):,}",
    )
    tables = load_month(tables, month_start=date.fromisoformat(f"{month}-01"))
    write_processed_csvs(month, tables)

    log.info("finished successfully")
    return 0


def main():
    parser = argparse.ArgumentParser(description="GB grid carbon intensity pipeline")
    parser.add_argument("--month", required=True,
                        help="month to load, format YYYY-MM, e.g. 2026-09")
    args = parser.parse_args()
    setup_logging()
    try:
        sys.exit(run(args.month))
    except Exception:
        logging.getLogger("pipeline").exception("pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()