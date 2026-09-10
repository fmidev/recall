import logging

from dash import callback, Output, Input
import dash_leaflet as dl

from recall.aios import PlaybackSliderAIO
from recall.layout import BASEMAP
from recall.terracotta.client import get_singleband_url
from recall.visuals import cmap2hex
from recall.selection import selected_scan
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
    Output("scan-feedback", "children"),
    Output("scan-feedback", "is_open"),
    Input("selected-event", "data"),
    Input(PlaybackSliderAIO.ids.slider("playback"), "value"),
    Input("scan-availability", "data"),
)
def scan_feedback(selection, slider_val, availability):
    scan = selected_scan(selection, slider_val)
    if scan is None:
        return "", False
    if availability and availability.get("error"):
        return availability["error"], True
    if not availability or availability.get("event_id") != selection["id"]:
        return "Checking imagery availability...", True
    if scan.timestamp.strftime("%Y%m%d%H%M") not in availability["available"]:
        return (
            "This scan is not prepared or is unavailable. A blank layer does not "
            "indicate no precipitation. Use Prepare imagery to retry.",
            True,
        )
    return "", False


@callback(
    Output("map", "children"),
    Output("map-timestamp", "children"),
    Input("selected-event", "data"),
    Input(PlaybackSliderAIO.ids.slider("playback"), "value"),
    Input("ingestion-result", "data"),
)
def update_radar_layers(selection, slider_val, ingestion_result=None):
    """Update the radar image URL based on the selected event."""
    cmap = "gist_ncar"
    layers = list(BASEMAP)
    scan = selected_scan(selection, slider_val)
    if scan is None:
        return layers, ""
    product = "DBZH"
    url = get_singleband_url(
        scan.timestamp,
        scan.radar,
        product,
        colormap=cmap + "_cut",
        stretch_range="[0,255]",
    )
    revision = "initial"
    if ingestion_result and any(
        event["event_id"] == selection["id"]
        for event in ingestion_result.get("events", [])
    ):
        revision = ingestion_result["revision"]
    layers.append(
        dl.TileLayer(id=f"radar-layer-{revision}", url=url, opacity=RADAR_LAYER_OPACITY)
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
    return layers, scan.timestamp.strftime("%Y-%m-%d %H:%M UTC")


@callback(
    Output("map", "viewport"),
    Input("selected-event", "data"),
)
def update_viewport(selection):
    """Update the map viewport based on the selected event."""
    if selection and selection.get("coordinates"):
        return dict(center=selection["coordinates"], zoom=8, transition="flyTo")
    return dict(center=DEFAULT_COORDS, zoom=6, transition="flyTo")
