"""Callbacks for the events tab."""

from dash import Input, Output, State, callback
from dash.exceptions import PreventUpdate

from recall.aios import PlaybackSliderAIO
from recall.database import list_scan_timestamps
from recall.database.connection import db
from recall.database.models import Event, Radar, Tag
from recall.utils import timestamp_marks


@callback(
    Output('end-time', 'min'),
    Input('start-time', 'value'),
)
def update_end_time_min(start_time):
    """Update the minimum value of the end time input."""
    return start_time


@callback(
    Output('add-event', 'disabled'),
    Input('start-time', 'value'),
    Input('end-time', 'value'),
    Input('radar-picker', 'value'),
)
def disable_add_event_button(start_time, end_time, radar_id: int):
    """Disable the add-event button if required fields are empty."""
    return not all([start_time, end_time, radar_id])


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
        label = f"{event.start_time.strftime('%Y-%m-%d')} {event.radar.name}"
        if tags:
            label += f": {tags}"
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
def update_selected_event(event_id: int, _):
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
def delete_event(n_clicks, event_id: int):
    """Delete the selected event from the database."""
    if not n_clicks:
        raise PreventUpdate
    event = db.session.query(Event).get(event_id)
    db.session.delete(event)
    db.session.commit()
    return 0, None, {'status': 'deleted'}


@callback(
    Output(PlaybackSliderAIO.ids.slider('playback'), 'marks'),
    Output(PlaybackSliderAIO.ids.slider('playback'), 'max'),
    Input('event-dropdown', 'value'),
    Input('events-update-signal', 'data')
)
def update_slider_marks(event_id: int, _):
    """Update the slider marks based on the selected event."""
    if not event_id:
        return {}, 1
    event = db.session.query(Event).get(event_id)
    timestamps = list_scan_timestamps(event)
    marks = timestamp_marks(timestamps)
    return marks, len(timestamps) - 1