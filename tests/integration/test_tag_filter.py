from datetime import datetime, timedelta

import pytest

from recall.database.connection import db
from recall.database.models import Event, Tag
from recall.database.queries import browse_events
from recall.domain import EventValidationError


pytestmark = pytest.mark.integration


@pytest.fixture
def tagged_events(radars):
    tags = [Tag(name="rain"), Tag(name="attenuation"), Tag(name="birds")]
    db.session.add_all(tags)
    start = datetime(2023, 8, 28, 10)
    events = []
    for i, event_tags in enumerate(([tags[0], tags[1]], [tags[0]], [tags[2]], [])):
        events.append(
            Event(
                radar=radars[0],
                start_time=start + timedelta(hours=i),
                end_time=start + timedelta(hours=i + 1),
                tags=event_tags,
                description=str(i),
            )
        )
    db.session.add_all(events)
    db.session.commit()
    return [event.id for event in events], [tag.id for tag in tags]


def test_default_all_filter_and_any_filter(tagged_events):
    ids, tags = tagged_events
    assert [event.id for event in browse_events(tags[:2])] == [ids[0]]
    assert [event.id for event in browse_events(tags[:2], "any")] == ids[:2]


def test_empty_filter_includes_untagged_events(tagged_events):
    ids, _ = tagged_events
    assert [event.id for event in browse_events()] == ids


def test_duplicate_ids_do_not_change_all_semantics(tagged_events):
    ids, tags = tagged_events
    assert [event.id for event in browse_events([tags[0], tags[0]])] == ids[:2]


def test_missing_tags_and_no_matches(tagged_events):
    _, tags = tagged_events
    assert browse_events([tags[0], tags[2]]) == []
    assert browse_events([999999]) == []


def test_filter_does_not_modify_annotations(tagged_events):
    ids, tags = tagged_events
    browse_events(tags[:2], "any")
    db.session.expire_all()
    assert {tag.id for tag in db.session.get(Event, ids[0]).tags} == set(tags[:2])
    assert db.session.get(Event, ids[-1]).tags == []


def test_invalid_match_mode_is_rejected(tagged_events):
    with pytest.raises(EventValidationError, match="Tag matching"):
        browse_events([], "invalid")
