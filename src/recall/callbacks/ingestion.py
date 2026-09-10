"""Submit independent imagery jobs and poll their explicit results."""

import logging
from uuid import uuid4

from dash import Input, Output, State, Patch, callback, ctx, no_update
from dash.exceptions import PreventUpdate
from kombu.exceptions import OperationalError


logger = logging.getLogger(__name__)


def polling_error(error):
    logger.error(
        "Cannot read imagery job status",
        exc_info=(type(error), error, error.__traceback__),
    )
    previous = ctx.states.get("ingestion-result.data") or {}
    return (
        {
            **previous,
            "status": "failed",
            "message": "Cannot read worker status. Retrying automatically; check Redis/worker logs.",
        },
        0,
        1,
        "Status unavailable",
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
        task = celery_app.tasks["recall.prepare_imagery"].apply_async(
            args=(event_ids,), retry=False
        )
    except OperationalError:
        logger.exception("Could not enqueue imagery preparation")
        return no_update, {
            **(previous or {}),
            "status": "failed",
            "message": "Could not queue imagery preparation. The catalog is saved; retry when the worker/broker is available.",
        }
    update = Patch()
    update.append(task.id)
    return update, no_update


@callback(
    Output("ingestion-poll", "disabled"),
    Output("ingestion-progress", "class_name"),
    Input("ingestion-jobs", "data"),
    Input("ingestion-result", "data"),
)
def polling_state(jobs, result):
    completed = set((result or {}).get("completed_jobs", []))
    pending = set(jobs or []) - completed
    return not bool(pending), "my-3" if pending else "d-none"


@callback(
    Output("ingestion-result", "data"),
    Output("ingestion-progress", "value"),
    Output("ingestion-progress", "max"),
    Output("ingestion-progress", "label"),
    Input("ingestion-poll", "n_intervals"),
    State("ingestion-jobs", "data"),
    State("ingestion-result", "data"),
    on_error=polling_error,
    prevent_initial_call=True,
)
def poll_imagery(_, jobs, previous):
    from recall.app import celery_app

    previous = previous or {}
    completed = list(previous.get("completed_jobs", []))
    latest = None
    pending = 0
    progress = (0, 1, "Queued; waiting for worker")
    changed = False
    for job_id in jobs or []:
        if job_id in completed:
            continue
        task = celery_app.AsyncResult(job_id)
        state = task.state
        if state == "SUCCESS":
            latest = {
                "job_id": job_id,
                "events": task.result["events"],
                "failed": False,
            }
            completed.append(job_id)
            changed = True
        elif state in ("FAILURE", "REVOKED"):
            logger.error(
                "Imagery job %s ended with state %s; see worker logs", job_id, state
            )
            latest = {"job_id": job_id, "events": [], "failed": True}
            completed.append(job_id)
            changed = True
        else:
            pending += 1
            if state == "PROGRESS":
                info = task.info
                progress = (
                    info["completed"],
                    info["total"],
                    f"{info['completed']}/{info['total']}",
                )
    if not changed:
        return no_update, *progress
    events = latest["events"]
    missing = sum(event["missing"] for event in events)
    failed = sum(event["failed"] for event in events)
    available = sum(event["inserted"] + event["existing"] for event in events)
    result = {
        "status": (
            "failed"
            if latest["failed"]
            else "partial"
            if missing or failed
            else "ready"
        ),
        "message": (
            "Latest completed imagery job failed; check worker logs and retry. "
            "Saved catalog data is unchanged."
            if latest["failed"]
            else f"Latest completed preparation (events {', '.join(str(e['event_id']) for e in events)}): "
            f"{available} scans available, {missing} missing, {failed} failed. "
            f"{pending} jobs pending. Saved catalog data is unchanged."
        ),
        "events": events,
        "completed_jobs": completed,
        "job_id": latest["job_id"],
        "revision": str(uuid4()),
    }
    return result, *progress


@callback(
    Output("ingestion-feedback", "children"),
    Output("ingestion-feedback", "color"),
    Output("ingestion-feedback", "is_open"),
    Input("ingestion-result", "data"),
    Input("ingestion-jobs", "data"),
)
def show_ingestion_result(result, jobs):
    if result and result["status"] == "failed":
        return result["message"], "danger", True
    if jobs and not set(jobs).issubset(set((result or {}).get("completed_jobs", []))):
        return (
            "Imagery jobs queued or running. Catalog saves remain available.",
            "info",
            True,
        )
    if not result:
        return "", "info", False
    colors = {"ready": "success", "partial": "warning", "failed": "danger"}
    return result["message"], colors[result["status"]], True
