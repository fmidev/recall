"""Methods for interacting with the database."""


def get_coords(db, radar):
    lat = db.session.scalar(radar.location.ST_Y())
    lon = db.session.scalar(radar.location.ST_X())
    return lat, lon