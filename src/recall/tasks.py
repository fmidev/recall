"""Independent Celery jobs: preparing another event never cancels earlier work."""

from dataclasses import asdict
from datetime import datetime
import logging

from celery import Task
from sqlalchemy.exc import SQLAlchemyError

from recall.database import jobs
from recall.terracotta.ingest import ingest_scans


logger = logging.getLogger(__name__)


def register_tasks(celery_app, server):
    class DurableIngestionTask(Task):
        def on_failure(self, exc, task_id, args, kwargs, einfo):
            if getattr(self.request, "ingestion_claimed", False):
                with server.app_context():
                    try:
                        jobs.fail_job(
                            args[0] if args else kwargs["job_id"],
                            f"{type(exc).__name__}: preparation stopped "
                            f"({getattr(self.request, 'ingestion_stage', 'starting job')}). "
                            "See worker logs; retry explicitly to create a new job.",
                        )
                    except SQLAlchemyError:
                        logger.exception(
                            "Could not persist failure for job %s", task_id
                        )
            super().on_failure(exc, task_id, args, kwargs, einfo)

    @celery_app.task(
        bind=True,
        base=DurableIngestionTask,
        name="recall.prepare_imagery",
        shared=False,
        ignore_result=True,
        store_errors_even_if_ignored=False,
    )
    def prepare_imagery(task, job_id):
        task.request.ingestion_claimed = False
        with server.app_context():
            job = jobs.claim_job(job_id)
            if job is None:
                return {"job_id": job_id, "duplicate": True}
            task.request.ingestion_claimed = True
            completed = 0
            for snapshot in job["snapshots"]:
                task.request.ingestion_stage = f"event {snapshot['event_id']}"
                times = [
                    datetime.fromisoformat(time) for time in snapshot["timestamps"]
                ]

                def progress(update):
                    value, _, _ = update
                    jobs.record_progress(job_id, completed + value)

                result = ingest_scans(times, snapshot["radar"], progress)
                completed += len(times)
                jobs.record_event_result(
                    job_id,
                    {"event_id": snapshot["event_id"], **asdict(result)},
                    completed,
                )
            task.request.ingestion_stage = "saving final outcome"
            result = jobs.finish_job(job_id)
            return {"job_id": job_id, "events": result["results"]}
