from typing import List, Optional
import datetime

from sqlalchemy import Column, String, Text, ForeignKey, event
from sqlalchemy.orm import mapped_column, Mapped
from geoalchemy2 import Geography

from prevent.database.connection import db


event_tag_m2m = db.Table(
    'event_tag',
    Column('event_id', ForeignKey('event.id'), primary_key=True),
    Column('tag_id', ForeignKey('tag.id'), primary_key=True),
)

tag_tag_m2m = db.Table(
    'tag_tag',
    Column('parent_tag_id', ForeignKey('tag.id'), primary_key=True),
    Column('child_tag_id', ForeignKey('tag.id'), primary_key=True),
)


class Radar(db.Model):
    __tablename__ = 'radar'
    id: Mapped[int] = mapped_column(primary_key=True)
    fmisid: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(10), unique=True)
    location: Mapped[Geography] = mapped_column(Geography(geometry_type='POINT', srid=4326))
    description: Mapped[Optional[str]] = Column(Text)
    events: Mapped[List['Event']] = db.relationship(back_populates="radar")


class Event(db.Model):
    __tablename__ = 'event'
    id: Mapped[int] = mapped_column(primary_key=True)
    radar_id: Mapped[int] = mapped_column(ForeignKey('radar.id'))
    start_time: Mapped[datetime.datetime]
    end_time: Mapped[datetime.datetime]
    description = Column(Text)
    radar: Mapped['Radar'] = db.relationship(back_populates="events")
    tags: Mapped[List['Tag']] = db.relationship(secondary=event_tag_m2m, back_populates="events")


class Tag(db.Model):
    __tablename__ = 'tag'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = Column(Text)
    events: Mapped[List['Event']] = db.relationship(secondary=event_tag_m2m, back_populates="tags")
    parent_tags: Mapped[List['Tag']] = db.relationship(
        secondary=tag_tag_m2m,
        primaryjoin=id == tag_tag_m2m.c.child_tag_id,
        secondaryjoin=id == tag_tag_m2m.c.parent_tag_id,
        back_populates="child_tags"
    )
    child_tags: Mapped[List['Tag']] = db.relationship(
        secondary=tag_tag_m2m,
        primaryjoin=id == tag_tag_m2m.c.parent_tag_id,
        secondaryjoin=id == tag_tag_m2m.c.child_tag_id,
        back_populates="parent_tags"
    )


@event.listens_for(Radar.__table__, 'after_create')
def insert_radars(*args, **kws):
    radars = [
        Radar(name='fikor', fmisid=100926, location='POINT(21.643379 60.128469)', description='Korppoo'),
        Radar(name='fivih', fmisid=107275, location='POINT(24.49558603 60.5561915)', description='Vihti'),
        Radar(name='fivim', fmisid=101518, location='POINT(23.82086 63.104835)', description='Vimpeli'),
        Radar(name='fiuta', fmisid=101872, location='POINT(26.318877 64.774934)', description='Utajärvi'),
        Radar(name='filuo', fmisid=101939, location='POINT(26.896916 67.139096)', description='Luosto'),
        Radar(name='finur', fmisid=107131, location='POINT(29.44892 63.83786)', description='Nurmes'),
        Radar(name='fikuo', fmisid=101582, location='POINT(27.381468 62.862598)', description='Kuopio'),
        Radar(name='fikes', fmisid=100690, location='POINT(29.79772 61.90699)', description='Kesälahti'),
        Radar(name='fikan', fmisid=107307, location='POINT(22.50204 61.81085)', description='Kankaanpää'),
        Radar(name='fipet', fmisid=103813, location='POINT(25.44008118 62.30451365)', description='Petäjävesi'),
        Radar(name='fianj', fmisid=101234, location='POINT(27.108057 60.903871)', description='Anjalankoski')
    ]
    for radar in radars:
        db.session.add(radar)


@event.listens_for(Radar.__table__, 'after_create')
def insert_basic_tags(*args, **kws):
    tags = [
        Tag(name='squall line', description='A line of thunderstorms that can form along and/or ahead of a cold front.'),
        Tag(name='rain', description='Precipitation in the form of liquid water drops with diameters greater than 0.5 millimetres.'),
        Tag(name='convective', description='A type of weather system that is characterized by vertical motion.'),
        Tag(name='stratiform', description='A broad shield of precipitation with a relatively similar intensity.'),
        Tag(name='doppler snake', description='A doppler filter artifact.'),
        Tag(name='melting', description='Melting layer signature.')
    ]
    for tag in tags:
        db.session.add(tag)