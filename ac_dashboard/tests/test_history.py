from datetime import datetime, timedelta, timezone

import pytest

from app.history import RANGES, build_history


def test_ranges_map_to_statistics_period():
    assert RANGES["24h"] == (timedelta(hours=24), "5minute")
    assert RANGES["7d"] == (timedelta(days=7), "hour")
    assert RANGES["30d"] == (timedelta(days=30), "hour")


def test_build_history_maps_statistics_rows_to_points():
    rows = [
        {"start": 1.0e12, "end": 1.0e12 + 3.6e6, "mean": 12.456, "min": 12.0, "max": 13.0},
        {"start": 1.0e12 + 3.6e6, "end": 1.0e12 + 7.2e6, "mean": 13.0, "min": None, "max": None},
    ]
    result = build_history("7d", "°C", rows)
    assert result["range"] == "7d"
    assert result["period"] == "hour"
    assert result["unit"] == "°C"
    assert result["points"] == [
        {"t": 1_000_000_000_000, "mean": 12.5, "min": 12.0, "max": 13.0},
        {"t": 1_000_003_600_000, "mean": 13.0, "min": None, "max": None},
    ]


def test_build_history_skips_rows_without_mean():
    rows = [{"start": 1.0e12, "end": 1.0e12 + 3.6e6, "mean": None, "min": None, "max": None}]
    assert build_history("24h", "°C", rows)["points"] == []


def test_build_history_rejects_unknown_range():
    with pytest.raises(KeyError):
        build_history("1y", "°C", [])
