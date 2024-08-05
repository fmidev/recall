from typing import List, Optional
import datetime

from sqlalchemy import Column, String, Text, ForeignKey, event
from sqlalchemy.orm import relationship, mapped_column, Mapped
from geoalchemy2 import Geography

from prevent.database.connection import db


class Radar(db.Model):
    __tablename__ = 'radar'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(10), unique=True)
    location: Mapped[Geography] = mapped_column(Geography(geometry_type='POINT', srid=4326))
    description: Mapped[Optional[str]] = Column(Text)
    events: Mapped[List['Event']] = relationship(back_populates="radar")


class Event(db.Model):
    __tablename__ = 'event'
    id: Mapped[int] = mapped_column(primary_key=True)
    radar_id: Mapped[int] = mapped_column(ForeignKey('radar.id'))
    start_time: Mapped[datetime.datetime]
    end_time: Mapped[datetime.datetime]
    description = Column(Text)
    radar: Mapped['Radar'] = relationship(back_populates="events")
    tags: Mapped[List['Tag']] = relationship(secondary="event_tag", back_populates="events")


class Tag(db.Model):
    __tablename__ = 'tag'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = Column(Text)
    events: Mapped[List['Event']] = relationship(secondary="event_tag", back_populates="tags")


class EventTag(db.Model):
    __tablename__ = 'event_tag'
    event_id: Mapped[int] = mapped_column(ForeignKey('event.id'), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey('tag.id'), primary_key=True)


@event.listens_for(Radar.__table__, 'after_create')
def insert_radars(*args, **kws):
    radars = []
    radars.append(Radar(name='fikor', location='POINT(21.64 60.13)', description='Korppoo'))
    for radar in radars:
        db.session.add(radar)


@event.listens_for(Radar.__table__, 'after_create')
def insert_basic_tags(*args, **kws):
    tags = []
    tags.append(Tag(name='squall line', description='A line of thunderstorms that can form along and/or ahead of a cold front.'))
    tags.append(Tag(name='rain', description='Precipitation in the form of liquid water drops with diameters greater than 0.5 millimetres.'))
    tags.append(Tag(name='convective', description='A type of weather system that is characterized by vertical motion.'))
    for tag in tags:
        db.session.add(tag)