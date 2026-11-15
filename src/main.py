"""Orchestrate the pipeline."""

from src.extract import extract_month
from src.transform import (
    build_dim_fuel,
    build_dim_time,
    build_facts,
    build_generation_long,
    build_intensity,
    run_quality_checks,
)


def main():
    month = "2026-09"
    print(f"Extracting data for {month}...")
    raw_payload = extract_month(month)

    generation_long = build_generation_long(raw_payload["generation"])
    intensity = build_intensity(raw_payload["intensity"])
    dim_time = build_dim_time(generation_long, month)
    dim_fuel = build_dim_fuel(generation_long)
    fact_generation, fact_intensity = build_facts(
        generation_long, intensity, dim_time, dim_fuel
    )

    failures = run_quality_checks(generation_long, intensity)
    if failures:
        raise RuntimeError("Data quality checks failed: " + "; ".join(failures))

    print("Data quality checks passed.")
    print(f"Raw generation periods: {len(raw_payload['generation'])}")
    print(f"Raw intensity periods: {len(raw_payload['intensity'])}")
    print(f"Generation-long rows: {len(generation_long)}")
    print(f"Intensity rows: {len(intensity)}")
    print(f"Time dimension rows: {len(dim_time)}")
    print(f"Fuel dimension rows: {len(dim_fuel)}")
    print(f"Generation fact rows: {len(fact_generation)}")
    print(f"Intensity fact rows: {len(fact_intensity)}")
    print("\nFuel dimension:")
    print(dim_fuel.to_string(index=False))
    print("\nGeneration fact preview:")
    print(fact_generation.head().to_string(index=False))
    print("\nIntensity fact preview:")
    print(fact_intensity.head().to_string(index=False))


if __name__ == "__main__":
    main()
