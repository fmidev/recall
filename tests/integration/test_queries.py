from datetime import datetime, timedelta

import pytest
from sqlalchemy import func

from recall.database.connection import db
from recall.database.models import Event, Tag
from recall.database.queries import add_event, get_coords, save_event
from recall.domain import EventValidationError


pytestmark = pytest.mark.integration
START = datetime(2024, 1, 1, 12)
END = START + timedelta(minutes=30)


def test_get_coords_returns_leaflet_latitude_longitude(radars):
    assert get_coords(db, radars[0]) == pytest.approx((60, 21))


def test_save_create_and_metadata_only_updates(radars):
    event, imagery_changed = save_event(radars[0].id, START, END, "Initial", [])
    assert imagery_changed is True
    event_id = event.id
    tag = Tag(name="curated")
    db.session.add(tag)
    db.session.commit()

    updated, imagery_changed = save_event(
        radars[0].id, START, END, "Updated", [tag.id, tag.id], event_id=event_id
    )
    assert imagery_changed is False
    assert updated.id == event_id
    db.session.expire_all()
    assert updated.description == "Updated"
    assert updated.tags == [tag]
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 1

    unchanged, imagery_changed = save_event(
        radars[0].id, START, END, "Updated", [tag.id], event_id=event_id
    )
    assert unchanged.id == event_id
    assert imagery_changed is False


@pytest.mark.parametrize("change", ["radar", "start", "end"])
def test_imagery_changes_only_for_radar_or_interval(radars, change):
    event, _ = save_event(radars[0].id, START, END, "Initial", [])
    radar_id = radars[1].id if change == "radar" else radars[0].id
    start = START + timedelta(minutes=5) if change == "start" else START
    end = END + timedelta(minutes=5) if change == "end" else END
    updated, imagery_changed = save_event(
        radar_id, start, end, "Initial", [], event_id=event.id
    )
    assert imagery_changed is True
    assert (updated.radar_id, updated.start_time, updated.end_time) == (
        radar_id,
        start,
        end,
    )


@pytest.mark.parametrize(
    "missing, message",
    [
        ("radar", "existing radar"),
        ("tag", "tag no longer exists"),
        ("event", "event no longer exists"),
    ],
)
def test_save_rejects_stale_identifiers_without_modifying_catalog(
    radars, missing, message
):
    event, _ = save_event(radars[0].id, START, END, "Preserved", [])
    event_id = event.id
    with pytest.raises(EventValidationError, match=message):
        save_event(
            999999 if missing == "radar" else radars[0].id,
            START,
            END,
            "Must not persist",
            [999999] if missing == "tag" else [],
            event_id=999999 if missing == "event" else event_id,
        )
    db.session.expire_all()
    assert db.session.get(Event, event_id).description == "Preserved"
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 1


def test_rejected_update_rolls_back_all_changes(radars):
    first = add_event(db, radars[0], START, END, "Preserved")
    add_event(db, radars[0], END, END + timedelta(minutes=30), "Adjacent")
    first_id = first.id
    with pytest.raises(EventValidationError, match="overlaps"):
        save_event(
            radars[0].id,
            START,
            END + timedelta(minutes=5),
            "Must not persist",
            [],
            event_id=first_id,
        )
    db.session.expire_all()
    preserved = db.session.get(Event, first_id)
    assert preserved.description == "Preserved"
    assert preserved.end_time == END
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 2


def test_database_overlap_race_becomes_validation_error_and_session_recovers(
    radars, monkeypatch
):
    add_event(db, radars[0], START, END, "Existing")
    # Simulate the preflight query missing a competing writer's uncommitted row.
    monkeypatch.setattr(
        "recall.database.queries.event_overlaps_existing", lambda db, event: False
    )
    with pytest.raises(EventValidationError, match="overlaps"):
        add_event(db, radars[0], START, END, "Rejected")
    saved = add_event(db, radars[1], START, END, "Different radar")
    assert saved.id is not None
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 2
