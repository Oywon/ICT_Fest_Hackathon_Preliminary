"""Helpers for parsing input datetimes and rendering UTC responses."""
from datetime import datetime, timezone


def parse_input_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime into a naive UTC datetime for storage.

    Inputs that carry a UTC offset are normalized to UTC; naive inputs are
    treated as UTC as-is.
    """
    if "T" not in value and " " not in value:
        raise ValueError("Expected ISO 8601 datetime")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso_utc(dt: datetime) -> str:
    """Render a stored (naive UTC) datetime with an explicit UTC designator."""
    return dt.replace(tzinfo=timezone.utc).isoformat()
