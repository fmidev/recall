"""Callbacks for the events tab."""

import logging
from uuid import uuid4

from dash import Input, Output, State, callback, ctx, no_update
from dash.exceptions import PreventUpdate

from recall.aios import PlaybackSliderAIO
from recall.database.connection import db
from recall.database.models import Event, Radar, Tag
from recall.utils import timestamp_marks
from recall.database.queries import browse_events, save_event
from recall.domain import EventValidationError
from recall.database.queries import get_coords
from recall.selection import event_snapshot


logger = logging.getLogger(__name__)


def save_error(error):
    logger.error(
        "Event save failed", exc_info=(type(error), error, error.__traceback__)
    )
    return {
        "status": "invalid",
        "message": "The save could not be confirmed. Refresh the catalog before retrying.",
        "revision": str(uuid4()),
    }, no_update


@callback(
    Output("startup-interval", "disabled"),
    Input("startup-interval", "n_intervals"),
)
def finish_startup(_):
    return True


@callback(
    Output("events-update-signal", "data", allow_duplicate=True),
    Output("ingestion-request", "data"),
    Input("add-event", "n_clicks"),
    Input("save-event", "n_clicks"),
    State("event-dropdown", "value"),
    State("start-time", "value"),
    State("end-time", "value"),
    State("event-description", "value"),
    State("radar-picker", "value"),
    State("tag-picker", "value"),
    running=[
        (Output("event-save-buttons", "disabled"), True, False),
    ],
    on_error=save_error,
    prevent_initial_call=True,
)
def submit_event(
    add_clicks, save_clicks, event_id, start, end, description, radar_id, tags
):
    updating = ctx.triggered_id == "save-event"
    if updating and event_id is None:
        return {"status": "invalid", "message": "Select an event to update."}, no_update
    try:
        event, imagery_changed = save_event(
            radar_id,
            start,
            end,
            description,
            tags,
            event_id=event_id if updating else None,
        )
    except EventValidationError as exc:
        return {
            "status": "invalid",
            "message": str(exc),
            "revision": str(uuid4()),
        }, no_update
    revision = str(uuid4())
    signal = {
        "status": "updated" if updating else "added",
        "id": event.id,
        "revision": revision,
    }
    request = (
        {"event_id": event.id, "revision": revision} if imagery_changed else no_update
    )
    return signal, request


@callback(
    Output("event-feedback", "children"),
    Output("event-feedback", "color"),
    Output("event-feedback", "is_open"),
    Input("events-update-signal", "data"),
    Input("selected-event", "data"),
)
def event_feedback(signal, selection=None):
    if selection and selection.get("error"):
        return selection["error"], "danger", True
    if not signal:
        return "", "info", False
    if signal.get("status") == "invalid":
        return signal["message"], "danger", True
    messages = {
        "added": "Event saved. Imagery preparation runs separately; retry below if needed.",
        "updated": "Event updated. Imagery preparation runs separately when required.",
        "deleted": "Event deleted.",
    }
    message = messages.get(signal.get("status"), "")
    return message, "success", bool(message)


@callback(
    Output("end-time", "min"),
    Input("start-time", "value"),
)
def update_end_time_min(start_time):
    """Update the minimum value of the end time input."""
    return start_time


@callback(
    Output("add-event", "disabled"),
    Input("start-time", "value"),
    Input("end-time", "value"),
    Input("radar-picker", "value"),
)
def disable_add_event_button(start_time, end_time, radar_id: int):
    """Disable the add-event button if required fields are empty."""
    return not all([start_time, end_time, radar_id])


@callback(
    Output("event-dropdown", "options"),
    Output("event-dropdown", "value"),
    Output("filter-feedback", "children"),
    Input("events-update-signal", "data"),
    Input("startup-interval", "disabled"),
    Input("tag-update-signal", "data"),
    Input("tag-filter", "value"),
    Input("tag-match", "value"),
    State("event-dropdown", "value"),
)
def populate_event_dropdown(signal, _, __, tag_ids, match, selected_id):
    """Populate the event dropdown with events from the database."""
    if ctx.triggered_id == "events-update-signal" and signal:
        if signal.get("status") == "invalid":
            return no_update, no_update, no_update
    events = browse_events(tag_ids, match)
    # Label is the event start date and radar name
    options = []
    for event in events:
        tags = ", ".join([tag.name for tag in event.tags])
        label = f"{event.start_time.strftime('%Y-%m-%d %H:%M')} UTC {event.radar.name}"
        if tags:
            label += f": {tags}"
        options.append({"label": label, "value": event.id})
    ids = {event.id for event in events}
    if ctx.triggered_id == "events-update-signal" and signal:
        if signal.get("status") == "added":
            selected_id = signal["id"]
    message = f"{len(events)} matching events."
    if not events:
        message = (
            "No events match these tags. Clear the filter to see the full catalog."
            if tag_ids
            else "No events in the catalog."
        )
    if (
        ctx.triggered_id == "events-update-signal"
        and signal
        and signal.get("status") in ("added", "updated")
        and tag_ids
    ):
        if signal.get("id") not in ids:
            message += " The saved event is outside this filter."
    return options, selected_id if selected_id in ids else None, message


