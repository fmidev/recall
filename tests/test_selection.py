from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import dash_leaflet as dl
import pytest
from dash import no_update

from recall.callbacks import events, map as map_callbacks, tags
from recall.selection import event_snapshot, selected_scan
from recall.utils import timestamp_marks


@pytest.fixture
def selection():
    start = datetime(2026, 9, 10, 10)
    event = SimpleNamespace(
        id=1,
        radar_id=2,
        radar=SimpleNamespace(name="fikor"),
        start_time=start,
        end_time=start + timedelta(minutes=10),
        description="Case",
        tags=[],
    )
    return event_snapshot(event, [60, 21])


@pytest.mark.parametrize(
    "index,expected", [(0, 0), (1, 1), (99, 1), (-1, 0), (None, 0), (float("nan"), 0)]
)
def test_stale_slider_is_bounded(selection, index, expected):
    assert selected_scan(selection, index).index == expected


def test_missing_selection_has_no_scan():
    assert selected_scan(None, 0) is None
    assert selected_scan({"error": "deleted"}, 0) is None


def test_missing_metadata_is_not_presented_as_no_precipitation(selection):
    message, visible = map_callbacks.scan_feedback(
        selection, 0, {"event_id": 1, "available": []}
    )
    assert visible
    assert "does not indicate no precipitation" in message
    assert map_callbacks.scan_feedback(
        selection, 0, {"event_id": 1, "available": ["202609101000"]}
    ) == ("", False)


def test_map_and_download_use_same_saved_scan(selection):
    layers, label = map_callbacks.update_radar_layers(selection, 99)
    radar_layers = [
        layer
        for layer in layers
        if isinstance(layer, dl.TileLayer)
        and getattr(layer, "id", "").startswith("radar-layer-")
    ]
    assert len(radar_layers) == 1
    assert "/202609101005/fikor/DBZH/" in radar_layers[0].url
    filename, href = events.update_h5_download_link(selection, 99)
    assert filename == "202609101005_radar.polar.fikor.h5"
    assert filename in href
    assert label == "2026-09-10 10:05 UTC"


def test_long_event_still_has_only_one_radar_layer(selection):
    selection["timestamps"] = [
        (datetime(2026, 9, 10) + timedelta(minutes=5 * i)).isoformat()
        for i in range(288)
    ]
    layers, _ = map_callbacks.update_radar_layers(selection, 100)
    assert (
        sum(getattr(layer, "id", "").startswith("radar-layer-") for layer in layers)
        == 1
    )


def test_preparation_completion_replaces_selected_tile_layer(selection):
    before, _ = map_callbacks.update_radar_layers(selection, 0)
    after, _ = map_callbacks.update_radar_layers(
        selection, 0, {"events": [{"event_id": 1}], "revision": "completed-job"}
    )
    assert any(getattr(layer, "id", "") == "radar-layer-initial" for layer in before)
    assert any(
        getattr(layer, "id", "") == "radar-layer-completed-job" for layer in after
    )


def test_switching_event_resets_and_pauses_playback(selection):
    marks, maximum, value, playing, disabled = events.update_slider_marks(selection)
    assert marks
    assert (maximum, value, playing, disabled) == (1, 0, False, False)


def test_one_scan_event_has_a_valid_mark(selection):
    selection["timestamps"] = selection["timestamps"][:1]
    assert events.update_slider_marks(selection) == ({0: "10:00"}, 0, 0, False, False)
    assert timestamp_marks([]) == {}


def test_empty_state_clears_forms_and_disables_playback():
    assert events.update_selected_event(None) == (
        "",
        "",
        "",
        None,
        [],
        True,
        True,
        True,
    )
    assert events.update_slider_marks(None) == ({}, 1, 0, False, True)
    assert events.update_h5_download_link(None, 99) == ("", "#")


def test_deleted_last_event_clears_dropdown(monkeypatch):
    monkeypatch.setattr(
        events, "ctx", SimpleNamespace(triggered_id="events-update-signal")
    )
    session = Mock()
    session.scalars.return_value.all.return_value = []
    monkeypatch.setattr(events.db, "session", session)
    assert events.populate_event_dropdown(
        {"status": "deleted"}, True, {}, [], "all", 1
    ) == (
        [],
        None,
        "No events in the catalog.",
    )


def test_invalid_save_does_not_reset_selection(monkeypatch):
    monkeypatch.setattr(
        events, "ctx", SimpleNamespace(triggered_id="events-update-signal")
    )
    assert events.populate_event_dropdown(
        {"status": "invalid"}, True, {}, [], "all", 1
    ) == (
        no_update,
        no_update,
        no_update,
    )


def test_clicked_tag_not_first_historical_click(monkeypatch):
    monkeypatch.setattr(
        tags, "ctx", SimpleNamespace(triggered_id={"type": "tag-button", "index": 2})
    )
    session = Mock()
    session.get.return_value = SimpleNamespace(
        id=2, name="second", description="Selected"
    )
    monkeypatch.setattr(tags.db, "session", session)
    result = tags.tag_selected(
        1,
        {},
        [3, 1],
        [
            {"type": "tag-button", "index": 1},
            {"type": "tag-button", "index": 2},
        ],
    )
    assert result == ("second", "Selected", 2, False, False)
    assert session.get.call_args.args[1] == 2


@pytest.mark.parametrize("name", [None, "", "  ", "x" * 256])
def test_invalid_tag_names(name):
    assert tags.validate_tag_name(name)


def test_legacy_invalid_event_is_visible_but_not_playable(selection):
    event = SimpleNamespace(
        id=1,
        radar_id=2,
        radar=SimpleNamespace(name="fikor"),
        start_time=datetime(2026, 9, 10, 10, 1),
        end_time=datetime(2026, 9, 10, 10, 4),
        description="Legacy",
        tags=[],
    )
    snapshot = event_snapshot(event, [60, 21])
    assert snapshot["error"]
    assert selected_scan(snapshot, 0) is None
    assert events.update_selected_event(snapshot)[0] == "2026-09-10T10:01:00"
    assert events.event_feedback(None, snapshot)[1:] == ("danger", True)
