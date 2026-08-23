"""Temperature history from Home Assistant's long-term statistics.

Raw recorder history is purged after ~10 days, but statistics (5-minute
short-term, hourly long-term with mean/min/max) persist, so the charts read
those instead.
"""

from datetime import timedelta

# range -> (how far back, statistics period)
RANGES: dict[str, tuple[timedelta, str]] = {
    "24h": (timedelta(hours=24), "5minute"),
    "7d": (timedelta(days=7), "hour"),
    "30d": (timedelta(days=30), "hour"),
}


def _round(value):
    return None if value is None else round(value, 1)


def build_history(range_key: str, unit: str | None, rows: list[dict]) -> dict:
    _, period = RANGES[range_key]
    points = [
        {
            "t": int(row["start"]),  # epoch ms, as HA reports it
            "mean": _round(row["mean"]),
            "min": _round(row.get("min")),
            "max": _round(row.get("max")),
        }
        for row in rows
        if row.get("mean") is not None
    ]
    return {"range": range_key, "period": period, "unit": unit, "points": points}
