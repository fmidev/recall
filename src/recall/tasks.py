"""Independent Celery jobs: preparing another event never cancels earlier work."""

from dataclasses import asdict

from recall.database import list_scan_timestamps
from recall.database.connection import db
from recall.database.models import Event
from recall.domain import EventValidationError
from recall.terracotta.ingest import ingest_scans


def register_tasks(celery_app, server):
    @celery_app.task(bind=True, name="recall.prepare_imagery")
    def prepare_imagery(task, event_ids=None):
        with server.app_context():
            query = db.select(Event).order_by(Event.start_time)
            if event_ids is not None:
                query = query.where(Event.id.in_(event_ids))
            events = db.session.scalars(query).all()
            if not events:
                raise EventValidationError("No saved events to prepare.")
            targets = [
                (event.id, event.radar.name, list_scan_timestamps(event))
                for event in events
            ]
        total = sum(len(times) for _, _, times in targets)
        completed = 0
        results = []
        for event_id, radar, times in targets:

            def progress(update):
                value, _, _ = update
                task.update_state(
                    state="PROGRESS",
                    meta={"completed": completed + value, "total": total},
                )

            result = ingest_scans(times, radar, progress)
            results.append({"event_id": event_id, **asdict(result)})
            completed += len(times)
        return {"events": results}
