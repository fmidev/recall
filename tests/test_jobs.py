from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from celery import Celery
from dash import no_update
from flask import Flask, current_app
from kombu.exceptions import OperationalError

from recall.callbacks import ingestion
from recall.database import jobs
from recall.domain import EventValidationError
from recall.tasks import register_tasks
from recall.terracotta.ingest import IngestionResult


def job(job_id="job", status="ready", event_id=1, **kwargs):
    return {
        "id": job_id,
        "status": status,
        "results": [
            {
                "event_id": event_id,
                "inserted": 1,
                "existing": 0,
                "missing": 0,
                "failed": 0,
            }
        ]
        if status in ("ready", "partial")
        else [],
        "snapshots": [
            {
                "event_id": event_id,
                "radar": "test",
                "description": "Saved description",
                "start_time": "2024-01-01T00:00:00",
                "end_time": "2024-01-01T00:05:00",
                "timestamps": ["2024-01-01T00:00:00"],
            }
        ],
        "completed": 1 if status == "ready" else 0,
        "total": 1,
        "error": None,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
        "started_at": None,
        "finished_at": None,
        **kwargs,
    }


def test_enqueue_persists_before_publish_and_uses_durable_identity(monkeypatch):
    from recall.app import celery_app

    monkeypatch.setattr(
        ingestion, "ctx", SimpleNamespace(triggered_id="ingestion-request")
    )
    order = []

    def persist(ids):
        assert ids == [2]
        order.append("persist")
        return job("new-job")

    def publish(**kwargs):
        assert order == ["persist"]
        order.append("publish")
        assert kwargs == {"args": ("new-job",), "task_id": "new-job", "retry": False}

    monkeypatch.setattr(jobs, "create_job", persist)
    monkeypatch.setattr(
        celery_app.tasks["recall.prepare_imagery"], "apply_async", publish
    )
    update, result = ingestion.enqueue_imagery(
        {"event_id": 2, "revision": "saved"}, 0, 0, 2, ["previous-job"], None
    )
    assert order == ["persist", "publish"]
    assert update.to_plotly_json()["operations"][0]["params"]["value"] == "new-job"
    assert result is no_update


def test_broker_failure_is_persisted_and_never_reported_as_success(monkeypatch):
    from recall.app import celery_app

    monkeypatch.setattr(ingestion, "ctx", SimpleNamespace(triggered_id="ingest-all"))
    monkeypatch.setattr(jobs, "create_job", lambda ids: job("failed-job"))
    failure = Mock()
    monkeypatch.setattr(jobs, "fail_job", failure)
    monkeypatch.setattr(
        celery_app.tasks["recall.prepare_imagery"],
        "apply_async",
        Mock(side_effect=OperationalError("broker unavailable")),
    )
    update, result = ingestion.enqueue_imagery(None, 0, 1, None, [], None)
    assert update is no_update
    assert result["status"] == "failed"
    assert "could not confirm queue submission" in result["message"]
    failure.assert_called_once_with(
        "failed-job", result["message"], expected_status="queued"
    )


def test_no_publish_when_snapshot_creation_fails(monkeypatch):
    from recall.app import celery_app

    monkeypatch.setattr(ingestion, "ctx", SimpleNamespace(triggered_id="ingest-all"))
    monkeypatch.setattr(
        jobs, "create_job", Mock(side_effect=EventValidationError("No events"))
    )
    publish = Mock()
    monkeypatch.setattr(
        celery_app.tasks["recall.prepare_imagery"], "apply_async", publish
    )
    _, result = ingestion.enqueue_imagery(None, 0, 1, None, [], None)
    assert result["status"] == "failed"
    assert result["message"] == "No events"
    publish.assert_not_called()


def test_reload_uses_database_not_browser_or_celery_results(monkeypatch):
    from recall.app import celery_app

    read_redis = Mock(side_effect=AssertionError("Redis results must not be read"))
    monkeypatch.setattr(celery_app, "AsyncResult", read_redis)
    history = [job("failed", "failed"), job("running", "running", completed=2, total=5)]
    monkeypatch.setattr(jobs, "list_jobs", lambda: history)
    result, value, maximum, label, rendered = ingestion.poll_imagery(0, [], None)
    assert result["completed_jobs"] == ["failed"]
    assert result["active_jobs"] == ["running"]
    assert (value, maximum, label) == (2, 5, "2/5 · 1 active jobs")
    assert rendered
    assert ingestion.polling_state([], result) == (False, "my-3")
    again, *_, rendered_again = ingestion.poll_imagery(
        1, ["unknown-browser-id"], result
    )
    assert again is no_update
    assert rendered_again is no_update
    read_redis.assert_not_called()


def test_revision_ignores_polling_and_scan_progress_but_changes_on_new_outcome():
    active = job("active", "running", total=5)
    previous, _ = ingestion.summarize_jobs([active, job()])
    active["completed"] = 3
    active["updated_at"] = "2024-01-02T00:00:00+00:00"
    current, _ = ingestion.summarize_jobs([active, job()])
    assert current["revision"] == previous["revision"]
    assert current["history_revision"] != previous["history_revision"]
    active["results"] = job()["results"]
    changed, _ = ingestion.summarize_jobs([active, job()])
    assert changed["revision"] != previous["revision"]


def test_successful_retry_replaces_previous_missing_scan_results():
    previous = job("old", "partial")
    previous["results"][0].update(inserted=0, missing=1)
    result, _ = ingestion.summarize_jobs([job("retry"), previous])
    assert result["status"] == "ready"
    assert result["events"][0]["missing"] == 0
    assert "1 scans available, 0 missing" in result["message"]


