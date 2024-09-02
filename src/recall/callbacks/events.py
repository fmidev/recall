"""Callbacks for the events tab."""

from dash import Input, Output, callback


@callback(
    Output('end-time', 'min'),
    Input('start-time', 'value'),
)
def update_end_time_min(start_time):
    """Update the minimum value of the end time input."""
    return start_time
