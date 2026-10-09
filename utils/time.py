"""Timestamps: the database stores timezone-aware UTC datetimes, while the dashboard parses `YYYY-MM-DD HH:MM:SS`
strings (web/src/lib/utils.ts appends the Z itself)."""

from datetime import UTC, datetime
from typing import overload

FORMAT = "%Y-%m-%d %H:%M:%S"


@overload
def to_stamp(value: datetime) -> str: ...


@overload
def to_stamp(value: None) -> None: ...


def to_stamp(value: datetime | None) -> str | None:
    """A datetime in the dashboard's format, or None; a time without a zone is taken as UTC."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime(FORMAT)
