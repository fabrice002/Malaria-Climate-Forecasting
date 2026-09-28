"""
Shared helpers.

`utc_now` exists because `datetime.utcnow()` is deprecated from Python 3.12: it
returned a *naive* datetime that merely happened to hold UTC, which silently
breaks any comparison with an aware one. `datetime.now(UTC)` returns a properly
timezone-aware value.

Every timestamp in this application — ORM defaults, pipeline runs, API responses
— goes through this function, so the codebase never mixes aware and naive values.
The matching ORM columns are declared `DateTime(timezone=True)`.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)
