from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

from celery import Celery
from flask_migrate import downgrade, upgrade
import pytest
from sqlalchemy import inspect, text

from recall.database import jobs
from recall.database.connection import db
from recall.database.models import Event, IngestionJob
from recall.tasks import register_tasks
from recall.terracotta.ingest import IngestionResult

from conftest import MIGRATIONS


pytestmark = pytest.mark.integration


def save_event(radar, offset=0):
    start = datetime(2024, 1, 1) + timedelta(minutes=offset)
    event = Event(
        radar=radar,
        start_time=start,
        end_time=start + timedelta(minutes=5),
        description="Snapshot description",
    )
    db.session.add(event)
    db.session.commit()
    return event


def outcome(event_id, **kwargs):
    return {
        "event_id": event_id,
        "inserted": 1,
        "existing": 0,
        "missing": 0,
        "failed": 0,
        **kwargs,
    }


def test_job_migration_roundtrip_preserves_catalog(radars):
    event = save_event(radars[0])
    event_id = event.id
    assert (
        db.session.scalar(text("SELECT version_num FROM alembic_version"))
        == "0003_ingestion_jobs"
    )
    downgrade(directory=MIGRATIONS, revision="0002_event_intervals")
    assert "ingestion_job" not in inspect(db.engine).get_table_names()
    assert db.session.get(Event, event_id).description == "Snapshot description"
    upgrade(directory=MIGRATIONS)
    assert jobs.list_jobs() == []


def test_history_survives_event_deletion_and_session_restart(radars):
    event = save_event(radars[0])
    event_id = event.id
    created = jobs.create_job([event_id])
    db.session.delete(event)
    db.session.commit()
    db.session.remove()
    restored = jobs.list_jobs()
    assert restored[0]["id"] == created["id"]
    assert restored[0]["snapshots"][0]["description"] == "Snapshot description"
    assert restored[0]["snapshots"][0]["event_id"] == event_id
    assert restored[0]["status"] == "queued"
    claimed = jobs.claim_job(created["id"])
    assert claimed["snapshots"] == created["snapshots"]


def test_worker_uses_snapshot_after_event_edit_and_deletion(
    radars, migrated_db, monkeypatch
):
    import recall.tasks as tasks

    event = save_event(radars[0])
    event_id = event.id
    created = jobs.create_job([event_id])
    event.start_time += timedelta(days=1)
    event.end_time += timedelta(days=1)
    db.session.commit()
    db.session.delete(event)
    db.session.commit()
    calls = []

    def scan(times, radar, report):
        calls.append((times, radar))
        report((1, 1, "1/1"))
        return IngestionResult(inserted=1)

    monkeypatch.setattr(tasks, "ingest_scans", scan)
    celery = Celery("snapshot-test", broker="memory://", backend="cache+memory://")
    register_tasks(celery, migrated_db)
    result = celery.tasks["recall.prepare_imagery"].apply(
        args=(created["id"],), throw=True
    )
    assert result.successful()
    assert calls == [([datetime(2024, 1, 1)], "test-one")]
    db.session.remove()
    assert jobs.list_jobs()[0]["results"] == [outcome(event_id, issues=[])]


def test_atomic_claim_allows_one_worker(radars, migrated_db):
    event = save_event(radars[0])
    created = jobs.create_job([event.id])
    barrier = Barrier(2)

    def claim():
        with migrated_db.app_context():
            barrier.wait(timeout=10)
            return jobs.claim_job(created["id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = list(executor.map(lambda _: claim(), range(2)))
    assert sum(result is not None for result in attempts) == 1
    db.session.remove()
    history = jobs.list_jobs()
    assert history[0]["status"] == "running"
    assert history[0]["started_at"]
    assert jobs.claim_job(created["id"]) is None


@pytest.mark.parametrize("missing, expected", [(0, "ready"), (1, "partial")])
def test_terminal_state_and_results_are_durable(radars, missing, expected):
    event = save_event(radars[0])
    created = jobs.create_job([event.id])
    jobs.claim_job(created["id"])
    jobs.record_progress(created["id"], 1)
    jobs.record_event_result(
        created["id"], outcome(event.id, inserted=1 - missing, missing=missing), 1
    )
    jobs.finish_job(created["id"])
    db.session.remove()
    restored = jobs.list_jobs()[0]
    assert restored["status"] == expected
    assert restored["finished_at"]
    assert restored["completed"] == restored["total"] == 1
    assert restored["results"][0]["missing"] == missing
    assert jobs.claim_job(created["id"]) is None


def test_task_failure_keeps_previous_event_outcome(radars, migrated_db, monkeypatch):
    import recall.tasks as tasks

    first = save_event(radars[0])
    second = save_event(radars[0], offset=5)
    first_id, second_id = first.id, second.id
    created = jobs.create_job([first_id, second_id])
    calls = []

    def scan(times, radar, report):
        calls.append(times)
        if len(calls) == 2:
            raise RuntimeError("event two stopped")
        report((1, 1, "1/1"))
        return IngestionResult(inserted=1)

    monkeypatch.setattr(tasks, "ingest_scans", scan)
    celery = Celery("durable-test", broker="memory://", backend="cache+memory://")
    register_tasks(celery, migrated_db)
    result = celery.tasks["recall.prepare_imagery"].apply(
        args=(created["id"],), throw=False
    )
    assert result.failed()
    db.session.remove()
    restored = jobs.list_jobs()[0]
    assert restored["status"] == "failed"
    assert "RuntimeError" in restored["error"]
    assert restored["results"] == [outcome(first_id, issues=[])]
    assert restored["completed"] == 1
    assert restored["total"] == 2


def test_history_limit_never_hides_old_active_jobs(radars):
    event = save_event(radars[0])
    queued = jobs.create_job([event.id])
    running = jobs.create_job([event.id])
    jobs.claim_job(running["id"])
    for _ in range(4):
        created = jobs.create_job([event.id])
        jobs.fail_job(created["id"], "Broker unavailable", expected_status="queued")
    db.session.remove()
    history = jobs.list_jobs(limit=2)
    assert len(history) == 4
    assert {job["id"] for job in history if job["status"] in jobs.ACTIVE} == {
        queued["id"],
        running["id"],
    }
    assert db.session.get(IngestionJob, running["id"]).finished_at is None


def test_submission_failure_cannot_overwrite_running_or_finished_job(radars):
    event = save_event(radars[0])
    created = jobs.create_job([event.id])
    jobs.claim_job(created["id"])
    jobs.fail_job(created["id"], "Ambiguous broker failure", expected_status="queued")
    assert jobs.list_jobs()[0]["status"] == "running"
    jobs.record_event_result(created["id"], outcome(event.id), 1)
    jobs.finish_job(created["id"])
    jobs.fail_job(created["id"], "Late failure")
    assert jobs.list_jobs()[0]["status"] == "ready"
