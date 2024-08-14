from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from prevent.aios import PlaybackSliderAIO
from prevent.secrets import FMI_COMMERCIAL_API_KEY 


WMS_MAP = f'https://wms.fmi.fi/fmi-apikey/{FMI_COMMERCIAL_API_KEY}/geoserver/wms'
BASEMAP = (
    dl.WMSTileLayer(url=WMS_MAP, layers='KAP:BasicMap version 7', format='image/png'),
    dl.WMSTileLayer(url=WMS_MAP, layers='KAP:radars_finland', format='image/png', transparent=True)
)


def create_layout():
    # event form using dbc.Form, WITHOUT using dbc.FormGroup
    time_span_input = html.Div([
        dbc.Row([
            dbc.Label('Event time span', width='auto'),
            dbc.Col([
                dcc.DatePickerRange(
                    id='date-span',
                    start_date_placeholder_text='Start Date',
                    end_date_placeholder_text='End Date',
                    display_format='YYYY-MM-DD',
                    minimum_nights=0,
                ),
            ]),
        ]),
        dbc.Row([
            dbc.Label('From', width='auto'),
            dbc.Col([
                dbc.Input(id='start-time', type='time', placeholder='Start Time'),
            ]),
            dbc.Label('to', width='auto'),
            dbc.Col([
                dbc.Input(id='end-time', type='time', placeholder='End Time'),
            ])
        ]),
    ], className='mb-3')
    description_input = html.Div([
        dbc.Input(id='event-description', type='text', placeholder='Event description')
    ], className='mb-3')
    radar_picker = dbc.Row([
        dbc.Label('Radar', width='auto'),
        dbc.Col(dbc.Select(id='radar-picker')),
    ], className='mb-3')
    tag_picker = html.Div([
        html.P('Tags'),
        dcc.Dropdown(id='tag-picker', multi=True),
    ], className='mb-3')
    add_event_button = dbc.Button('Add new', color='primary', id='add-event')
    save_event_button = dbc.Button('Save changes', color='primary', id='save-event')
    delete_event_button = dbc.Button('Delete', color='danger', id='delete-event')
    buttons = dbc.Row([
        dbc.Col(add_event_button),
        dbc.Col(save_event_button),
        dbc.Col(delete_event_button),
    ])
    event_form_card = dbc.Card(
        dbc.CardBody([
            dbc.Form([
                time_span_input,
                description_input,
                radar_picker,
                tag_picker,
                buttons,
            ]),
        ])
    )
    event_controls_tab_content = html.Div([
        dbc.Card(
            dbc.CardBody([
                dcc.Dropdown(id='event-dropdown'),
                PlaybackSliderAIO(
                    aio_id='playback',
                    slider_props={'min': 0, 'max': 1, 'step': 1, 'value': 0},
                    button_props={'className': 'float-left'}
                )
            ])
        ),
        event_form_card,
    ])
    maintenance_tab_content = dbc.Card(
        dbc.CardBody([
            html.P('Ingest all events to the terracotta database.'),
            dbc.Button('Ingest all', id='ingest-all', color='primary'),
        ])
    )
    tabs = dbc.Tabs([
        dbc.Tab(event_controls_tab_content, label='Event'),
        dbc.Tab(maintenance_tab_content, label='Maintenance'),
    ])
    return dbc.Container([
        dcc.Interval(id='startup-interval', interval=1, n_intervals=0, max_intervals=1),
        dcc.Store(id='events-update-signal'), # signal for updating the event dropdown
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


