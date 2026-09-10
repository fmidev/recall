# Durable imagery preparation

Imagery preparation history is shared by every browser. It is stored in the
catalog PostgreSQL database, not in browser storage or Celery's Redis result
backend. Apply migration `0003_ingestion_jobs` through the normal, explicit
database upgrade procedure before deploying the updated web and worker code.
Do not upgrade a running worker's task protocol in place: queued tasks from the
previous release use a different argument format and must finish before switching
both web and worker to this release.
Existing Redis-only task results are not retroactively imported by the migration;
save any historical results you need before they expire.
New preparation tasks explicitly disable Celery result/error storage: Redis is
the broker, not a second job-history store. A result-backend outage must not block
PostgreSQL failure recording or make submission depend on Redis subscriptions.

## Lifecycle

- Saving a job commits its UUID and event snapshots before publishing the UUID to
  Celery. Snapshots include the radar, description, interval and expected scans.
  Later catalog edits or deletion do not alter or delete the job.
- A worker atomically claims only a `queued` job. Duplicate delivery cannot
  concurrently process the same job, and completed jobs cannot be claimed again.
- Scan progress and each completed event's outcome are committed separately.
  A later exception leaves the preceding event outcomes intact.
- `ready` means every requested scan was inserted or already existed. `partial`
  means the task finished but some scans were missing or failed; inspect each
  event's issues. `failed` means submission or task execution failed; partial
  event outcomes may still be available.
- A publish error is recorded as a failure while the job is still queued. An
  ambiguous broker acknowledgement does not overwrite a worker's already-claimed
  or completed job. A database outage can also prevent recording the error; the
  immediate UI error states that limitation.

Maintenance displays the latest 20 terminal jobs and **all** queued/running jobs,
including their last-update times. All records remain in PostgreSQL; the display
limit does not delete older history. Polling continues while idle to discover
other users' submissions. Map refresh revisions derive from persisted event
outcomes and do not change on every poll.

## Interrupted work and retries

There is no startup ingestion, automatic requeue, lease expiry, or automatic
success inference. A process killed before its failure hook runs can leave a job
`running`; a publish interruption can leave it `queued`. Last update is progress
evidence, **not** proof that a worker remains alive. Check worker/broker status
before retrying; an independent new job may overlap an old worker that is still
running.

Use **Prepare imagery** or **Ingest all** to explicitly create a new job using
current saved-event snapshots. Previous history remains unchanged. Existing scans
are recognized by the ingestion layer. A successful retry replaces the previous
attempt's missing/failed counters in the latest result, not in historical records.
