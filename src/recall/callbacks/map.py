from dash import callback, Output, Input
import dash_leaflet as dl

from recall.aios import PlaybackSliderAIO
from recall.database import list_scan_timestamps
from recall.database.connection import db
from recall.database.models import Event
from recall.database.queries import get_coords
from recall.layout import BASEMAP
from recall.terracotta.client import get_singleband_url
from recall.visuals import cmap2hex


DEFAULT_COORDS = (64.0, 26.5)
RADAR_LAYER_OPACITY = 0.8


@callback(
    Output('map', 'children'),
    Output('map-timestamp', 'children'),
    Input('event-dropdown', 'value'),
    Input(PlaybackSliderAIO.ids.slider('playback'), 'value'),
)
def update_radar_layers(event_id: int, slider_val: int):
    """Update the radar image URL based on the selected event."""
    cmap = 'gist_ncar'
    layers = list(BASEMAP)
    if not event_id:
        return layers, ''
    event = db.session.query(Event).get(event_id)
    timestamps = list_scan_timestamps(event)
    radar_name = event.radar.name
    product = 'DBZH'
    itimestep = slider_val
    for i, timestamp in enumerate(timestamps):
        url = get_singleband_url(timestamp, radar_name, product, colormap=cmap+'_cut', stretch_range='[0,255]')
        opacity = RADAR_LAYER_OPACITY if i == itimestep else 0.0
        layers.append(dl.TileLayer(id=f'scan{i}', url=url, opacity=opacity))
    layers.append(dl.Colorbar(id='cbar', colorscale=cmap2hex(cmap),
                              nTicks=5, width=20, height=250, min=-32, max=96, position='topright'))
    return layers, timestamps[itimestep].strftime('%Y-%m-%d %H:%M UTC')


@callback(
    Output('map', 'viewport'),
    Input('event-dropdown', 'value')
)
def update_viewport(event_id: int):
    """Update the map viewport based on the selected event."""
    if event_id:
        event = db.session.query(Event).get(event_id)
        lat, lon = get_coords(db, event.radar)
        return dict(center=(lat, lon), zoom=8, transition='flyTo')
    return dict(center=DEFAULT_COORDS, zoom=6, transition='flyTo')
