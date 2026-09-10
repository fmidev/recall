from types import SimpleNamespace
from unittest.mock import Mock

from dash import no_update

from recall.callbacks import ingestion


def test_enqueue_preserves_previous_jobs(monkeypatch):
    from recall.app import celery_app

    monkeypatch.setattr(
        ingestion, "ctx", SimpleNamespace(triggered_id="ingestion-request")
    )
    task = celery_app.tasks["recall.prepare_imagery"]
    enqueue = Mock(return_value=SimpleNamespace(id="new-job"))
    monkeypatch.setattr(task, "apply_async", enqueue)
    jobs, result = ingestion.enqueue_imagery(
        {"event_id": 2}, 0, 0, 2, ["previous-job"], None
    )
    assert jobs.to_plotly_json()["operations"] == [
        {"operation": "Append", "location": [], "params": {"value": "new-job"}}
    ]
    assert result is no_update
    enqueue.assert_called_once_with(args=([2],), retry=False)


def test_poll_counts_failures_and_completion_without_canceling_pending(monkeypatch):
    from recall.app import celery_app

    result = {
        "events": [
            {"event_id": 1, "inserted": 1, "existing": 0, "missing": 0, "failed": 0}
        ]
    }
    tasks = {
        "one": SimpleNamespace(state="SUCCESS", result=result),
        "two": SimpleNamespace(state="PROGRESS", info={"completed": 2, "total": 5}),
        "three": SimpleNamespace(state="FAILURE"),
    }
    monkeypatch.setattr(celery_app, "AsyncResult", tasks.__getitem__)
    status, value, maximum, label = ingestion.poll_imagery(1, list(tasks), None)
    assert status["completed_jobs"] == ["one", "three"]
    assert status["status"] == "failed"
    assert (value, maximum, label) == (2, 5, "2/5")
    assert ingestion.polling_state(list(tasks), status) == (False, "my-3")
    again, *_ = ingestion.poll_imagery(2, list(tasks), status)
    assert again is no_update


def test_successful_retry_does_not_retain_previous_missing_scans(monkeypatch):
    from recall.app import celery_app

    previous = {
        "completed_jobs": ["missing"],
        "events": [
            {"event_id": 1, "missing": 1, "failed": 0, "inserted": 0, "existing": 0}
        ],
    }
    task = SimpleNamespace(
        state="SUCCESS",
        result={
            "events": [
                {"event_id": 1, "missing": 0, "failed": 0, "inserted": 1, "existing": 0}
            ]
        },
    )
    monkeypatch.setattr(celery_app, "AsyncResult", lambda _: task)
    result, *_ = ingestion.poll_imagery(1, ["missing", "retry"], previous)
    assert result["status"] == "ready"
    assert result["events"][0]["missing"] == 0
    assert "1 scans available, 0 missing" in result["message"]


def test_polling_stops_after_all_jobs_complete():
    assert ingestion.polling_state(["done"], {"completed_jobs": ["done"]}) == (
        True,
        "d-none",
    )


def test_failed_job_feedback_is_not_success():
    result = {
        "status": "partial",
        "message": "One failed job",
        "completed_jobs": ["done"],
    }
    assert ingestion.show_ingestion_result(result, ["done"]) == (
        "One failed job",
        "warning",
        True,
    )
