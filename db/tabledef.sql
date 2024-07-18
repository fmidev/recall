-- Description: SQL script to define the database schema

CREATE EXTENSION IF NOT EXISTS postgis;

-- Create Radar table
CREATE TABLE radar (
    radar_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    location GEOGRAPHY(Point, 4326),
    description TEXT
);

-- Create Event table
CREATE TABLE event (
    event_id SERIAL PRIMARY KEY,
    radar_id INT NOT NULL,
    start_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    end_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    description TEXT,
    FOREIGN KEY (radar_id) REFERENCES radar(radar_id)
);

-- Create Tag table
CREATE TABLE tag (
    tag_id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT
);

-- Create EventTag junction table for many-to-many relationship between Event and Tag
CREATE TABLE event_tag (
    event_id INT NOT NULL,
    tag_id INT NOT NULL,
    PRIMARY KEY (event_id, tag_id),
    FOREIGN KEY (event_id) REFERENCES Event(event_id),
    FOREIGN KEY (tag_id) REFERENCES Tag(tag_id)
);