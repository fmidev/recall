import dash
from dash import dcc, html
from dash.dependencies import Input, Output
from dash.long_callback import CeleryLongCallbackManager
import dash_leaflet as dl
from celery import Celery

from prevent.models import Event, db
from prevent.db import get_coords


celery_app = Celery('prevent', broker='redis://localhost:6379/0')
callman = CeleryLongCallbackManager(celery_app)

app = dash.Dash(__name__, long_callback_manager=callman)
server = app.server  # Expose Flask server for deployments


def create_event_dropdown():
    events = db.session.query(Event).all()
    return dcc.Dropdown(
        id='event-dropdown',
        options=[{'label': event.description, 'value': event.id} for event in events],
        value=None
    )


app.layout = html.Div([
    html.Div([
        create_event_dropdown(),
        html.Div(id='selected-event')
    ], style={'width': '30%', 'display': 'inline-block'}),
    html.Div([
        dl.Map([dl.TileLayer(), dl.Marker(position=(61.9241, 25.7482), id="marker")],
               id='map',
               style={'width': '100%', 'height': '80vh'})
    ], style={'width': '70%', 'display': 'inline-block'})
])


@app.callback(
    [Output('map', 'center'), Output('map', 'zoom'), Output('selected-event', 'children')],
    [Input('event-dropdown', 'value')]
)
def update_map(event_id):
    if event_id:
        event = db.session.query(Event).get(event_id)
        lat, lon = get_coords(event.radar)  # Assuming get_coords is defined elsewhere
        return (lat, lon), 9, f"Selected Event: {event.description}"
    else:
        return (61.9241, 25.7482), 6, "Select an event"


def main(**kws):
    # Run the Dash app server
    app.run_server(debug=True, host='0.0.0.0', port=8050, **kws)


if __name__ == '__main__':
    main(debug=True)