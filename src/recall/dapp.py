"""Dash app for visualizing radar case studies."""

import os
import datetime

from dash import Dash, Input, Output, State, CeleryManager, callback
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from celery import Celery
from flask_migrate import Migrate

from recall.database import list_scan_timestamps
from recall.database.models import Event, Tag, Radar
from recall.database.queries import initial_db_setup, add_event
from recall.database.connection import db
from recall.layout import create_layout
from recall.terracotta.ingest import insert_event
from recall.aios import PlaybackSliderAIO
from recall.utils import timestamp_marks
from recall.callbacks.tags import populate_tag_collection, tag_selected, add_tag, save_tag, delete_tag
from recall.callbacks.map import update_radar_layers, update_viewport


DATABASE_URI = os.environ.get('PREVENT_DB_URI', 'postgresql://postgres:postgres@localhost/recall')
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')


def create_app():
    celery_app = Celery(__name__, broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
    callman = CeleryManager(celery_app)
    app = Dash(
        __name__,
        title='Recall',
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


@callback(
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


@callback(
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


@callback(
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


@callback(
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


@callback(
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


@callback(
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


@callback(
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


@callback(
    Output('tag-picker', 'options'),
    Input('startup-interval', 'disabled'),
    Input('tag-update-signal', 'data'),
)
def populate_tag_picker(_, __):
    """Populate the tag picker with tags from the database."""
    tags = db.session.query(Tag).order_by(Tag.name).all()
    if not tags:
        print('No tags found')
        raise PreventUpdate
    options = [{'label': tag.name, 'value': tag.id} for tag in tags]
    return options


@callback(
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


@callback(
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


def main(**kws):
    """For development purposes only."""
    app.run(debug=True, host='0.0.0.0', port='8050', **kws)


if __name__ == '__main__':
    main()