def test_other_event_results_do_not_invalidate_this_events_tiles():
    before, _ = ingestion.summarize_jobs([job("first", event_id=1)])
    after, _ = ingestion.summarize_jobs(
        [job("second", event_id=2), job("first", event_id=1)]
    )
    assert before["event_revisions"]["1"] == after["event_revisions"]["1"]
    assert "2" in after["event_revisions"]


def test_latest_failed_job_retains_completed_event_results():
    failed = job("failed", "failed", error="Explicit failure")
    failed["results"] = job()["results"]
    result, _ = ingestion.summarize_jobs([failed])
    assert result["status"] == "failed"
    assert result["events"] == failed["results"]
    assert "Explicit failure" in result["message"]
    assert ingestion.show_ingestion_result(result, []) == (
        result["message"],
        "danger",
        True,
    )


def test_idle_polling_keeps_discovering_other_users_jobs():
    assert ingestion.polling_state([], None) == (False, "d-none")


def test_history_preserves_expanded_items_across_refreshes():
    accordion = ingestion.history_view([job()])[1]
    assert accordion.id == "ingestion-history-accordion"
    assert accordion.persistence is True
    assert accordion.persisted_props == ["active_item"]
    assert accordion.children[0].item_id == "job"


def test_submission_does_not_subscribe_to_a_result_backend(monkeypatch):
    celery = Celery(
        "no-result-subscription", broker="memory://", backend="cache+memory://"
    )
    register_tasks(celery, Flask(__name__))
    subscribe = Mock(side_effect=RuntimeError("result backend is down"))
    monkeypatch.setattr(celery.backend, "on_task_call", subscribe)
    task = celery.tasks["recall.prepare_imagery"]
    assert task.ignore_result
    assert not task.store_errors_even_if_ignored
    task.apply_async(args=("durable-job",), task_id="durable-job", retry=False)
    subscribe.assert_not_called()


def test_failure_persists_even_when_result_backend_cannot_store(monkeypatch):
    import recall.tasks as tasks

    celery = Celery("no-result-storage", broker="memory://", backend="cache+memory://")
    celery.conf.task_store_eager_result = True
    celery.conf.task_always_eager = True
    register_tasks(celery, Flask(__name__))
    monkeypatch.setattr(jobs, "claim_job", lambda _: job(status="running"))
    monkeypatch.setattr(
        tasks, "ingest_scans", Mock(side_effect=RuntimeError("raster bug"))
    )
    failure = Mock()
    monkeypatch.setattr(jobs, "fail_job", failure)
    store = Mock(side_effect=ConnectionError("result backend is down"))
    monkeypatch.setattr(celery.backend, "store_result", store)
    result = celery.tasks["recall.prepare_imagery"].apply_async(
        args=("durable-job",), throw=False
    )
    assert result.failed()
    failure.assert_called_once()
    store.assert_not_called()


def test_duplicate_delivery_does_not_run_ingestion(monkeypatch):
    import recall.tasks as tasks

    monkeypatch.setattr(jobs, "claim_job", lambda _: None)
    scan = Mock()
    monkeypatch.setattr(tasks, "ingest_scans", scan)
    celery = Celery("duplicate-test", broker="memory://", backend="cache+memory://")
    register_tasks(celery, Flask(__name__))
    result = celery.tasks["recall.prepare_imagery"].apply(args=("job",), throw=True)
    assert result.result["duplicate"] is True
    scan.assert_not_called()


def test_each_task_registration_uses_its_own_database_app(monkeypatch):
    servers = [Flask("first"), Flask("second")]
    celery_apps = [
        Celery(name, broker="memory://", backend="cache+memory://")
        for name in ("first", "second")
    ]
    for celery, server in zip(celery_apps, servers):
        register_tasks(celery, server)
    used_servers = []

    def claim(_):
        used_servers.append(current_app._get_current_object())
        return None

    monkeypatch.setattr(jobs, "claim_job", claim)
    for celery in celery_apps:
        celery.tasks["recall.prepare_imagery"].apply(args=("job",), throw=True)
    assert used_servers == servers


@pytest.mark.parametrize("fail_second", [False, True])
def test_task_records_each_result_before_later_failure(monkeypatch, fail_second):
    import recall.tasks as tasks

    saved = job(status="running")
    saved["snapshots"].append(deepcopy(saved["snapshots"][0]))
    saved["snapshots"][1]["event_id"] = 2
    monkeypatch.setattr(jobs, "claim_job", lambda _: saved)
    records = []
    progress = Mock()
    failure = Mock()
    finish = Mock(return_value={"results": records})
    monkeypatch.setattr(
        jobs, "record_event_result", lambda _, result, __: records.append(result)
    )
    monkeypatch.setattr(jobs, "record_progress", progress)
    monkeypatch.setattr(jobs, "fail_job", failure)
    monkeypatch.setattr(jobs, "finish_job", finish)

    def scans(times, radar, report):
        if records and fail_second:
            raise RuntimeError("second event failed")
        report((1, 1, "1/1"))
        return IngestionResult(inserted=1)

    monkeypatch.setattr(tasks, "ingest_scans", scans)
    celery = Celery("outcome-test", broker="memory://", backend="cache+memory://")
    register_tasks(celery, Flask(__name__))
    result = celery.tasks["recall.prepare_imagery"].apply(args=("job",), throw=False)
    assert records[0]["event_id"] == 1
    progress.assert_any_call("job", 1)
    if fail_second:
        assert result.failed()
        assert len(records) == 1
        failure.assert_called_once()
        assert "RuntimeError" in failure.call_args.args[1]
        finish.assert_not_called()
    else:
        assert result.successful()
        assert len(records) == 2
        failure.assert_not_called()
        finish.assert_called_once_with("job")
