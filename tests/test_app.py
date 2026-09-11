import os
import subprocess
import sys


def test_basemap_key_can_be_supplied_without_packaging_secrets():
    environment = {**os.environ, "FMI_COMMERCIAL_API_KEY": "validation-only-not-a-key"}
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from recall.layout import BASEMAP; "
            "assert 'validation-only-not-a-key' in BASEMAP[0].url",
        ],
        env=environment,
        check=True,
        timeout=30,
    )


def test_layout_and_callback_registration():
    from recall.app import server

    client = server.test_client()
    assert client.get("/").status_code == 200
    layout = client.get("/_dash-layout")
    assert layout.status_code == 200
    assert '"active_tab":"events"' in layout.get_data(as_text=True)
    dependencies = client.get("/_dash-dependencies")
    assert dependencies.status_code == 200
    assert "selected-event" in dependencies.get_data(as_text=True)


def test_playback_assets_and_frame_callbacks_are_client_side():
    from recall.app import server

    client = server.test_client()
    dependencies = client.get("/_dash-dependencies").get_json()
    frame_callbacks = [
        callback
        for callback in dependencies
        if any(
            "PlaybackSliderAIO" in item["id"]
            and item["property"] in ("value", "n_intervals", "active", "n_clicks")
            for item in callback["inputs"]
        )
    ]
    assert len(frame_callbacks) == 4
    assert all(callback.get("clientside_function") for callback in frame_callbacks)
    renderer = next(
        c for c in dependencies if "radar-frame-manifest.data" in c["output"]
    )
    assert all(item["property"] != "value" for item in renderer["inputs"])
    asset = client.get("/assets/playback.js")
    assert asset.status_code == 200
    assert "renderFrame" in asset.get_data(as_text=True)


def test_play_button_reserves_its_width_in_narrow_layouts():
    from recall.aios import PlaybackSliderAIO

    component = PlaybackSliderAIO(aio_id="layout-test")
    assert component.children[0].children[0].width == "auto"
