"""Submit independent jobs; PostgreSQL is the shared source of history and progress."""

import hashlib
import json
import logging

from dash import Input, Output, State, Patch, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from kombu.exceptions import EncodeError, OperationalError
from sqlalchemy.exc import SQLAlchemyError

from recall.database import jobs as job_store
from recall.domain import EventValidationError


logger = logging.getLogger(__name__)


def polling_error(error):
    logger.error(
        "Cannot read imagery job history",
        exc_info=(type(error), error, error.__traceback__),
    )
    previous = ctx.states.get("ingestion-result.data") or {}
    message = (
        "Cannot read durable imagery history. Retrying status checks automatically; "
        "check the catalog database. No jobs have been requeued."
    )
    return (
        {**previous, "status": "failed", "message": message},
        0,
        1,
        "Status unavailable",
        html.P(message, className="text-danger"),
    )


@callback(
    Output("ingestion-jobs", "data"),
    Output("ingestion-result", "data", allow_duplicate=True),
    Input("ingestion-request", "data"),
    Input("prepare-imagery", "n_clicks"),
    Input("ingest-all", "n_clicks"),
    State("event-dropdown", "value"),
    State("ingestion-jobs", "data"),
    State("ingestion-result", "data"),
    running=[
        (Output("prepare-imagery", "disabled"), True, False),
        (Output("ingest-all", "disabled"), True, False),
        (Output("event-save-buttons", "disabled"), True, False),
    ],
    prevent_initial_call=True,
)
def enqueue_imagery(request, retry_clicks, all_clicks, selected_id, jobs, previous):
    from recall.app import celery_app

    if ctx.triggered_id == "ingestion-request":
        if not request:
            raise PreventUpdate
        event_ids = [request["event_id"]]
    elif ctx.triggered_id == "prepare-imagery":
        if not selected_id:
            return no_update, {
                **(previous or {}),
                "status": "failed",
                "message": "Select a saved event first.",
            }
        event_ids = [selected_id]
    else:
        event_ids = None
    try:
        job = job_store.create_job(event_ids)
    except (EventValidationError, SQLAlchemyError) as exc:
        logger.exception("Could not persist imagery job")
        return no_update, {
            **(previous or {}),
            "status": "failed",
            "message": (
                str(exc)
                if isinstance(exc, EventValidationError)
                else "Could not save imagery job history. Nothing was queued; check the catalog database."
            ),
        }
    try:
        celery_app.tasks["recall.prepare_imagery"].apply_async(
            args=(job["id"],), task_id=job["id"], retry=False
        )
    except (OperationalError, EncodeError, OSError) as exc:
        logger.exception("Could not enqueue imagery preparation %s", job["id"])
        message = (
            f"{type(exc).__name__}: could not confirm queue submission. "
            "The saved catalog is unchanged. Check the broker/worker, then retry explicitly."
        )
        try:
            job_store.fail_job(job["id"], message, expected_status="queued")
        except SQLAlchemyError:
            logger.exception("Could not record queue failure for %s", job["id"])
            message += (
                " Failure could not be recorded; the durable job may still show queued."
            )
        return no_update, {
            **(previous or {}),
            "status": "failed",
            "job_id": job["id"],
            "message": message,
        }
    update = Patch()
    update.append(job["id"])
    return update, no_update


@callback(
    Output("ingestion-poll", "disabled"),
    Output("ingestion-progress", "class_name"),
    Input("ingestion-jobs", "data"),
    Input("ingestion-result", "data"),
)
def polling_state(jobs, result):
    # Keep checking even when idle: another browser can submit independent work.
    return False, "my-3" if (result or {}).get("active_jobs") else "d-none"


def job_summary(job):
    available = sum(r["inserted"] + r["existing"] for r in job["results"])
    missing = sum(r["missing"] for r in job["results"])
    failed = sum(r["failed"] for r in job["results"])
    return f"{available} scans available, {missing} missing, {failed} failed"


