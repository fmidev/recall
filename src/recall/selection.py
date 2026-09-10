"""One saved-event snapshot shared by the form, map, playback, and downloads."""

import logging
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from recall.database import list_scan_timestamps
from recall.domain import EventValidationError


logger = logging.getLogger(__name__)


def event_snapshot(event, coordinates):
    error = None
    try:
        timestamps = [time.isoformat() for time in list_scan_timestamps(event)]
    except EventValidationError as exc:
        timestamps = []
        error = str(exc)
        logger.warning("Invalid interval for saved event %s: %s", event.id, exc)
    return {
        "id": event.id,
        "radar_id": event.radar_id,
        "radar": event.radar.name,
        "start_time": event.start_time.isoformat(),
        "end_time": event.end_time.isoformat(),
        "description": event.description or "",
        "tag_ids": [tag.id for tag in event.tags],
        "coordinates": coordinates,
        "timestamps": timestamps,
        "error": error,
    }


@dataclass(frozen=True)
class Scan:
    radar: str
    timestamp: datetime
    index: int


def selected_scan(selection, slider_value):
    """Bound a possibly stale slider value to the current saved selection."""
    if not selection or not selection.get("timestamps"):
        return None
    times = selection["timestamps"]
    value = slider_value if isinstance(slider_value, (int, float)) else 0
    index = min(max(int(value) if isfinite(value) else 0, 0), len(times) - 1)
    return Scan(selection["radar"], datetime.fromisoformat(times[index]), index)
