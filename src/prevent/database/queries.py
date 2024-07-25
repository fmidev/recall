"""Methods for interacting with the database."""
import datetime

from sqlalchemy import select

from prevent.database.models import Event, Radar, Tag
from prevent.terradarcotta import insert_event as sync_insert_event


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


def sample_events(db):
    events_table_empty = db.session.execute(select(Event)).scalar_one_or_none() is None
    if not events_table_empty:
        return
    # add squall line event to fikor radar 2024-07-17 09:30:00 to 2024-07-17 12:00:00 UTC
    fikor = db.session.execute(select(Radar).filter_by(name="fikor")).scalar_one()
    squall_line = db.session.execute(select(Tag).filter_by(name="squall line")).scalar_one()
    add_event(
        db,
        radar=fikor,
        start_time=datetime.datetime(2024, 7, 17, 9, 30, 0),
        end_time=datetime.datetime(2024, 7, 17, 12, 0, 0),
        description='Squall line over the coast of Korppoo',
        tags=[squall_line]
    )