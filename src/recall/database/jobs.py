"""Durable job lifecycle. Every mutation commits before returning."""

from uuid import uuid4

from sqlalchemy import func, update

from recall.database import list_scan_timestamps
from recall.database.connection import db
from recall.database.models import Event, IngestionJob
from recall.domain import EventValidationError


ACTIVE = ("queued", "running")
TERMINAL = ("ready", "partial", "failed")


def serialize_job(job):
    return {
        name: getattr(job, name)
        for name in (
            "id",
            "status",
            "snapshots",
            "results",
            "completed",
            "total",
            "error",
        )
    } | {
        name: getattr(job, name).isoformat() if getattr(job, name) else None
        for name in ("created_at", "updated_at", "started_at", "finished_at")
    }


def create_job(event_ids=None):
    query = db.select(Event).order_by(Event.start_time, Event.id)
    if event_ids is not None:
        query = query.where(Event.id.in_(event_ids))
    events = db.session.scalars(query).all()
    if not events:
        raise EventValidationError("No saved events to prepare.")
    if event_ids is not None and {event.id for event in events} != set(event_ids):
        raise EventValidationError(
            "A selected event no longer exists; reload the catalog."
        )
    snapshots = [
        {
            "event_id": event.id,
            "radar": event.radar.name,
            "description": event.description,
            "start_time": event.start_time.isoformat(),
            "end_time": event.end_time.isoformat(),
            "timestamps": [time.isoformat() for time in list_scan_timestamps(event)],
        }
        for event in events
    ]
    job = IngestionJob(
        id=str(uuid4()),
        status="queued",
        snapshots=snapshots,
        results=[],
        completed=0,
        total=sum(len(snapshot["timestamps"]) for snapshot in snapshots),
    )
    db.session.add(job)
    db.session.commit()
    return serialize_job(job)


def claim_job(job_id):
    """Only one delivery can change queued → running, even across workers."""
    claimed = db.session.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.status == "queued")
        .values(status="running", started_at=func.now(), updated_at=func.now())
        .returning(IngestionJob.id)
    ).scalar_one_or_none()
    db.session.commit()
    if claimed is None:
        return None
    snapshot = serialize_job(db.session.get(IngestionJob, job_id))
    # Serialization refreshes expired ORM fields; close that read transaction
    # before the worker begins raster I/O.
    db.session.commit()
    return snapshot


def record_progress(job_id, completed):
    db.session.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.status == "running")
        .values(completed=completed, updated_at=func.now())
    )
    db.session.commit()


def record_event_result(job_id, result, completed):
    job = db.session.get(IngestionJob, job_id)
    if job.status != "running":
        raise RuntimeError("Cannot record results for an unclaimed job.")
    job.results = [*job.results, result]
    job.completed = completed
    job.updated_at = func.now()
    db.session.commit()


def finish_job(job_id):
    job = db.session.get(IngestionJob, job_id)
    if job.status != "running":
        raise RuntimeError("Cannot finish an unclaimed job.")
    if len(job.results) != len(job.snapshots) or job.completed != job.total:
        raise RuntimeError("Cannot finish a job with unrecorded event outcomes.")
    job.status = (
        "partial" if any(r["missing"] or r["failed"] for r in job.results) else "ready"
    )
    job.updated_at = job.finished_at = func.now()
    db.session.commit()
    return serialize_job(job)


def fail_job(job_id, error, *, expected_status="running"):
    # Roll back a failed SQL operation before recording the independent failure.
    db.session.rollback()
    db.session.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.status == expected_status)
        .values(
            status="failed", error=error, updated_at=func.now(), finished_at=func.now()
        )
    )
    db.session.commit()


def list_jobs(limit=20):
    """Recent terminal history plus ALL active work, not a browser-local list."""
    order = (IngestionJob.created_at.desc(), IngestionJob.id.desc())
    active = db.session.scalars(
        db.select(IngestionJob).where(IngestionJob.status.in_(ACTIVE)).order_by(*order)
    ).all()
    recent = db.session.scalars(
        db.select(IngestionJob)
        .where(IngestionJob.status.in_(TERMINAL))
        .order_by(*order)
        .limit(limit)
    ).all()
    return sorted(
        [serialize_job(job) for job in active + recent],
        key=lambda job: (job["created_at"], job["id"]),
        reverse=True,
    )
