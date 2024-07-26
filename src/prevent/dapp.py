import os
import time
import datetime

import dash
from dash import dcc, html
from dash.dependencies import Input, Output
from dash.long_callback import CeleryLongCallbackManager
import dash_leaflet as dl
from celery import Celery
from sqlalchemy import create_engine, select
from sqlalchemy_utils import database_exists, create_database
from sqlalchemy.exc import OperationalError

from prevent.database.models import Event, Radar, Tag
from prevent.database.queries import get_coords
from prevent.database.connection import db
from prevent.terradarcotta import insert_event as sync_insert_event


DATABASE_URI = os.environ.get('DATABASE_URI', 'postgresql://preventuser:kukkakaalisinappi@localhost/prevent')


def ensure_database_exists(uri, retries=5, delay=5):
    """Ensure that the database exists by creating it if it does not."""
    engine = create_engine(uri)
    created = False
    attempt = 0
    while attempt < retries:
        try:
            if not database_exists(engine.url):
                create_database(engine.url)
            break
        except OperationalError as e:
            attempt += 1
            if attempt < retries:
                print(f"Database connection failed. Retrying in {delay} seconds... (Attempt {attempt}/{retries})")
                time.sleep(delay)
            else:
                print(f"Failed to connect to the database after {retries} attempts.")
                raise e
    return created


def create_app():
    db_created = ensure_database_exists(DATABASE_URI)
    celery_app = Celery('prevent', broker='redis://localhost:6379/0', backend='redis://localhost:6379/1')
    callman = CeleryLongCallbackManager(celery_app)
    app = dash.Dash(__name__, long_callback_manager=callman)
    server = app.server
    server.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
    db.init_app(server)
    if db_created:
        with server.app_context():
            initial_db_setup()
    return app, server, celery_app


def initial_db_setup():
    db.create_all()
    db.session.commit()
    sample_events(db)


def create_layout():
    return html.Div([
        html.Div([
            dcc.Dropdown(id='event-dropdown'),
            html.Div(id='selected-event')
        ], style={'width': '30%', 'display': 'inline-block'}),
        html.Div([
            dl.Map([dl.TileLayer(), dl.Marker(position=(61.9241, 25.7482), id="marker")],
                id='map',
                style={'width': '100%', 'height': '80vh'})
        ], style={'width': '70%', 'display': 'inline-block'})
    ])


def add_event(db, radar, start_time, end_time, description, tags=None):
    """Add an event to the database."""
    event = Event(
        radar=radar,
        tags=tags,
        start_time=start_time,
        end_time=end_time,
        description=description
    )
    insert_event(event)
    db.session.add(event)
    db.session.commit()
    return event


def sample_events(db):
    events_table_empty = db.session.execute(select(Event)).scalar_one_or_none() is None
    if not events_table_empty:
        return
    # add squall line event to fikor radar 2024-07-17 09:30:00 to 2024-07-17 12:00:00 UTC
    fikor = db.session.execute(select(Radar).filter_by(name="fikor")).scalar_one()
    squall_line = db.session.execute(select(Tag).filter_by(name="squall line")).scalar_one()
    events = []
    events.append(add_event(
        db,
        radar=fikor,
        start_time=datetime.datetime(2024, 7, 17, 9, 30, 0),
        end_time=datetime.datetime(2024, 7, 17, 12, 0, 0),
        description='Squall line over the coast of Korppoo',
        tags=[squall_line]
    ))
    return events


app, server, celery_app = create_app()
app.layout = create_layout()


@celery_app.task
def insert_event(event):
    sync_insert_event(event)


@app.callback(
    Output('event-dropdown', 'options'),
    [Input('event-dropdown', 'id')]
)
def populate_dropdown(_):
    events = db.session.query(Event).all()
    if not events:
        events = sample_events(db)
    return [{'label': event.description, 'value': event.id} for event in events]


@app.callback(
    Output('selected-event', 'children'),
    [Input('event-dropdown', 'value')]
)
def update_selected_event(event_id):
    if event_id:
        event = db.session.query(Event).get(event_id)
        lat, lon = get_coords(event.radar)  # Assuming get_coords is defined elsewhere
        return f"Selected Event: {event.description}"
    else:
        return "Select an event"


@app.callback(
    [Output('map', 'center'), Output('map', 'zoom'), Output('selected-event', 'children')],
    [Input('event-dropdown', 'value')]
)
def update_map(event_id):
    if event_id:
        event = db.session.query(Event).get(event_id)
        lat, lon = get_coords(event.radar)  # Assuming get_coords is defined elsewhere
        return (lat, lon), 9, f"Selected Event: {event.description}"
    else:
        return (61.9241, 25.7482), 6, "Select an event"


def main(**kws):
    app.run_server(debug=True, host='0.0.0.0', **kws)


if __name__ == '__main__':
    main(debug=True)