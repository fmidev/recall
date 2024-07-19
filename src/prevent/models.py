from typing import List, Optional
import datetime

from sqlalchemy import Column, String, Text, ForeignKey
from sqlalchemy.orm import relationship, DeclarativeBase, mapped_column, Mapped
from geoalchemy2 import Geography
from flask_sqlalchemy import SQLAlchemy


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class Radar(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(10))
    location: Mapped[Geography] = mapped_column(Geography(geometry_type='POINT', srid=4326))
    description: Mapped[Optional[str]] = Column(Text)
    events: Mapped[List['Event']] = relationship(back_populates="radar")


class Event(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    radar_id: Mapped[int] = mapped_column(ForeignKey('radar.id'))
    start_time: Mapped[datetime.datetime]
    end_time: Mapped[datetime.datetime]
    description = Column(Text)
    radar: Mapped['Radar'] = relationship(back_populates="events")
    tags: Mapped[List['Tag']] = relationship(secondary="event_tag", back_populates="events")


class Tag(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = Column(Text)
    events: Mapped[List['Event']] = relationship(secondary="event_tag", back_populates="tags")


class EventTag(db.Model):
    __tablename__ = 'event_tag'
    event_id: Mapped[int] = mapped_column(ForeignKey('event.id'), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey('tag.id'), primary_key=True)

