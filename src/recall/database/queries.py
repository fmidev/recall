"""Methods for interacting with the database."""

import datetime

from recall.database.connection import db

from recall.terracotta.ingest import insert_event
from recall.database.models import Event, Radar, Tag


def get_coords(db, radar):
    lat = db.session.scalar(radar.location.ST_Y())
    lon = db.session.scalar(radar.location.ST_X())
    return lat, lon


def add_event(db, radar, start_time, end_time, description, tags=None, **kws):
    """Add an event to the database."""
    event = Event(
        radar=radar,
        tags=tags,
        start_time=start_time,
        end_time=end_time,
        description=description
    )
    if event_overlaps_existing(db, event):
        raise ValueError('Event overlaps with existing event')
    insert_event(event, **kws)
    db.session.add(event)
    db.session.commit()
    return event


def event_overlaps_existing(db, event):
    """Check if the event overlaps with any existing events."""
    events = db.session.query(Event).filter(Event.radar == event.radar).all()
    for e in events:
        cond1 = e.start_time <= event.start_time <= e.end_time
        cond2 = e.start_time <= event.end_time <= e.end_time
        if cond1 or cond2:
            return True
    return False


def sample_events(db):
    events_table_empty = db.session.execute(db.select(Event)).first() is None
    if not events_table_empty:
        return
    fikor = db.session.execute(db.select(Radar).filter_by(name="fikor")).scalar_one()
    rain = db.session.execute(db.select(Tag).filter_by(name="rain")).scalar_one()
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


def initial_db_setup(db, server):
    print('Setting up database')
    with server.app_context():
        db.create_all()
        db.session.commit()
        sample_events(db)


def events_list():
    """Generate a list of dictionaries containing event information."""
    events = db.session.query(Event).order_by(Event.start_time).all()
    event_list = []
    for event in events:
        e = {
            'id': event.id,
            'radar': event.radar.name,
            'start_time': event.start_time,
            'end_time': event.end_time,
            'description': event.description,
            'tags': [tag.name for tag in event.tags]
        }
        event_list.append(e)
    return event_list
