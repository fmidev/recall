"""Dash app for visualizing radar case studies."""

import os
import datetime

from dash import Dash, Input, Output, State, ALL, CeleryManager
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
from prevent.utils import timestamp_marks
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
        State('start-time', 'value'),
        State('end-time', 'value'),
        State('event-description', 'value'),
        State('radar-picker', 'value'),
        State('tag-picker', 'value'),
    ],
    background=True,
    running=[
        (Output('add-event', 'children'), 'Submitting event...', 'Save as new'),
        (Output('event-form-progress', 'class_name'), '', 'd-none'),
    ],
    progress=[
        Output('event-form-progress', 'value'),
        Output('event-form-progress', 'max'),
        Output('event-form-progress', 'label'),
    ],
    prevent_initial_call=True
)
def submit_event(set_progress, n_clicks, start_time, end_time, description, radar_id, tag_ids):
    """Submit an event to the database."""
    if not n_clicks:
        raise PreventUpdate
    with server.app_context():
        radar = db.session.query(Radar).get(radar_id)
        tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        start_time = datetime.datetime.fromisoformat(start_time)
        end_time = datetime.datetime.fromisoformat(end_time)
        print(f"Adding event: {start_time} - {end_time} {description} {radar.name}")
        add_event(db, radar, start_time, end_time, description, tags, set_progress=set_progress)
    return 0, {'status': 'added'}


@app.callback(
    output=(
        Output('save-event', 'n_clicks'),
        Output('events-update-signal', 'data', allow_duplicate=True),
    ),
    inputs=[
        Input('save-event', 'n_clicks'),
        State('event-dropdown', 'value'),
        State('start-time', 'value'),
        State('end-time', 'value'),
        State('event-description', 'value'),
        State('radar-picker', 'value'),
        State('tag-picker', 'value'),
    ],
    background=True,
    running=[
        (Output('save-event', 'children'), 'Updating event...', 'Save changes'),
        (Output('event-form-progress', 'class_name'), 'my-3', 'd-none'),
    ],
    progress=[
        Output('event-form-progress', 'value'),
        Output('event-form-progress', 'max'),
        Output('event-form-progress', 'label'),
    ],
    prevent_initial_call=True
)
def update_event(set_progress, n_clicks, event_id, start_time, end_time, description, radar_id, tag_ids):
    """Update an event in the database."""
    if not n_clicks:
        raise PreventUpdate
    with server.app_context():
        event = db.session.query(Event).get(event_id)
        radar = db.session.query(Radar).get(radar_id)
        tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        start_time = datetime.datetime.fromisoformat(start_time)
        end_time = datetime.datetime.fromisoformat(end_time)
        event.radar = radar
        event.start_time = start_time
        event.end_time = end_time
        event.description = description
        event.tags = tags
        db.session.commit()
        insert_event(event, set_progress=set_progress)
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
)
def update_radar_layers(event_id, slider_val):
    """Update the radar image URL based on the selected event."""
    cmap = 'gist_ncar'
    layers = list(BASEMAP)
    if not event_id:
        return layers
    event = db.session.query(Event).get(event_id)
    timestamps = list_scan_timestamps(event)
    radar_name = event.radar.name
    product = 'DBZH'
    itimestep = slider_val
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
    if not event_id:
        return {}, 1
    event = db.session.query(Event).get(event_id)
    timestamps = list_scan_timestamps(event)
    marks = timestamp_marks(timestamps)
    return marks, len(timestamps) - 1


@app.callback(
    Output('event-dropdown', 'options'),
    Input('events-update-signal', 'data'),
    Input('startup-interval', 'disabled')
)
def populate_event_dropdown(_, __):
    """Populate the event dropdown with events from the database."""
    events = db.session.query(Event).order_by(Event.start_time).all()
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
    radars = db.session.query(Radar).order_by(Radar.name).all()
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
    tags = db.session.query(Tag).order_by(Tag.name).all()
    if not tags:
        print('No tags found')
        raise PreventUpdate
    options = [{'label': tag.name, 'value': tag.id} for tag in tags]
    return options


