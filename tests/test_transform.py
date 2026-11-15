"""Tests for pipeline transformations."""

import pandas as pd

from src.transform import build_dim_fuel


def test_build_dim_fuel_returns_classified_dimension():
    generation_long = pd.DataFrame({"fuel": ["wind", "gas", "nuclear"]})

    result = build_dim_fuel(generation_long)

    assert result["fuel"].tolist() == ["gas", "nuclear", "wind"]
    assert result["fuel_group"].tolist() == ["fossil", "other", "renewable"]
    assert result["is_renewable"].tolist() == [0, 0, 1]
    assert result["fuel_key"].tolist() == [1, 2, 3]
