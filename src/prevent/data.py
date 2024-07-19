"""Populate the database with sample data"""
import datetime

from sqlalchemy import select

from prevent.models import Radar, Event, Tag


def sample_events(db):
    events_table_empty = db.session.execute(select(Event)).scalar_one_or_none() is None
    if not events_table_empty:
        return   
    # add squall line event to fikor radar 2024-07-17 09:30:00 to 2024-07-17 12:00:00 UTC
    fikor = db.session.execute(select(Radar).filter_by(name="fikor")).scalar_one()
    squall_line = db.session.execute(select(Tag).filter_by(name="squall line")).scalar_one()
    sl_event = Event(
        radar=fikor,
        tags=[squall_line],
        start_time=datetime.datetime(2024, 7, 17, 9, 30, 0),
        end_time=datetime.datetime(2024, 7, 17, 12, 0, 0),
        description='Squall line event at fikor radar'
    )
    db.session.add(sl_event)
    db.session.commit()