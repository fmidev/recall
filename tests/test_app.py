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
