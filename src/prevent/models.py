from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from geoalchemy2 import Geography

Base = declarative_base()

class Radar(Base):
    __tablename__ = 'Radar'
    radar_id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    location = Column(Geography(geometry_type='POINT', srid=3067))
    description = Column(Text)
    events = relationship("Event", back_populates="radar")

class Event(Base):
    __tablename__ = 'Event'
    event_id = Column(Integer, primary_key=True)
    radar_id = Column(Integer, ForeignKey('Radar.radar_id'), nullable=False)
    start_time = Column(TIMESTAMP, nullable=False)
    end_time = Column(TIMESTAMP, nullable=False)
    description = Column(Text)
    radar = relationship("Radar", back_populates="events")
    tags = relationship("Tag", secondary="Event_Tag", back_populates="events")

class Tag(Base):
    __tablename__ = 'Tag'
    tag_id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    events = relationship("Event", secondary="Event_Tag", back_populates="tags")

class EventTag(Base):
    __tablename__ = 'EventTag'
    event_id = Column(Integer, ForeignKey('Event.event_id'), primary_key=True)
    tag_id = Column(Integer, ForeignKey('Tag.tag_id'), primary_key=True)

# Engine and session creation for demonstration (adjust the connection string as needed)
engine = create_engine('postgresql://preventuser:kukkakaalisinappi@localhost/preventdb')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()