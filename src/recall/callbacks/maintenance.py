from dash import Input, Output, callback
import tomli_w

from recall.database.queries import events_list


@callback(
    Output('download-toml', 'data'),
    Input('btn-export-toml', 'n_clicks'),
    prevent_initial_call=True
)
def export_toml(n_clicks: int):
    """Export all events as a toml file."""
    print('Exporting events to toml')
    events = {'event': events_list()}
    return dict(content=tomli_w.dumps(events), filename='events.toml', type='application/toml')