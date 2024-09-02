from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from recall.aios import PlaybackSliderAIO
try:
    from recall.secrets import FMI_COMMERCIAL_API_KEY
    use_commercial_api = True
except ImportError:
    use_commercial_api = False


if use_commercial_api:
    WMS_MAP = f'https://wms.fmi.fi/fmi-apikey/{FMI_COMMERCIAL_API_KEY}/geoserver/wms'
    BASEMAP = (
        dl.WMSTileLayer(url=WMS_MAP, layers='KAP:BasicMap version 7', format='image/png'),
        dl.WMSTileLayer(url=WMS_MAP, layers='KAP:radars_finland', format='image/png', transparent=True)
    )
else:
    BASEMAP = (
        dl.TileLayer(),
    )
BUTTONS_GRID_CLASS = 'd-grid gap-1 d-md-flex justify-content-md-end'


def create_layout():
    # event form using dbc.Form, WITHOUT using dbc.FormGroup
    time_span_input = html.Div([
        dbc.Row([
            dbc.Label('From', width='auto'),
            dbc.Col([
                dbc.Input(id='start-time', type='datetime-local', placeholder='Start Time'),
            ]),
            dbc.Label('to', width='auto'),
            dbc.Col([
                dbc.Input(id='end-time', type='datetime-local', placeholder='End Time'),
            ])
        ]),
    ], className='mb-3')
    description_input = html.Div([
        dbc.Input(id='event-description', type='text', placeholder='Event description')
    ], className='mb-3')
    radar_picker = dbc.Row([
        dbc.Label('Radar', width='auto'),
        dbc.Col(dcc.Dropdown(id='radar-picker', placeholder='Select radar...')),
    ], className='mb-3')
    tag_picker = html.Div([
        html.P('Tags'),
        dcc.Dropdown(id='tag-picker', multi=True, placeholder='Select tags...'),
    ], className='mb-3')
    add_event_button = dbc.Button('Save as new', color='primary', id='add-event')
    save_event_button = dbc.Button('Save changes', color='primary', id='save-event')
    delete_event_button = dbc.Button('Delete', color='danger', id='delete-event')
    event_buttons = html.Div([
        add_event_button,
        save_event_button,
        delete_event_button,
    ], className=BUTTONS_GRID_CLASS)
    event_form_card = dbc.Card(
        dbc.CardBody([
            html.H4('Event details', className='card-title'),
            dbc.Form([
                time_span_input,
                description_input,
                radar_picker,
                tag_picker,
                event_buttons,
            ]),
            dbc.Progress(id='event-form-progress', class_name='d-none'),
        ]),
        class_name='mt-3'
    )
    event_controls_tab_content = html.Div([
        dbc.Card(
            dbc.CardBody([
                dcc.Dropdown(id='event-dropdown', placeholder='Select event...', className='mb-3'),
                html.Div([
                    PlaybackSliderAIO(
                        aio_id='playback',
                        slider_props={'min': 0, 'max': 1, 'step': 1, 'value': 0, 'updatemode': 'drag'},
                        button_props={'className': 'float-left'}
                    )
                ], id='playback-container', hidden=True),
            ]),
            class_name='mt-3'
        ),
        event_form_card,
    ])
    add_tag_button = dbc.Button('Add new', color='primary', id='add-tag')
    save_tag_button = dbc.Button('Save changes', color='primary', id='save-tag', disabled=True)
    delete_tag_button = dbc.Button('Delete', color='danger', id='delete-tag', disabled=True)
    tag_buttons = html.Div([
        add_tag_button,
        save_tag_button,
        delete_tag_button,
    ], className=BUTTONS_GRID_CLASS)
    tag_tab_content = html.Div([
        dcc.Store(id='selected-tag-id', data=-1),
        dcc.Store(id='tag-update-signal', data={}),  # signal for updating the tag collection
        dbc.Card([
            dbc.CardHeader(
                html.Div([], id='tag-collection', className='d-flex flex-wrap')
            ),
            dbc.CardBody([
                dbc.Input(id='tag-name', type='text', placeholder='Tag name', class_name='mb-3'),
                dbc.Input(id='tag-description', type='text', placeholder='Tag description', class_name='mb-3'),
                tag_buttons,
            ]),
        ], class_name='mt-3'),
    ])
    maintenance_tab_content = dbc.Card(
        dbc.CardBody([
            html.P('Ingest all events to the terracotta database.'),
            dbc.Button('Ingest all', id='ingest-all', color='primary'),
        ]),
        class_name='mt-3'
    )
    tabs = dbc.Tabs([
        dbc.Tab(event_controls_tab_content, label='Events'),
        dbc.Tab(tag_tab_content, label='Tags'),
        dbc.Tab(maintenance_tab_content, label='Maintenance'),
    ])
    return dbc.Container([
        dcc.Interval(id='startup-interval', interval=1, n_intervals=0, max_intervals=1),
        dcc.Store(id='events-update-signal'),  # signal for updating the event dropdown
        dbc.Row([
            dbc.Col([
                tabs
            ], lg=4),
            dbc.Col([
                dl.Map(children=BASEMAP,
                    id='map', center=(61.9241, 25.7482), zoom=6,
                    style={'width': '100%', 'height': '100vh'})
            ])
        ])
    ], fluid=True)


