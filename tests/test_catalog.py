from datetime import datetime

import pytest

from recall.database.catalog import parse_catalog
from recall.domain import EventValidationError


def event_record(**changes):
    return {
        "id": 21,
        "radar": "fikor",
        "start_time": datetime(2023, 8, 28, 10),
        "end_time": datetime(2023, 8, 28, 11),
        "description": "Interesting case",
        "tags": ["rain", "attenuation"],
        **changes,
    }


def test_parse_preserves_catalog_fields():
    record = parse_catalog({"event": [event_record()]})[0]
    assert record.id == 21
    assert record.description == "Interesting case"
    assert record.tags == ("attenuation", "rain")
    assert record.start_time == datetime(2023, 8, 28, 10)


@pytest.mark.parametrize(
    "document", [{}, {"event": []}, {"event": {}}, {"extra": [], "event": []}]
)
def test_rejects_invalid_document(document):
    with pytest.raises(EventValidationError):
        parse_catalog(document)


@pytest.mark.parametrize(
    "changes",
    [
        {"id": True},
        {"id": 0},
        {"id": 2**31},
        {"id": "1"},
        {"radar": ""},
        {"radar": " fikor"},
        {"description": None},
        {"tags": "rain"},
        {"tags": [""]},
        {"tags": ["rain", "rain"]},
        {"tags": [5]},
        {"tags": ["x" * 256]},
        {"end_time": datetime(2023, 8, 28, 10, 1)},
    ],
)
def test_rejects_invalid_record(changes):
    with pytest.raises(EventValidationError):
        parse_catalog({"event": [event_record(**changes)]})


def test_missing_fields_are_not_silently_defaulted():
    record = event_record()
    del record["tags"]
    with pytest.raises(EventValidationError):
        parse_catalog({"event": [record]})


def test_duplicate_ids_are_rejected():
    with pytest.raises(EventValidationError, match="Duplicate event ID"):
        parse_catalog({"event": [event_record(), event_record()]})


def test_overlapping_export_is_rejected_before_database_access():
    with pytest.raises(EventValidationError, match="overlap"):
        parse_catalog({"event": [event_record(), event_record(id=22)]})


def test_adjacent_events_and_different_radars_are_allowed():
    assert (
        len(
            parse_catalog(
                {
                    "event": [
                        event_record(),
                        event_record(
                            id=22,
                            start_time=datetime(2023, 8, 28, 11),
                            end_time=datetime(2023, 8, 28, 12),
                        ),
                        event_record(id=23, radar="fivih"),
                    ]
                }
            )
        )
        == 3
    )
