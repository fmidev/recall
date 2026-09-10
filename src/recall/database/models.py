from typing import List, Optional
import datetime

from sqlalchemy import CheckConstraint, Column, String, Text, ForeignKey, column, func
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import mapped_column, Mapped
from geoalchemy2 import Geography

from recall.database.connection import db


event_tag_m2m = db.Table(
    "event_tag",
    Column("event_id", ForeignKey("event.id"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id"), primary_key=True),
)

tag_tag_m2m = db.Table(
    "tag_tag",
    Column("parent_tag_id", ForeignKey("tag.id"), primary_key=True),
    Column("child_tag_id", ForeignKey("tag.id"), primary_key=True),
)


class Radar(db.Model):
    __tablename__ = "radar"
    id: Mapped[int] = mapped_column(primary_key=True)
    fmisid: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(10), unique=True)
    location: Mapped[Geography] = mapped_column(
        Geography(geometry_type="POINT", srid=4326)
    )
    description: Mapped[Optional[str]] = Column(Text)
    events: Mapped[List["Event"]] = db.relationship(back_populates="radar")


class Event(db.Model):
    __tablename__ = "event"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="event_positive_interval"),
        CheckConstraint(
            "date_trunc('minute', start_time) = start_time "
            "AND extract(minute FROM start_time)::integer % 5 = 0 "
            "AND date_trunc('minute', end_time) = end_time "
            "AND extract(minute FROM end_time)::integer % 5 = 0",
            name="event_five_minute_alignment",
        ),
        ExcludeConstraint(
            ("radar_id", "="),
            (
                func.tsrange(column("start_time"), column("end_time"), "[)"),
                "&&",
            ),
            name="event_radar_no_overlap",
            using="gist",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    radar_id: Mapped[int] = mapped_column(ForeignKey("radar.id"))
    start_time: Mapped[datetime.datetime]
    end_time: Mapped[datetime.datetime]
    description = Column(Text)
    radar: Mapped["Radar"] = db.relationship(back_populates="events")
    tags: Mapped[List["Tag"]] = db.relationship(
        secondary=event_tag_m2m, back_populates="events"
    )


class Tag(db.Model):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = Column(Text)
    events: Mapped[List["Event"]] = db.relationship(
        secondary=event_tag_m2m, back_populates="tags"
    )
    parent_tags: Mapped[List["Tag"]] = db.relationship(
        secondary=tag_tag_m2m,
        primaryjoin=id == tag_tag_m2m.c.child_tag_id,
        secondaryjoin=id == tag_tag_m2m.c.parent_tag_id,
        back_populates="child_tags",
    )
    child_tags: Mapped[List["Tag"]] = db.relationship(
        secondary=tag_tag_m2m,
        primaryjoin=id == tag_tag_m2m.c.parent_tag_id,
        secondaryjoin=id == tag_tag_m2m.c.child_tag_id,
        back_populates="parent_tags",
    )
