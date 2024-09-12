"""Dash app for visualizing radar case studies."""

import os
import datetime

from dash import Dash, Input, Output, State, CeleryManager, callback
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from celery import Celery
from flask_migrate import Migrate

from recall.database.models import Event, Tag, Radar
from recall.database.queries import initial_db_setup, add_event, event_overlaps_existing
from recall.database.connection import db
from recall.layout import create_layout
from recall.terracotta.ingest import insert_event
import recall.callbacks.events  # noqa: F401
import recall.callbacks.tags  # noqa: F401
import recall.callbacks.map  # noqa: F401
import recall.callbacks.maintenance  # noqa: F401


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
        (Output('event-form-progress', 'class_name'), 'my-3', 'd-none'),
    ],
    progress=[
        Output('event-form-progress', 'value'),
        Output('event-form-progress', 'max'),
        Output('event-form-progress', 'label'),
    ],
    prevent_initial_call=True
)
def submit_event(set_progress, n_clicks, start_time, end_time, description, radar_id: int, tag_ids):
    """Submit an event to the database."""
    if not n_clicks:
        raise PreventUpdate
    with server.app_context():
        radar = db.session.query(Radar).get(radar_id)
        tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        start_time = datetime.datetime.fromisoformat(start_time)
        end_time = datetime.datetime.fromisoformat(end_time)
        print(f"Adding event: {start_time} - {end_time} {description} {radar.name}")
        try:
            add_event(db, radar, start_time, end_time, description, tags, set_progress=set_progress)
        except ValueError:
            return 0, {'status': 'overlap'}
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
def update_event(set_progress, n_clicks, event_id: int, start_time, end_time, description: str, radar_id: int, tag_ids):
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
        if event_overlaps_existing(db, event):
            db.session.rollback()
            return 0, {'status': 'overlap'}
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


def main(**kws):
    """For development purposes only."""
    app.run(debug=True, host='0.0.0.0', port='8050', **kws)


if __name__ == '__main__':
    main()