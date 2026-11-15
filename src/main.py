"""Entry point: python -m src.main --month 2026-09"""

import argparse
import logging
import sys

from src.extract import extract_month
from src.load import load_month
from src.transform import (build_dim_fuel, build_dim_time, build_facts,
                           build_generation_long, build_intensity,
                           run_quality_checks)

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(message)s"


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[logging.FileHandler("pipeline.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )


def run(month):
    log = logging.getLogger("pipeline")
    log.info("start %s for %s", "grid pipeline", month)

    payload = extract_month(month)
    generation = build_generation_long(payload["generation"])
    intensity = build_intensity(payload["intensity"])
    log.info("extracted %s generation rows, %s intensity rows",
             len(generation), len(intensity))

    failures = run_quality_checks(generation, intensity)
    if failures:
        for failure in failures:
            log.error("quality check failed: %s", failure)
        log.error("aborting - nothing loaded")
        return 1

    dim_time = build_dim_time(generation, month)
    dim_fuel = build_dim_fuel(generation)
    fact_generation, fact_intensity = build_facts(
        generation, intensity, dim_time, dim_fuel)

    load_month({"dim_fuel": dim_fuel, "dim_time": dim_time,
                "fact_generation": fact_generation,
                "fact_intensity": fact_intensity},
               month_start=f"{month}-01")

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