-- Insert Radar Data
INSERT INTO Radar (name, location, description)
VALUES ('fikor', ST_MakePoint(21.64, 60.13), 'Korppoo');

-- Insert Event Data
-- Assuming the radar_id of 'fikor' radar is 1
INSERT INTO Event (radar_id, start_time, end_time, description)
VALUES (1, '2024-07-17 09:30:00', '2024-07-17 12:00:00', 'Squall line approaching the coast.');

-- Insert Tag Data (Optional)
INSERT INTO Tag (name, description)
VALUES ('Squall Line', 'A line of severe thunderstorms that can form along and/or ahead of a cold front.');

-- Associate Event with Tag (Optional)
-- Assuming the tag_id for 'Squall Line' is 1 and the event_id for the inserted event is 1
INSERT INTO EventTag (event_id, tag_id)
VALUES (1, 1);