def history_view(jobs):
    if not jobs:
        return html.P("No imagery preparation jobs yet.")
    return [
        html.P(
            "Shared history: latest 20 finished jobs and all queued/running jobs. "
            "Times include their UTC offset. A stopped worker may leave a job running; "
            "last update is not proof of liveness. Nothing is retried automatically. "
            "Check the worker before using Prepare imagery or Ingest all to create "
            "a new job; the old record is retained."
        ),
        dbc.Accordion(
            [
                dbc.AccordionItem(
                    [
                        html.P(
                            f"Last update: {job['updated_at']}; "
                            f"started: {job['started_at'] or 'not started'}; "
                            f"finished: {job['finished_at'] or 'not finished'}."
                        ),
                        html.P(job_summary(job)),
                        html.P(job["error"], className="text-danger")
                        if job["error"]
                        else None,
                        html.Ul(
                            [
                                html.Li(
                                    f"Event {snapshot['event_id']} · {snapshot['radar']} · "
                                    f"{snapshot['start_time']} – {snapshot['end_time']} UTC · "
                                    f"{snapshot['description'] or ''}"
                                )
                                for snapshot in job["snapshots"]
                            ]
                        ),
                        html.Ul(
                            [
                                html.Li(
                                    [
                                        f"Event {result['event_id']}: "
                                        f"{result['inserted']} inserted, {result['existing']} existing, "
                                        f"{result['missing']} missing, {result['failed']} failed.",
                                        html.Ul(
                                            [
                                                html.Li(issue)
                                                for issue in result.get("issues", [])
                                            ]
                                        ),
                                    ]
                                )
                                for result in job["results"]
                            ]
                        ),
                    ],
                    title=(
                        f"{job['created_at']} · {job['status']} · "
                        f"{job['completed']}/{job['total']} scans · job {job['id']}"
                    ),
                    item_id=job["id"],
                )
                for job in jobs
            ],
            id="ingestion-history-accordion",
            always_open=True,
            active_item=[],
            persistence=True,
            persisted_props=["active_item"],
            persistence_type="memory",
        ),
    ]


def summarize_jobs(jobs):
    active = [job for job in jobs if job["status"] in job_store.ACTIVE]
    latest = jobs[0] if jobs else None
    # The newest attempt with a completed outcome wins for each event; a retry
    # never inherits missing/failed counters from its previous attempt.
    outcomes = {}
    revisions = {}
    for job in jobs:
        for result in job["results"]:
            event_id = result["event_id"]
            if event_id not in outcomes:
                outcomes[event_id] = result
                revisions[event_id] = (job["id"], result)
    revision = hashlib.sha256(
        json.dumps(revisions, sort_keys=True).encode()
    ).hexdigest()[:20]
    result = {
        "status": latest["status"] if latest else "idle",
        "message": (
            f"Latest preparation: {latest['status']}; {job_summary(latest)}. "
            f"{latest['error'] or ''} {len(active)} jobs queued/running. "
            "Saved catalog data is unchanged."
            if latest
            else "No imagery preparation jobs yet."
        ),
        "events": list(outcomes.values()),
        "completed_jobs": [
            job["id"] for job in jobs if job["status"] in job_store.TERMINAL
        ],
        "active_jobs": [job["id"] for job in active],
        "job_id": latest["id"] if latest else None,
        "revision": revision,
        "event_revisions": {
            str(event_id): hashlib.sha256(
                json.dumps(outcome, sort_keys=True).encode()
            ).hexdigest()[:20]
            for event_id, outcome in revisions.items()
        },
        "history_revision": hashlib.sha256(
            json.dumps(jobs, sort_keys=True).encode()
        ).hexdigest()[:20],
    }
    completed = sum(job["completed"] for job in active)
    total = sum(job["total"] for job in active)
    progress = (
        completed,
        max(total, 1),
        f"{completed}/{total} · {len(active)} active jobs"
        if active
        else "No active jobs",
    )
    return result, progress


@callback(
    Output("ingestion-result", "data"),
    Output("ingestion-progress", "value"),
    Output("ingestion-progress", "max"),
    Output("ingestion-progress", "label"),
    Output("ingestion-history", "children"),
    Input("ingestion-poll", "n_intervals"),
    State("ingestion-jobs", "data"),
    State("ingestion-result", "data"),
    on_error=polling_error,
)
def poll_imagery(_, jobs, previous):
    history = job_store.list_jobs()
    result, progress = summarize_jobs(history)
    unchanged_history = previous is not None and result[
        "history_revision"
    ] == previous.get("history_revision")
    return (
        no_update if result == previous else result,
        *progress,
        no_update if unchanged_history else history_view(history),
    )


@callback(
    Output("ingestion-feedback", "children"),
    Output("ingestion-feedback", "color"),
    Output("ingestion-feedback", "is_open"),
    Input("ingestion-result", "data"),
    Input("ingestion-jobs", "data"),
)
def show_ingestion_result(result, jobs):
    if not result or result["status"] == "idle":
        return "", "info", False
    colors = {"ready": "success", "partial": "warning", "failed": "danger"}
    return result["message"], colors.get(result["status"], "info"), True
