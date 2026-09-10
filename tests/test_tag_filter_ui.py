from types import SimpleNamespace
from unittest.mock import Mock

from recall.callbacks import events


def test_filter_clears_selection_when_it_no_longer_matches(monkeypatch):
    monkeypatch.setattr(events, "ctx", SimpleNamespace(triggered_id="tag-filter"))
    monkeypatch.setattr(events, "browse_events", Mock(return_value=[]))
    options, selected, message = events.populate_event_dropdown(
        None, True, {}, [1], "all", 42
    )
    assert options == [] and selected is None
    assert "No events match" in message


def test_new_saved_event_outside_filter_is_explained(monkeypatch):
    monkeypatch.setattr(
        events, "ctx", SimpleNamespace(triggered_id="events-update-signal")
    )
    monkeypatch.setattr(events, "browse_events", Mock(return_value=[]))
    _, selected, message = events.populate_event_dropdown(
        {"status": "added", "id": 42}, True, {}, [1], "all", None
    )
    assert selected is None
    assert "saved event is outside" in message


def test_deleted_tag_is_removed_from_filter_selection(monkeypatch):
    session = Mock()
    session.scalars.return_value.all.return_value = [SimpleNamespace(id=2, name="rain")]
    monkeypatch.setattr(events.db, "session", session)
    options, value = events.populate_tag_filter(True, {}, [1, 2])
    assert options == [{"label": "rain", "value": 2}]
    assert value == [2]