@callback(
    Output("tag-filter", "options"),
    Output("tag-filter", "value"),
    Input("startup-interval", "disabled"),
    Input("tag-update-signal", "data"),
    State("tag-filter", "value"),
)
def populate_tag_filter(_, __, selected):
    tags = db.session.scalars(db.select(Tag).order_by(Tag.name)).all()
    ids = {tag.id for tag in tags}
    return (
        [{"label": tag.name, "value": tag.id} for tag in tags],
        [tag_id for tag_id in selected or [] if tag_id in ids],
    )


@callback(Output("radar-picker", "options"), Input("startup-interval", "disabled"))
def populate_radar_picker(_):
    """Populate the radar picker with radars from the database."""
    radars = db.session.scalars(db.select(Radar).order_by(Radar.name)).all()
    options = [{"label": radar.name, "value": radar.id} for radar in radars]
    return options


@callback(
    Output("tag-picker", "options"),
    Input("startup-interval", "disabled"),
    Input("tag-update-signal", "data"),
)
def populate_tag_picker(_, __):
    """Populate the tag picker with tags from the database."""
    tags = db.session.scalars(db.select(Tag).order_by(Tag.name)).all()
    options = [{"label": tag.name, "value": tag.id} for tag in tags]
    return options


@callback(
    Output("selected-event", "data"),
    Input("event-dropdown", "value"),
    Input("events-update-signal", "data"),
    Input("tag-update-signal", "data"),
)
def load_selected_event(event_id, signal, _):
    if ctx.triggered_id == "events-update-signal" and signal:
        if signal.get("status") == "invalid":
            raise PreventUpdate
    if event_id is None:
        return None
    event = db.session.get(Event, event_id)
    if event is None:
        logger.warning("Selected event %s no longer exists", event_id)
        return {"error": "This event no longer exists. Select another event."}
    return event_snapshot(event, get_coords(db, event.radar))


@callback(
    Output("start-time", "value"),
    Output("end-time", "value"),
    Output("event-description", "value"),
    Output("radar-picker", "value"),
    Output("tag-picker", "value"),
    Output("delete-event", "disabled"),
    Output("save-event", "disabled"),
    Output("playback-container", "hidden"),
    Input("selected-event", "data"),
)
def update_selected_event(selection):
    """Update the selected event text based on the selected event."""
    if selection and selection.get("id"):
        return (
            selection["start_time"],
            selection["end_time"],
            selection["description"],
            selection["radar_id"],
            selection["tag_ids"],
            False,
            False,
            not bool(selection["timestamps"]),
        )
    return "", "", "", None, [], True, True, True


@callback(
    Output("delete-event", "n_clicks"),
    Output("events-update-signal", "data", allow_duplicate=True),
    Input("confirm-delete-event", "submit_n_clicks"),
    State("event-dropdown", "value"),
    prevent_initial_call=True,
)
def delete_event(n_clicks, event_id: int):
    """Delete the selected event from the database."""
    if not n_clicks:
        raise PreventUpdate
    event = db.session.get(Event, event_id) if event_id is not None else None
    if event is None:
        return 0, {"status": "invalid", "message": "This event no longer exists."}
    db.session.delete(event)
    db.session.commit()
    return 0, {"status": "deleted", "id": event_id, "revision": str(uuid4())}


@callback(
    Output(PlaybackSliderAIO.ids.slider("playback"), "marks"),
    Output(PlaybackSliderAIO.ids.slider("playback"), "max"),
    Output(PlaybackSliderAIO.ids.slider("playback"), "value", allow_duplicate=True),
    Output(PlaybackSliderAIO.ids.play("playback"), "active", allow_duplicate=True),
    Output(PlaybackSliderAIO.ids.slider("playback"), "disabled"),
    Input("selected-event", "data"),
    prevent_initial_call=True,
)
def update_slider_marks(selection):
    """Update the slider marks based on the selected event."""
    if not selection or not selection.get("timestamps"):
        return {}, 1, 0, False, True
    from datetime import datetime

    timestamps = [datetime.fromisoformat(value) for value in selection["timestamps"]]
    marks = timestamp_marks(timestamps)
    return marks, len(timestamps) - 1, 0, False, False
