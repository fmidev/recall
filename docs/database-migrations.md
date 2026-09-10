# Database lifecycle and migrations

RECALL has separate event (`recalldb`) and raster-metadata (`terracotta`)
databases. Alembic manages **only the event database**. Starting the app does not
create tables, seed records, stamp revisions, or ingest sample events.

Run commands from the repository root with the intended `PREVENT_DB_URI` set.
Always confirm the server/database identity and take a tested backup before
changing a deployed database. Stop web/worker writers during maintenance.
Do not reset databases or remove volumes to resolve a migration error.

## New event database

Provision an empty PostgreSQL database. The migration role must be able to create
the `postgis` and `btree_gist` extensions, or an administrator must install them
in this database first.

```sh
flask --app recall.app:server db upgrade
flask --app recall.app:server seed
flask --app recall.app:server db current
```

`seed` explicitly inserts missing radar and basic-tag records. It is idempotent,
preserves existing descriptions/locations, and never creates events or performs
network ingestion. A conflicting radar FMISID under a different name aborts the
entire seed transaction for manual review. Regular application startup never
invokes this command.

## Restoring a TOML catalog into a fresh database

Create the current schema with `db upgrade` and seed the radar definitions first.
There is no legacy database to baseline when restoring an export into a new database.

```sh
flask --app recall.app:server import-events /path/to/events.toml --dry-run
flask --app recall.app:server import-events /path/to/events.toml
```

The importer validates every record, radar identifier and interval before writing.
It preserves exported event IDs, descriptions, times and named tag assignments,
creates missing tags with empty descriptions, and preserves existing reference
tag descriptions. Inserts are committed in one transaction. An exact repeat is
a no-op; a nonempty differing catalog is rejected rather than merged or overwritten.
The export does not contain tag descriptions/hierarchy or raster metadata.

Import never starts imagery jobs. Verify the restored catalog and back it up before
using **Ingest all**, so ingestion can run against a finalized worker deployment.

## Existing databases created with `create_all()`

Do **not** upgrade blindly: revision `0001_initial` creates the legacy tables and
will correctly fail if those tables already exist. Do **not** stamp `head`, since
that would claim interval constraints exist without installing them.

1. Back up the event database; test restoring the backup to a separate database.
   Stop application/worker writes and confirm the configured database identity.
2. Inspect migration state and check the legacy schema:

   ```sh
   flask --app recall.app:server db current
   flask --app recall.app:server db history
   flask --app recall.app:server verify-baseline
   ```

   The read-only verifier requires the five legacy application tables in `public`,
   matching column types/nullability/defaults, primary/unique/foreign keys, and the
   radar location GiST index. It checks geography POINT/EPSG:4326 and
   timezone-naive timestamps and rejects extra check/exclusion constraints.
   An already-versioned database must follow its existing revision history instead.
   The verifier neither stamps nor changes anything. Review any mismatch; do not
   bypass it or assume that similarly named tables have the expected schema.
3. **Only after successful verification and operator review**, establish the
   baseline explicitly:

   ```sh
   flask --app recall.app:server db stamp 0001_initial
   flask --app recall.app:server db upgrade
   flask --app recall.app:server seed
   ```

4. Verify `db current` reports `0003_ingestion_jobs`, then restart writers.

The second revision locks the event table for its audit and constraint installation.
It reports invalid event IDs and overlapping ID pairs and aborts without modifying
curated records. Fix only explicitly reviewed data, retaining a backup/audit trail,
then rerun `db upgrade`. It does not round timestamps, delete events, or resolve
overlaps automatically. This migration requires an online database connection;
offline `db upgrade --sql` is intentionally unsupported.

Revision `0003_ingestion_jobs` adds a separate durable preparation-history table,
without changing curated event/tag rows. Drain old-format Celery tasks before
updating both worker and web code; see [imagery jobs](ingestion-jobs.md).

## Interval contract