@app.callback(
    Output('start-time', 'value'),
    Output('end-time', 'value'),
    Output('event-description', 'value'),
    Output('radar-picker', 'value'),
    Output('tag-picker', 'value'),
    Output('delete-event', 'disabled'),
    Output('save-event', 'disabled'),
    Output('playback-container', 'hidden'),
    Input('event-dropdown', 'value'),
    Input('startup-interval', 'disabled')
)
def update_selected_event(event_id, _):
    """Update the selected event text based on the selected event."""
    if event_id:
        event = db.session.query(Event).get(event_id)
        start_time = event.start_time.isoformat()
        end_time = event.end_time.isoformat()
        description = event.description
        radar_id = event.radar.id
        tag_ids = [tag.id for tag in event.tags]
        return start_time, end_time, description, radar_id, tag_ids, False, False, False
    return '', '', '', None, [], True, True, True


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
    Output('tag-collection', 'children'),
    Output('add-tag', 'disabled'),
    Input('tag-name', 'value'),
    Input('tag-update-signal', 'data'),
    State('selected-tag-id', 'data'),
)
def populate_tag_collection(tag_name, _, selected_tag_id):
    """Populate the tag collection.

    The tag collection holds all tags in the database.
    The matching tags are highlighted.
    """
    matching_tags_ids = []
    full_match = False
    if tag_name:
        matching_tags = db.session.query(Tag).filter(Tag.name.ilike(f'%{tag_name}%')).all()
        matching_tags_ids = [tag.id for tag in matching_tags]
        full_match = any(tag.name == tag_name for tag in matching_tags)
    tags = db.session.query(Tag).order_by(Tag.name).all()
    tag_buttons = []
    # Disable the add button if the tag name is empty or tag_name already exists
    adding_disabled = not tag_name or full_match or selected_tag_id > -1
    for tag in tags:
        if tag.id in matching_tags_ids:
            if tag.id == selected_tag_id:
                color = 'primary'
            else:
                color = 'danger' if full_match else 'warning'
        else:
            color = 'secondary'
        button = dbc.Button(
            tag.name,
            id={'type': 'tag-button', 'index': tag.id},
            active=tag.id == selected_tag_id,
            color=color, outline=True, size='sm', class_name='mr-2 mb-2',
        )
        tag_buttons.append(button)
    return tag_buttons, adding_disabled


@app.callback(
    Output('tag-name', 'value'),
    Output('tag-description', 'value'),
    Output('selected-tag-id', 'data'),
    Output('save-tag', 'disabled'),
    Output('delete-tag', 'disabled'),
    State('selected-tag-id', 'data'),
    Input('tag-update-signal', 'data'),
    Input({'type': 'tag-button', 'index': ALL}, 'n_clicks'),
    State({'type': 'tag-button', 'index': ALL}, 'id'),
    prevent_initial_call=True
)
def tag_selected(selected_tag_id, signal, n_clicks, button_ids):
    """Update the tag form based on the selected tag."""
    if any(n_clicks):
        # Find the index of the clicked button
        clicked_index = next(i for i, clicks in enumerate(n_clicks) if clicks)
        button_id = button_ids[clicked_index]
        tag_id = button_id['index']
        if tag_id == selected_tag_id:
            return '', '', -1, True, True
    elif signal.get('status') == 'added':
        tag_id = signal.get('id')
    elif signal.get('status') == 'deleted':
        return '', '', -1, True, True
    else:
        raise PreventUpdate
    tag = db.session.query(Tag).get(tag_id)
    return tag.name, tag.description, tag_id, False, False


@app.callback(
    Output('add-tag', 'n_clicks'),
    Output('tag-update-signal', 'data', allow_duplicate=True),
    Input('add-tag', 'n_clicks'),
    State('tag-name', 'value'),
    State('tag-description', 'value'),
    prevent_initial_call=True
)
def add_tag(n_clicks, name, description):
    """Add a new tag to the database."""
    if not n_clicks:
        raise PreventUpdate
    if not name:
        return 0, {'status': 'empty'}
    tag = Tag(name=name, description=description)
    db.session.add(tag)
    db.session.commit()
    return 0, {'status': 'added', 'id': tag.id}


@app.callback(
    Output('save-tag', 'n_clicks'),
    Output('tag-update-signal', 'data', allow_duplicate=True),
    Input('save-tag', 'n_clicks'),
    State('tag-name', 'value'),
    State('tag-description', 'value'),
    State('selected-tag-id', 'data'),
    prevent_initial_call=True
)
def save_tag(n_clicks, name, description, tag_id):
    """Save changes to the selected tag."""
    if not n_clicks:
        raise PreventUpdate
    tag = db.session.query(Tag).get(tag_id)
    tag.name = name
    tag.description = description
    db.session.commit()
    return 0, {'status': 'updated'}


@app.callback(
    Output('delete-tag', 'n_clicks'),
    Output('tag-update-signal', 'data', allow_duplicate=True),
    Input('delete-tag', 'n_clicks'),
    State('selected-tag-id', 'data'),
    prevent_initial_call=True
)
def delete_tag(n_clicks, tag_id):
    """Delete the selected tag from the database."""
    if not n_clicks:
        raise PreventUpdate
    tag = db.session.query(Tag).get(tag_id)
    db.session.delete(tag)
    db.session.commit()
    return 0, {'status': 'deleted'}


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