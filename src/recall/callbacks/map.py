import logging
import hashlib
import json

from dash import (
    callback,
    clientside_callback,
    ClientsideFunction,
    Output,
    Input,
    State,
    ALL,
    ctx,
    no_update,
)
import dash_leaflet as dl

from recall.aios import PlaybackSliderAIO
from recall.layout import BASEMAP
from recall.terracotta.client import get_singleband_url
from recall.visuals import cmap2hex
from recall.selection import selected_scan, frame_details
from recall.terracotta.ingest import get_driver


DEFAULT_COORDS = (64.0, 26.5)
RADAR_LAYER_OPACITY = 0.8
logger = logging.getLogger(__name__)


def availability_error(error):
    logger.error(
        "Cannot check imagery availability",
        exc_info=(type(error), error, error.__traceback__),
    )
    return {
        "error": "Imagery availability could not be checked. Check the tile database/service."
    }


@callback(
    Output("scan-availability", "data"),
    Input("selected-event", "data"),
    Input("ingestion-result", "data"),
    on_error=availability_error,
)
def load_availability(selection, _):
    if not selection or not selection.get("timestamps"):
        return None
    times = [
        value.replace("-", "").replace(":", "").replace("T", "")[:12]
        for value in selection["timestamps"]
    ]
    datasets = get_driver().get_datasets(
        {
            "timestamp": times,
            "radar": selection["radar"],
            "product": "DBZH",
        }
    )
    return {"event_id": selection["id"], "available": [keys[0] for keys in datasets]}


@callback(
    Output("map", "children"),
    Output("radar-layer-state", "data"),
    Output("radar-frame-manifest", "data"),
    Input("selected-event", "data"),
    Input("ingestion-result", "data"),
    Input("map", "center"),
    Input("map", "zoom"),
    Input("map-user-interaction", "data"),
    State("radar-layer-state", "data"),
    State(PlaybackSliderAIO.ids.slider("playback"), "value"),
)
def prepare_radar_layers(
    selection, ingestion_result, center, zoom, interaction, current, slider_val
):
    # trackViewport reports center/zoom on moveend, not each animation step.
    # A cancelled previous flight can also emit moveend at the old location.
    ready = ctx.triggered_id == "map-user-interaction" or at_event_view(
        selection, center, zoom
    )
    return update_radar_layers(
        selection, ingestion_result, current, slider_val, viewport_ready=ready
    )


def at_event_view(selection, center, zoom):
    if not selection or not selection.get("coordinates"):
        return True
    if isinstance(center, dict):
        center = [center.get("lat"), center.get("lng")]
    return (
        isinstance(center, (list, tuple))
        and len(center) == 2
        and all(
            isinstance(value, (int, float)) and abs(value - target) < 1e-6
            for value, target in zip(center, selection["coordinates"])
        )
        and zoom == 8
    )


def update_radar_layers(
    selection, ingestion_result=None, current=None, slider_val=0, *, viewport_ready=True
):
    """Keep every timestep mounted; playback only changes client-side opacity."""
    cmap = "gist_ncar"
    state = None
    if selection and selection.get("timestamps"):
        cached = current.get("pending", current) if current else {}
        previous_revision = (
            cached.get("revision", "initial")
            if cached.get("event_id") == selection["id"]
            and cached.get("radar") == selection["radar"]
            else "initial"
        )
        state = {
            "event_id": selection["id"],
            "radar": selection["radar"],
            "timestamps": selection["timestamps"],
            "revision": (ingestion_result or {})
            .get("event_revisions", {})
            .get(str(selection["id"]), previous_revision),
        }
    if state == current:
        return no_update, no_update, no_update
    layers = list(BASEMAP)
    if state is None:
        return layers, None, None
    new_location = (
        not current
        or "pending" in current
        or current.get("event_id") != state["event_id"]
        or current.get("radar") != state["radar"]
    )
    if new_location and not viewport_ready:
        pending = {"pending": state}
        if current == pending:
            return no_update, no_update, no_update
        return layers, pending, None
    series = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:20]
    active = selected_scan(selection, slider_val)
    frames = []
    for index in range(len(selection["timestamps"])):
        scan = selected_scan(selection, index)
        frames.append(frame_details(scan))
        layers.append(
            dl.TileLayer(
                id={"type": "radar-scan", "series": series, "index": index},
                url=get_singleband_url(
                    scan.timestamp,
                    scan.radar,
                    "DBZH",
                    colormap=cmap + "_cut",
                    stretch_range="[0,255]",
                ),
                opacity=RADAR_LAYER_OPACITY if index == active.index else 0,
                updateWhenIdle=True,
                updateWhenZooming=False,
            )
        )
    layers.append(
        dl.Colorbar(
            id="cbar",
            colorscale=cmap2hex(cmap),
            nTicks=5,
            width=20,
            height=250,
            min=-32,
            max=96,
            position="topright",
        )
    )
    return layers, state, {**state, "series": series, "frames": frames}


clientside_callback(
    ClientsideFunction(namespace="recall", function_name="renderFrame"),
    Output({"type": "radar-scan", "series": ALL, "index": ALL}, "opacity"),
    Output("map-timestamp", "children"),
    Output("download-h5-link", "children"),
    Output("download-h5-link", "href"),
    Output("scan-feedback", "children"),
    Output("scan-feedback", "is_open"),
    Input(PlaybackSliderAIO.ids.slider("playback"), "value"),
    Input({"type": "radar-scan", "series": ALL, "index": ALL}, "id"),
    Input("radar-frame-manifest", "data"),
    Input("selected-event", "data"),
    Input("scan-availability", "data"),
)


@callback(
    Output("map", "viewport"),
    Input("selected-event", "data"),
)
def update_viewport(selection):
    """Update the map viewport based on the selected event."""
    if selection and selection.get("coordinates"):
        return dict(center=selection["coordinates"], zoom=8, transition="flyTo")
    return dict(center=DEFAULT_COORDS, zoom=6, transition="flyTo")
