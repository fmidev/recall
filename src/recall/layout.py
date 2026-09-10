import os

from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_leaflet as dl

from recall.aios import PlaybackSliderAIO

FMI_COMMERCIAL_API_KEY = os.environ.get("FMI_COMMERCIAL_API_KEY")
if not FMI_COMMERCIAL_API_KEY:
    try:
        from recall.secrets import FMI_COMMERCIAL_API_KEY
    except ModuleNotFoundError as exc:
        if exc.name != "recall.secrets":
            raise


if FMI_COMMERCIAL_API_KEY:
    WMS_MAP = f"https://wms.fmi.fi/fmi-apikey/{FMI_COMMERCIAL_API_KEY}/geoserver/wms"
    BASEMAP = (
        dl.WMSTileLayer(
            url=WMS_MAP, layers="KAP:BasicMap version 7", format="image/png"
        ),
        dl.WMSTileLayer(
            url=WMS_MAP,
            layers="KAP:radars_finland",
            format="image/png",
            transparent=True,
        ),
    )
else:
    BASEMAP = (
        dl.TileLayer(
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        ),
    )
BUTTONS_GRID_CLASS = "d-grid gap-1 d-md-flex justify-content-md-end"


def create_layout():
    # event form using dbc.Form, WITHOUT using dbc.FormGroup
    time_span_input = html.Div(
        [
            dbc.Row(
                [
                    dbc.Label("From", width="auto", html_for="start-time"),
                    dbc.Col(
                        [
                            dbc.Input(
                                id="start-time",
                                type="datetime-local",
                                placeholder="Start Time",
                            ),
                        ]
                    ),
                    dbc.Label("to", width="auto", html_for="end-time"),
                    dbc.Col(
                        [
                            dbc.Input(
                                id="end-time",
                                type="datetime-local",
                                placeholder="End Time",
                            ),
                        ]
                    ),
                    dbc.Col([dbc.Label("UTC", width="auto")]),
                ]
            ),
        ],
        className="mb-3",
    )
    description_input = html.Div(
        [
            dbc.Input(
                id="event-description", type="text", placeholder="Event description"
            )
        ],
        className="mb-3",
    )
    radar_picker = dbc.Row(
        [
            dbc.Label("Radar", width="auto", html_for="radar-picker"),
            dbc.Col(dcc.Dropdown(id="radar-picker", placeholder="Select radar...")),
        ],
        className="mb-3",
    )
    tag_picker = dbc.Row(
        [
            dbc.Col(
                [
                    dbc.Label("Tags", html_for="tag-picker"),
                    dcc.Dropdown(
                        id="tag-picker", multi=True, placeholder="Select tags..."
                    ),
                ]
            ),
        ],
        className="mb-3",
    )
    add_event_button = dbc.Button("Save as new", color="primary", id="add-event")
    save_event_button = dbc.Button("Save changes", color="primary", id="save-event")
    delete_event_button = dbc.Button("Delete", color="danger", id="delete-event")
    event_buttons = html.Fieldset(
        [
            add_event_button,
            save_event_button,
            dcc.ConfirmDialogProvider(
                delete_event_button,
                id="confirm-delete-event",
                message="Delete this saved event and its tag associations? This cannot be undone.",
            ),
        ],
        id="event-save-buttons",
        className=BUTTONS_GRID_CLASS,
    )
    event_form_card = dbc.Card(
        dbc.CardBody(
            [
                html.H4("Event details", className="card-title"),
                dbc.Form(
                    [
                        time_span_input,
                        description_input,
                        radar_picker,
                        tag_picker,
                        event_buttons,
                    ]
                ),
                dbc.Alert(id="event-feedback", is_open=False, class_name="mt-3"),
                dbc.Button("Prepare imagery", id="prepare-imagery", class_name="mt-2"),
                dbc.Progress(id="ingestion-progress", class_name="d-none"),
                dbc.Alert(id="ingestion-feedback", is_open=False, class_name="mt-3"),
            ]
        ),
        class_name="mt-3",
    )
    event_controls_tab_content = html.Div(
        [
            dbc.Card(
                dbc.CardBody(
                    [
                        dbc.Label("Filter events by tags", html_for="tag-filter"),
                        dcc.Dropdown(
                            id="tag-filter",
                            multi=True,
                            value=[],
                            placeholder="All events (no tag filter)",
                            className="mb-2",
                        ),
                        dbc.RadioItems(
                            id="tag-match",
                            value="all",
                            inline=True,
                            options=[
                                {"label": "All selected tags", "value": "all"},
                                {"label": "Any selected tag", "value": "any"},
                            ],
                            class_name="mb-2",
                        ),
                        html.Div(
                            id="filter-feedback",
                            className="small text-muted mb-2",
                            role="status",
                        ),
                        dcc.Dropdown(
                            id="event-dropdown",
                            placeholder="Select event...",
                            className="mb-3",
                        ),
                        html.Div(
                            [
                                PlaybackSliderAIO(
                                    aio_id="playback",
                                    slider_props={
                                        "min": 0,
                                        "max": 1,
                                        "step": 1,
                                        "value": 0,
                                        "updatemode": "drag",
                                    },
                                    button_props={"className": "float-left"},
                                )
                            ],
                            id="playback-container",
                            hidden=True,
                        ),
                    ]
                ),
                class_name="mt-3",
            ),
            event_form_card,
            dbc.Card(
                dbc.CardBody(
                    [
                        html.H4("Download", className="card-title"),
                        html.A("", id="download-h5-link", href="#", target="_blank"),
                    ]
                ),
                class_name="mt-3",
            ),
        ]
    )
    add_tag_button = dbc.Button("Add new", color="primary", id="add-tag")
    save_tag_button = dbc.Button(
        "Save changes", color="primary", id="save-tag", disabled=True
    )
    delete_tag_button = dbc.Button(
        "Delete", color="danger", id="delete-tag", disabled=True
    )
    tag_buttons = html.Div(
        [
            add_tag_button,
            save_tag_button,
            dcc.ConfirmDialogProvider(
                delete_tag_button,
                id="confirm-delete-tag",
                message="Delete this tag from the catalog and all events? This cannot be undone.",
            ),
        ],
        className=BUTTONS_GRID_CLASS,
    )
    tag_tab_content = html.Div(
        [
            dcc.Store(id="selected-tag-id", data=-1),
            dcc.Store(
                id="tag-update-signal", data={}
            ),  # signal for updating the tag collection
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.Div([], id="tag-collection", className="d-flex flex-wrap")
                    ),
                    dbc.CardBody(
                        [
                            dbc.Input(
                                id="tag-name",
                                type="text",
                                placeholder="Tag name",
                                class_name="mb-3",
                            ),
                            dbc.Input(
                                id="tag-description",
                                type="text",
                                placeholder="Tag description",
                                class_name="mb-3",
                            ),
                            tag_buttons,
                            dbc.Alert(
                                id="tag-feedback", is_open=False, class_name="mt-3"
                            ),
                        ]
                    ),
                ],
                class_name="mt-3",
            ),
        ]
    )
    maintenance_tab_content = html.Div(
        [
            dbc.Card(
                dbc.CardBody(
                    [
                        html.P("Ingest all events to the terracotta database."),
                        dbc.Button("Ingest all", id="ingest-all", color="primary"),
                    ]
                ),
                class_name="mt-3",
            ),
            dbc.Card(
                dbc.CardBody(
                    [
                        html.P("Export all events."),
                        dbc.Button(
                            "Export as toml", id="btn-export-toml", color="primary"
                        ),
                        dcc.Download(id="download-toml"),
                    ]
                ),
                class_name="mt-3",
            ),
        ]
    )
    tabs = dbc.Tabs(
        [
            dbc.Tab(event_controls_tab_content, label="Events", tab_id="events"),
            dbc.Tab(tag_tab_content, label="Tags", tab_id="tags"),
            dbc.Tab(maintenance_tab_content, label="Maintenance", tab_id="maintenance"),
        ],
        active_tab="events",
    )
    return dbc.Container(
        [
            dcc.Interval(
                id="startup-interval", interval=1, n_intervals=0, max_intervals=1
            ),
            dcc.Store(
                id="events-update-signal"
            ),  # signal for updating the event dropdown
            dcc.Store(id="ingestion-request"),
            dcc.Store(id="ingestion-result"),
            dcc.Store(id="selected-event"),
            dcc.Store(id="scan-availability"),
            dcc.Store(id="ingestion-jobs", data=[]),
            dcc.Interval(id="ingestion-poll", interval=1000, disabled=True),
            dbc.Row(
                [
                    dbc.Col([tabs], lg=4),
                    dbc.Col(
                        [
                            dbc.Alert(
                                id="scan-feedback", color="warning", is_open=False
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        id="map-timestamp",
                                        className="leaflet-bottom leaflet-left leaflet-control bg-light text-dark p-2 rounded",
                                    ),
                                    html.Div(
                                        [
                                            dl.Map(
                                                children=BASEMAP,
                                                id="map",
                                                center=(61.9241, 25.7482),
                                                zoom=6,
                                                style={
                                                    "width": "100%",
                                                    "height": "100vh",
                                                },
                                            )
                                        ]
                                    ),
                                ],
                                className="position-relative",
                            ),
                        ]
                    ),
                ]
            ),
        ],
        fluid=True,
    )
