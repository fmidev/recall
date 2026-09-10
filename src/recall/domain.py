"""Shared validation for catalog events and archive scan times."""

from datetime import datetime, timedelta, timezone


SCAN_INTERVAL = timedelta(minutes=5)


class EventValidationError(ValueError):
    """An event cannot be saved with the supplied inputs."""


def parse_event_time(value):
    """Normalize a form or database timestamp to the catalog's naive UTC format."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise EventValidationError("Enter a valid UTC date and time.") from exc
    if not isinstance(value, datetime):
        raise EventValidationError("Both start and end times are required.")
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def validate_event_interval(start_time, end_time):
    """Validate a half-open UTC interval on the five-minute archive grid."""
    start_time = parse_event_time(start_time)
    end_time = parse_event_time(end_time)
    for value in (start_time, end_time):
        if value.minute % 5 or value.second or value.microsecond:
            raise EventValidationError(
                "Start and end times must fall on five-minute UTC boundaries."
            )
    if end_time <= start_time:
        raise EventValidationError("End time must be later than start time.")
    return start_time, end_time
