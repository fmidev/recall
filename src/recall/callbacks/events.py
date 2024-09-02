"""Callbacks for the events tab."""

from dash import Input, Output, callback


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
def disable_add_event_button(start_time, end_time, radar_id):
    """Disable the add-event button if required fields are empty."""
    return not all([start_time, end_time, radar_id])