from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from dash import no_update

from recall.callbacks import events
from recall.domain import EventValidationError


@pytest.mark.parametrize(
    "updating,imagery_changed", [(False, True), (True, True), (True, False)]
)
def test_save_requests_imagery_only_when_required(
    monkeypatch, updating, imagery_changed
):
    monkeypatch.setattr(
        events,
        "ctx",
        SimpleNamespace(triggered_id="save-event" if updating else "add-event"),
    )
    save = Mock(return_value=(SimpleNamespace(id=42), imagery_changed))
    monkeypatch.setattr(events, "save_event", save)
    signal, request = events.submit_event(
        1, 1, 42, "start", "end", "description", 1, [2]
    )
    assert signal["status"] == ("updated" if updating else "added")
    assert signal["id"] == 42
    assert save.call_args.kwargs["event_id"] == (42 if updating else None)
    if imagery_changed:
        assert request["event_id"] == 42
    else:
        assert request is no_update


def test_invalid_save_does_not_request_ingestion(monkeypatch):
    monkeypatch.setattr(events, "ctx", SimpleNamespace(triggered_id="add-event"))
    monkeypatch.setattr(
        events, "save_event", Mock(side_effect=EventValidationError("invalid"))
    )
    signal, request = events.submit_event(1, 0, None, "", "", "", None, [])
    assert signal["status"] == "invalid"
    assert request is no_update
    assert events.event_feedback(signal) == ("invalid", "danger", True)


def test_save_failure_is_visible_and_does_not_request_ingestion():
    signal, request = events.save_error(RuntimeError("test"))
    assert signal["status"] == "invalid"
    assert "could not be confirmed" in signal["message"]
    assert request is no_update
