import os
import datetime

from dash import Dash, dcc, html, Input, Output
from dash.long_callback import CeleryLongCallbackManager
import dash_leaflet as dl
from celery import Celery
from sqlalchemy import select

from prevent.database.models import Event, Radar, Tag
from prevent.database.queries import get_coords
from prevent.database.connection import db
from prevent.terradarcotta import insert_event as sync_insert_event
from prevent.secrets import FMI_COMMERCIAL_API_KEY


WMS_MAP = f'https://wms.fmi.fi/fmi-apikey/{FMI_COMMERCIAL_API_KEY}/geoserver/wms'
DATABASE_URI = os.environ.get('DATABASE_URI', 'postgresql://preventuser:kukkakaalisinappi@localhost/prevent')


def create_app():
    celery_app = Celery('prevent', broker='redis://localhost:6379/0', backend='redis://localhost:6379/1')
    callman = CeleryLongCallbackManager(celery_app)
    app = Dash(__name__, long_callback_manager=callman)
    server = app.server
    server.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
    db.init_app(server)
    return app, server, celery_app


def initial_db_setup():
    print('Setting up database')
    with server.app_context():
        db.create_all()
        db.session.commit()
        sample_events(db)


def create_layout():
    return html.Div([
        dcc.Interval(id='startup-interval', interval=1, n_intervals=0, max_intervals=1),
        html.Div([
            dcc.Dropdown(id='event-dropdown'),
            html.Div(id='selected-event')
        ], style={'width': '30%', 'display': 'inline-block'}),
        html.Div([
            dl.Map([dl.WMSTileLayer(url=WMS_MAP, layers='KAP:BasicMap version 7', format='image/png')],
                id='map', center=(61.9241, 25.7482), zoom=6,
                style={'width': '100%', 'height': '98vh'})
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
    #insert_event(event)
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
    Output('startup-interval', 'disabled'),
    Input('startup-interval', 'n_intervals')
)
def run_initial_db_setup(n_intervals):
    """Run initial database setup when the app starts."""
    if n_intervals == 0:
        initial_db_setup()
    return True


@app.callback(
    Output('event-dropdown', 'options'),
    Input('event-dropdown', 'id'),
    Input('startup-interval', 'disabled')
)
def populate_dropdown(_, __):
    events = db.session.query(Event).all()
    if not events:
        events = sample_events(db)
    return [{'label': event.description, 'value': event.id} for event in events]


@app.callback(
    Output('selected-event', 'children'),
    Input('event-dropdown', 'value'),
    Input('startup-interval', 'disabled')
)
def update_selected_event(event_id, _):
    if event_id:
        event = db.session.query(Event).get(event_id)
        return f"Selected Event: {event.description}"
    else:
        return "Select an event"


@app.callback(
    Output('map', 'center'),
    Output('map', 'zoom'),
    Input('event-dropdown', 'value')
)
def update_map(event_id):
    if event_id:
        event = db.session.query(Event).get(event_id)
        lat, lon = get_coords(db, event.radar)  # Assuming get_coords is defined elsewhere
        return (lat, lon), 9
    else:
        return (61.9241, 25.7482), 6


def main(**kws):
    app.run_server(host='0.0.0.0', **kws)


if __name__ == '__main__':
    main(debug=True)