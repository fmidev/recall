"""Methods for interacting with the database."""

from sqlalchemy.exc import IntegrityError

from recall.database.connection import db
from recall.database.models import Event, Radar, Tag
from recall.domain import EventValidationError, validate_event_interval


def get_coords(db, radar):
    lat = db.session.scalar(radar.location.ST_Y())
    lon = db.session.scalar(radar.location.ST_X())
    return lat, lon


def add_event(db, radar, start_time, end_time, description, tags=None):
    """Add an event to the database."""
    start_time, end_time = validate_event_interval(start_time, end_time)
    event = Event(
        radar=radar,
        tags=tags or [],
        start_time=start_time,
        end_time=end_time,
        description=description,
    )
    _persist_event(db, event)
    return event


def _persist_event(db, event):
    if event_overlaps_existing(db, event):
        db.session.rollback()
        raise EventValidationError(
            "Event overlaps with an existing event for this radar."
        )
    db.session.add(event)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        if getattr(exc.orig, "pgcode", None) == "23P01":
            raise EventValidationError(
                "Event overlaps with an existing event for this radar."
            ) from exc
        raise


def save_event(radar_id, start_time, end_time, description, tag_ids, event_id=None):
    """Save catalog data only; return the event and whether imagery needs preparation."""
    start_time, end_time = validate_event_interval(start_time, end_time)
    radar = db.session.get(Radar, radar_id) if radar_id is not None else None
    if radar is None:
        raise EventValidationError("Select an existing radar.")
    tag_ids = set(tag_ids or [])
    tags = db.session.scalars(db.select(Tag).where(Tag.id.in_(tag_ids))).all()
    if {tag.id for tag in tags} != tag_ids:
        raise EventValidationError("A selected tag no longer exists. Refresh the form.")
    if event_id is None:
        return add_event(db, radar, start_time, end_time, description, tags), True
    event = db.session.get(Event, event_id)
    if event is None:
        raise EventValidationError("This event no longer exists. Select another event.")
    imagery_changed = (event.radar_id, event.start_time, event.end_time) != (
        radar.id,
        start_time,
        end_time,
    )
    # Loading the tag relationship must not flush a half-validated edit.
    with db.session.no_autoflush:
        event.radar = radar
        event.start_time = start_time
        event.end_time = end_time
        event.description = description
        event.tags = tags
    _persist_event(db, event)
    return event, imagery_changed


def event_overlaps_existing(db, event):
    """Check if the event overlaps with any existing events."""
    query = db.select(Event.id).where(
        Event.radar == event.radar,
        Event.start_time < event.end_time,
        Event.end_time > event.start_time,
    )
    if event.id is not None:
        query = query.where(Event.id != event.id)
    with db.session.no_autoflush:
        return db.session.scalar(query.limit(1)) is not None


def events_list():
    """Generate a list of dictionaries containing event information."""
    events = db.session.query(Event).order_by(Event.start_time).all()
    event_list = []
    for event in events:
        e = {
            "id": event.id,
            "radar": event.radar.name,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "description": event.description,
            "tags": [tag.name for tag in event.tags],
        }
        event_list.append(e)
    return event_list
