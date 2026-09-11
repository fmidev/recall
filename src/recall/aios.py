from dash import (
    html,
    dcc,
    Output,
    Input,
    State,
    clientside_callback,
    ClientsideFunction,
    MATCH,
)
import dash_bootstrap_components as dbc
import uuid


class PlaybackSliderAIO(html.Div):
    class ids:
        play = lambda aio_id: {
            "component": "PlaybackSliderAIO",
            "subcomponent": "button",
            "aio_id": aio_id,
        }
        play_icon = lambda aio_id: {
            "component": "PlaybackSliderAIO",
            "subcomponent": "i",
            "aio_id": aio_id,
        }
        slider = lambda aio_id: {
            "component": "PlaybackSliderAIO",
            "subcomponent": "slider",
            "aio_id": aio_id,
        }
        interval = lambda aio_id: {
            "component": "PlaybackSliderAIO",
            "subcomponent": "interval",
            "aio_id": aio_id,
        }

    ids = ids

    def __init__(
        self, button_props=None, slider_props=None, interval_props=None, aio_id=None
    ):
        if aio_id is None:
            aio_id = str(uuid.uuid4())

        button_props = button_props.copy() if button_props else {}
        slider_props = slider_props.copy() if slider_props else {}
        interval_props = interval_props.copy() if interval_props else {}

        button_props["active"] = False

        super().__init__(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            dbc.Button(
                                html.I(id=self.ids.play_icon(aio_id)),
                                id=self.ids.play(aio_id),
                                **button_props,
                            ),
                            width="auto",
                        ),
                        dbc.Col(
                            dcc.Slider(
                                id=self.ids.slider(aio_id),
                                className="md-3",
                                **slider_props,
                            )
                        ),
                    ]
                ),
                dcc.Interval(id=self.ids.interval(aio_id), **interval_props),
            ]
        )

    clientside_callback(
        ClientsideFunction(namespace="recall", function_name="togglePlayback"),
        Output(ids.play(MATCH), "active"),
        Input(ids.play(MATCH), "n_clicks"),
        State(ids.play(MATCH), "active"),
        prevent_initial_call=True,
    )

    clientside_callback(
        ClientsideFunction(namespace="recall", function_name="playbackControls"),
        Output(ids.play_icon(MATCH), "className"),
        Output(ids.interval(MATCH), "disabled"),
        Input(ids.play(MATCH), "active"),
    )

    clientside_callback(
        ClientsideFunction(namespace="recall", function_name="advancePlayback"),
        Output(ids.slider(MATCH), "value"),
        Input(ids.play(MATCH), "active"),
        Input(ids.interval(MATCH), "n_intervals"),
        State(ids.slider(MATCH), "min"),
        State(ids.slider(MATCH), "max"),
        State(ids.slider(MATCH), "step"),
        State(ids.slider(MATCH), "value"),
    )