Times remain `timestamp without time zone`, interpreted by the application as
UTC. They are not implicitly converted to local time. SQL clients must likewise
supply UTC-naive values; the column cannot identify the originating time zone.

Revision `0002_event_intervals` adds named constraints:

- `event_positive_interval`: end strictly after start.
- `event_five_minute_alignment`: both endpoints on five-minute boundaries,
  including zero seconds and microseconds.
- `event_radar_no_overlap`: PostgreSQL GiST exclusion on radar ID and
  `tsrange(start_time, end_time, '[)')`, using `btree_gist`. It prevents concurrent
  overlapping writes, including containment. Adjacent events and different radars
  are allowed; updates do not conflict with their own row.

Downgrading to `0001_initial` removes these constraints, not event data.
Downgrading the initial revision drops application tables and **destroys data**;
never use it as a routine repair. Neither downgrade removes shared extensions.

## Developing revisions

```sh
flask --app recall.app:server db migrate -m "describe schema change"
# Review generated SQL, upgrade/downgrade paths and existing-data handling.
flask --app recall.app:server db upgrade
```

Commit revisions with model changes. The dev overlay mounts only `src`; generate
migrations on the host or explicitly mount `migrations` when working in a container.
Test new and existing-data paths before deployment.

## Disposable PostGIS integration tests

Install the existing test extra (`pip install -e '.[test]'`). Integration tests
are skipped unless `RECALL_TEST_DB_URI` is explicitly set. The URI **and connected
database** must have a database name ending in `_test`; other names are refused.
Tests destroy/recreate application tables in that database, so use a dedicated
disposable instance, never a shared deployment. Do not run these tests concurrently
against the same database.

For example, start an isolated container on a random localhost port (choose a
unique container name if this one exists):

```sh
podman run -d --name recall-postgis-integration \
  -e POSTGRES_DB=recall_integration_test \
  -e POSTGRES_PASSWORD=test-only \
  -p 127.0.0.1::5432 docker.io/postgis/postgis:16-3.4
podman port recall-postgis-integration 5432
podman exec recall-postgis-integration pg_isready -U postgres -d recall_integration_test
# Wait for pg_isready to succeed, then use the printed host port:
RECALL_TEST_DB_URI='postgresql://postgres:test-only@127.0.0.1:PORT/recall_integration_test' \
  .venv/bin/python -m pytest tests/integration
# Remove only the disposable container created above:
podman rm -f -v recall-postgis-integration
```

The fixtures construct a minimal Flask application and never import/start the
Dash app, Celery worker, or Terracotta server. Tests cover blank migrations,
manual legacy baselining, invalid-data preservation, seed idempotence, constraint
boundaries, concurrent overlaps, and application overlap queries.

## Terracotta metadata

Terracotta manages its own schema/version separately. Back it up and check the
installed Terracotta version before upgrading. For a version mismatch, either
restore/pin a compatible version or plan a separately approved metadata rebuild
after testing it on a disposable database. Do not drop tables as an automatic
repair and never reset the event database to repair Terracotta.

For a new installation, create the Terracotta database explicitly using
`flask --app recall.app:server init-tiles` with `TC_DB_URI` configured. Its PostgreSQL
role must be able to create databases. This uses Terracotta's public API and refuses
to replace an existing database. New Compose installations pre-create only
`recalldb`; `init-tiles` creates `terracotta` including its metadata tables.

Older Compose installations may already have an empty `terracotta` database.
Do not run `init-tiles` against it or automatically delete it. Verify whether it
contains metadata. For an empty legacy database, provision a new database name
through `TC_DB_URI`, run `init-tiles`, and configure `TC_DRIVER_PATH` on the tile
server to match. Retire the old empty database only after operator review.

Catalog saves commit independently of imagery preparation. New events and
radar/time edits request preparation; description/tag edits do not.
**Prepare imagery** retries the selected saved event, and Maintenance **Ingest all**
processes all events. Viewing alone does not ingest. Re-ingestion can require
substantial external I/O; preserve the curated event/tag database throughout.
