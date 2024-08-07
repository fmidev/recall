"""Methods for interacting with the database."""

import datetime

from sqlalchemy import select

from prevent.terracotta.ingest import insert_event
from prevent.database.models import Event, Radar, Tag


def get_coords(db, radar):
    lat = db.session.scalar(radar.location.ST_Y())
    lon = db.session.scalar(radar.location.ST_X())
    return lat, lon


def add_event(db, radar, start_time, end_time, description, tags=None):
    """Add an event to the database."""
    event = Event(
        radar=radar,
        tags=tags,
        start_time=start_time,
        end_time=end_time,
        description=description
    )
    insert_event(event)
    db.session.add(event)
    db.session.commit()
    return event


def sample_events(db):
    events_table_empty = db.session.execute(select(Event)).scalar_one_or_none() is None
    if not events_table_empty:
        return
    fikor = db.session.execute(select(Radar).filter_by(name="fikor")).scalar_one()
    rain = db.session.execute(select(Tag).filter_by(name="rain")).scalar_one()
    events = []
    events.append(add_event(
        db,
        radar=fikor,
        start_time=datetime.datetime(2023, 8, 28, 10, 0, 0),
        end_time=datetime.datetime(2023, 8, 28, 11, 0, 0),
        description='Low pressure system',
        tags=[rain]
    ))
    return events