from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from recall.database import list_scan_timestamps
from recall.domain import EventValidationError, validate_event_interval


@pytest.mark.parametrize(
    "start,end",
    [
        (None, "2026-09-10T11:00"),
        ("invalid", "2026-09-10T11:00"),
        ("2026-09-10T10:00", ""),
        ("2026-09-10T10:00", "2026-09-10T10:00"),
        ("2026-09-10T11:00", "2026-09-10T10:00"),
        ("2026-09-10T10:01", "2026-09-10T11:00"),
        ("2026-09-10T10:00", "2026-09-10T11:01"),
        ("2026-09-10T10:00:01", "2026-09-10T11:00"),
        ("2026-09-10T10:00:00.000001", "2026-09-10T11:00"),
    ],
)
def test_invalid_intervals(start, end):
    with pytest.raises(EventValidationError):
        validate_event_interval(start, end)


def test_aware_input_is_normalized_to_utc():
    start, end = validate_event_interval(
        "2026-09-10T13:00+03:00", "2026-09-10T14:00+03:00"
    )
    assert start == datetime(2026, 9, 10, 10)
    assert end == datetime(2026, 9, 10, 11)
    assert start.tzinfo is None


@pytest.mark.parametrize("minutes", [5, 10, 60, 24 * 60])
def test_scans_include_start_and_exclude_end(minutes):
    start = datetime(2026, 9, 10, 23, 55)
    end = start + timedelta(minutes=minutes)
    scans = list_scan_timestamps(SimpleNamespace(start_time=start, end_time=end))
    assert len(scans) == minutes // 5
    assert scans[0] == start
    assert scans[-1] == end - timedelta(minutes=5)
    assert end not in scans


def test_adjacent_events_do_not_share_a_scan():
    boundary = datetime(2026, 9, 10, 11, tzinfo=timezone.utc)
    before = list_scan_timestamps(
        SimpleNamespace(start_time=boundary - timedelta(hours=1), end_time=boundary)
    )
    after = list_scan_timestamps(
        SimpleNamespace(start_time=boundary, end_time=boundary + timedelta(hours=1))
    )
    assert not set(before) & set(after)
