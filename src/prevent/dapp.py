"""Dash app for visualizing radar case studies."""

import os

from dash import Dash, dcc, html, Input, Output
from dash.long_callback import CeleryLongCallbackManager
from dash.exceptions import PreventUpdate
import dash_leaflet as dl
import dash_bootstrap_components as dbc
from celery import Celery

from prevent.database import list_scan_timestamps
from prevent.database.models import Event
from prevent.database.queries import get_coords, initial_db_setup
from prevent.database.connection import db
from prevent.terracotta.client import get_singleband_url
from prevent.secrets import FMI_COMMERCIAL_API_KEY
from prevent.aios import PlaybackSliderAIO
from prevent.visuals import cmap2hex


DEFAULT_COORDS = (64.0, 26.5)
WMS_MAP = f'https://wms.fmi.fi/fmi-apikey/{FMI_COMMERCIAL_API_KEY}/geoserver/wms'
DATABASE_URI = os.environ.get('PREVENT_DB_URI', 'postgresql://postgres:postgres@localhost/prevent')
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
COLORMAPS_DIR = os.environ.get('TC_EXTRA_CMAP_FOLDER', '/tmp/prevent/colormaps')
BASEMAP = (
    dl.WMSTileLayer(url=WMS_MAP, layers='KAP:BasicMap version 7', format='image/png'),
    dl.WMSTileLayer(url=WMS_MAP, layers='KAP:radars_finland', format='image/png', transparent=True)
)


def create_app():
    celery_app = Celery('prevent', broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
    callman = CeleryLongCallbackManager(celery_app)
    app = Dash(
        __name__, 
        long_callback_manager=callman,
        external_stylesheets=[
            dbc.themes.BOOTSTRAP,
            dbc.icons.FONT_AWESOME
        ]
    )
    server = app.server
    server.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
    db.init_app(server)
    return app, server, celery_app


def create_layout():
    return dbc.Container([
        dcc.Interval(id='startup-interval', interval=1, n_intervals=0, max_intervals=1),
        dbc.Row([
            dbc.Col([
                dcc.Dropdown(id='event-dropdown'),
                html.Div(id='selected-event'),
                PlaybackSliderAIO(
                    aio_id='playback',
                    slider_props={'min': 0, 'max': 1, 'step': 1, 'value': 0},
                    button_props={'className': 'float-left'}
                )
            ], lg=4),
            dbc.Col([
                dl.Map(children=BASEMAP,
                    id='map', center=(61.9241, 25.7482), zoom=6,
                    style={'width': '100%', 'height': '100vh'})
            ])
        ])
    ], fluid=True)


app, server, celery_app = create_app()
app.layout = create_layout()


@app.long_callback(
    output=Output('startup-interval', 'disabled'),
    inputs=[Input('startup-interval', 'n_intervals')],
    running=[(Output('event-dropdown', 'disabled'), True, False),
             (Output('selected-event', 'children'), 'Initializing events. This may take a while.', 'Ready.')]
)
def run_initial_setup(n_intervals):
    """Run initial setup when the app starts."""
    if n_intervals == 0:
        initial_db_setup(db, server)
    return True


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
    Input('event-dropdown', 'value')
)
def update_slider_marks(event_id):
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
    output=Output('event-dropdown', 'options'),
    inputs=[Input('event-dropdown', 'id'),
            Input('startup-interval', 'disabled')]
)
def populate_dropdown(_, __):
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
    Output('selected-event', 'children'),
    Input('event-dropdown', 'value'),
    Input('startup-interval', 'disabled')
)
def update_selected_event(event_id, _):
    """Update the selected event text based on the selected event."""
    if event_id:
        event = db.session.query(Event).get(event_id)
        return f"Selected Event: {event.description}"
    else:
        return "Select an event"


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