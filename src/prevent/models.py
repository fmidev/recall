from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from geoalchemy2 import Geography

Base = declarative_base()

class Radar(Base):
    __tablename__ = 'radar'
    radar_id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    location = Column(Geography(geometry_type='POINT', srid=4326))
    description = Column(Text)
    events = relationship("Event", back_populates="radar")

class Event(Base):
    __tablename__ = 'event'
    event_id = Column(Integer, primary_key=True)
    radar_id = Column(Integer, ForeignKey('radar.radar_id'), nullable=False)
    start_time = Column(TIMESTAMP, nullable=False)
    end_time = Column(TIMESTAMP, nullable=False)
    description = Column(Text)
    radar = relationship("Radar", back_populates="events")
    tags = relationship("Tag", secondary="event_tag", back_populates="events")

class Tag(Base):
    __tablename__ = 'tag'
    tag_id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    events = relationship("Event", secondary="event_tag", back_populates="tags")

class EventTag(Base):
    __tablename__ = 'event_tag'
    event_id = Column(Integer, ForeignKey('event.event_id'), primary_key=True)
    tag_id = Column(Integer, ForeignKey('tag.tag_id'), primary_key=True)

# Engine and session creation for demonstration (adjust the connection string as needed)
engine = create_engine('postgresql://preventuser:kukkakaalisinappi@localhost/preventdb', echo=True)
Base.metadata.create_all(engine)
