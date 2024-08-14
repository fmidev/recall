"""Dash app for visualizing radar case studies."""

import os
import datetime

from dash import Dash, Input, Output, State, no_update, CeleryManager
from dash.exceptions import PreventUpdate
import dash_leaflet as dl
import dash_bootstrap_components as dbc
from celery import Celery
from flask_migrate import Migrate

from prevent.database import list_scan_timestamps
from prevent.database.models import Event, Tag, Radar
from prevent.database.queries import get_coords, initial_db_setup, add_event
from prevent.database.connection import db
from prevent.layout import BASEMAP, create_layout
from prevent.terracotta.client import get_singleband_url
from prevent.terracotta.ingest import insert_event
from prevent.aios import PlaybackSliderAIO
from prevent.visuals import cmap2hex


DEFAULT_COORDS = (64.0, 26.5)
DATABASE_URI = os.environ.get('PREVENT_DB_URI', 'postgresql://postgres:postgres@localhost/prevent')
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
COLORMAPS_DIR = os.environ.get('TC_EXTRA_CMAP_FOLDER', '/tmp/prevent/colormaps')


def create_app():
    celery_app = Celery(__name__, broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
    callman = CeleryManager(celery_app)
    app = Dash(
        __name__, 
        background_callback_manager=callman,
        external_stylesheets=[
            dbc.themes.BOOTSTRAP,
            dbc.icons.FONT_AWESOME
        ]
    )
    server = app.server
    server.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
    db.init_app(server)
    migrate = Migrate(server, db)
    return app, server, celery_app, migrate


app, server, celery_app, migrate = create_app()
app.layout = create_layout()


@app.callback(
    output=Output('startup-interval', 'disabled'),
    inputs=[Input('startup-interval', 'n_intervals')],
    background=True,
    running=[(Output('event-dropdown', 'disabled'), True, False)]
)
def run_initial_setup(n_intervals):
    """Run initial setup when the app starts."""
    if n_intervals == 0:
        initial_db_setup(db, server)
    return True


@app.callback(
    output=(
        Output('add-event', 'n_clicks'),
        Output('events-update-signal', 'data', allow_duplicate=True),
    ),
    inputs=[
        Input('add-event', 'n_clicks'),
        State('date-span', 'start_date'),
        State('date-span', 'end_date'),
        State('start-time', 'value'),
        State('end-time', 'value'),
        State('event-description', 'value'),
        State('radar-picker', 'value'),
        State('tag-picker', 'value'),
    ],
    background=True,
    running=[
        (Output('add-event', 'children'), 'Submitting event...', 'Add new'),
    ],
    prevent_initial_call=True
)
def submit_event(n_clicks, start_date, end_date, start_time, end_time, description, radar_id, tag_ids):
    """Submit an event to the database."""
    if not n_clicks:
        raise PreventUpdate
    start_time = f"{start_date} {start_time}"
    end_time = f"{end_date} {end_time}"
    with server.app_context():
        radar = db.session.query(Radar).get(radar_id)
        tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        start_time = datetime.datetime.strptime(start_time, '%Y-%m-%d %H:%M')
        end_time = datetime.datetime.strptime(end_time, '%Y-%m-%d %H:%M')
        print(f"Adding event: {start_time} - {end_time} {description} {radar.name}")
        add_event(db, radar, start_time, end_time, description, tags)
    return 0, {'status': 'added'}


@app.callback(
    output=(
        Output('save-event', 'n_clicks'),
        Output('events-update-signal', 'data', allow_duplicate=True),
    ),
    inputs=[
        Input('save-event', 'n_clicks'),
        State('event-dropdown', 'value'),
        State('date-span', 'start_date'),
        State('date-span', 'end_date'),
        State('start-time', 'value'),
        State('end-time', 'value'),
        State('event-description', 'value'),
        State('radar-picker', 'value'),
        State('tag-picker', 'value'),
    ],
    background=True,
    running=[(Output('save-event', 'children'), 'Updating event...', 'Save changes')],
    prevent_initial_call=True
)
def update_event(n_clicks, event_id, start_date, end_date, start_time, end_time, description, radar_id, tag_ids):
    """Update an event in the database."""
    if not n_clicks:
        raise PreventUpdate
    start_time = f"{start_date} {start_time}"
    end_time = f"{end_date} {end_time}"
    with server.app_context():
        event = db.session.query(Event).get(event_id)
        radar = db.session.query(Radar).get(radar_id)
        tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        start_time = datetime.datetime.strptime(start_time, '%Y-%m-%d %H:%M')
        end_time = datetime.datetime.strptime(end_time, '%Y-%m-%d %H:%M')
        event.radar = radar
        event.start_time = start_time
        event.end_time = end_time
        event.description = description
        event.tags = tags
        db.session.commit()
        insert_event(event)
    return 0, {'status': 'updated'}


@app.callback(
    output=Output('ingest-all', 'n_clicks'),
    inputs=[Input('ingest-all', 'n_clicks')],
    background=True,
    running=[(Output('ingest-all', 'children'), 'Ingesting events...', 'Ingest all')]
)
def ingest_all_events(n_clicks):
    """Ingest all events to the terracotta database."""
    if not n_clicks:
        raise PreventUpdate
    with server.app_context():
        events = db.session.query(Event).all()
        for event in events:
            insert_event(event)
    return 0


@app.callback(
    Output('map', 'children'),
    Input('event-dropdown', 'value'),
    Input(PlaybackSliderAIO.ids.slider('playback'), 'value'),
    Input(PlaybackSliderAIO.ids.slider('playback'), 'drag_value')
)
def update_radar_layers(event_id, slider_val, drag_val):
    """Update the radar image URL based on the selected event."""
    cmap = 'gist_ncar'
    layers = list(BASEMAP)
    if not event_id:
        return layers
    event = db.session.query(Event).get(event_id)
    timestamps = list_scan_timestamps(event)
    radar_name = event.radar.name
    product = 'DBZH'
    itimestep = drag_val or slider_val
    for i, timestamp in enumerate(timestamps):
        url = get_singleband_url(timestamp, radar_name, product, colormap=cmap+'_cut', stretch_range='[0,255]')
        opacity = 0.7 if i == itimestep else 0.0
        layers.append(dl.TileLayer(id=f'scan{i}', url=url, opacity=opacity))
    layers.append(dl.Colorbar(id='cbar', colorscale=cmap2hex(cmap),
                              nTicks=5, width=20, height=250, min=-32, max=96, position='topright'))
    return layers


@app.callback(
    Output(PlaybackSliderAIO.ids.slider('playback'), 'marks'),
    Output(PlaybackSliderAIO.ids.slider('playback'), 'max'),
    Input('event-dropdown', 'value'),
    Input('events-update-signal', 'data')
)
def update_slider_marks(event_id, _):
    """Update the slider marks based on the selected event."""
    marks = {}
    if not event_id:
        return marks, 1
    event = db.session.query(Event).get(event_id)
    timestamps = list_scan_timestamps(event)
    for i, timestamp in enumerate(timestamps):
        marks[i] = {'label': timestamp.strftime('%H:%M')}
    return marks, i


@app.callback(
    Output('event-dropdown', 'options'),
    Input('events-update-signal', 'data'),
    Input('startup-interval', 'disabled')
)
def populate_event_dropdown(_, __):
    """Populate the event dropdown with events from the database."""
    events = db.session.query(Event).all()
    if not events:
        print('No events found')
        raise PreventUpdate
    # Label is the event start date and radar name
    options = []
    for event in events:
        tags = ', '.join([tag.name for tag in event.tags])
        label = f"{event.start_time.strftime('%Y-%m-%d')} {event.radar.name}: {tags}"
        options.append({'label': label, 'value': event.id})
    return options


@app.callback(
    Output('radar-picker', 'options'),
    Input('startup-interval', 'disabled')
)
def populate_radar_picker(_):
    """Populate the radar picker with radars from the database."""
    radars = db.session.query(Radar).all()
    if not radars:
        print('No radars found')
        raise PreventUpdate
    options = [{'label': radar.name, 'value': radar.id} for radar in radars]
    return options


@app.callback(
    Output('tag-picker', 'options'),
    Input('startup-interval', 'disabled')
)
def populate_tag_picker(_):
    """Populate the tag picker with tags from the database."""
    tags = db.session.query(Tag).all()
    if not tags:
        print('No tags found')
        raise PreventUpdate
    options = [{'label': tag.name, 'value': tag.id} for tag in tags]
    return options


@app.callback(
    Output('date-span', 'start_date'),
    Output('date-span', 'end_date'),
    Output('start-time', 'value'),
    Output('end-time', 'value'),
    Output('event-description', 'value'),
    Output('radar-picker', 'value'),
    Output('tag-picker', 'value'),
    Output('delete-event', 'disabled'),
    Output('save-event', 'disabled'),
    Input('event-dropdown', 'value'),
    Input('startup-interval', 'disabled')
)
def update_selected_event(event_id, _):
    """Update the selected event text based on the selected event."""
    if event_id:
        event = db.session.query(Event).get(event_id)
        start_date = event.start_time.strftime('%Y-%m-%d')
        end_date = event.end_time.strftime('%Y-%m-%d')
        start_time = event.start_time.strftime('%H:%M')
        end_time = event.end_time.strftime('%H:%M')
        description = event.description
        radar_id = event.radar.id
        tag_ids = [tag.id for tag in event.tags]
        return start_date, end_date, start_time, end_time, description, radar_id, tag_ids, False, False
    return None, None, '', '', '', None, [], True, True


@app.callback(
    Output('delete-event', 'n_clicks'),
    Output('event-dropdown', 'value'),
    Output('events-update-signal', 'data', allow_duplicate=True),
    Input('delete-event', 'n_clicks'),
    State('event-dropdown', 'value'),
    prevent_initial_call=True
)
def delete_event(n_clicks, event_id):
    """Delete the selected event from the database."""
    if not n_clicks:
        raise PreventUpdate
    event = db.session.query(Event).get(event_id)
    db.session.delete(event)
    db.session.commit()
    return 0, None, {'status': 'deleted'}


@app.callback(
    Output('map', 'viewport'),
    Input('event-dropdown', 'value')
)
def update_viewport(event_id):
    """Update the map viewport based on the selected event."""
    if event_id:
        event = db.session.query(Event).get(event_id)
        lat, lon = get_coords(db, event.radar)
        return dict(center=(lat, lon), zoom=8, transition='flyTo')
    else:
        return dict(center=DEFAULT_COORDS, zoom=6, transition='flyTo')


def main(**kws):
    app.run_server(host='0.0.0.0', **kws)


if __name__ == '__main__':
    main(debug=True)