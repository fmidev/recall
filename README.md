# RECALL - Radar Event Catalog and Archive Lookup Library

Simple web application to browse precipitation events and related weather radar data.

The events are tagged for interesting features, such as hail, birds, or heavy attenuation.
Events can be filtered by tags. A radar animation is shown for each event.

The browsing filter defaults to **all selected tags** (AND); choose **any selected
tag** for OR matching. Clearing the filter shows all events, including untagged
ones. Filtering never changes event annotations. Selections that no longer match
are cleared; saved events outside the active filter remain in the catalog.

## Deployment

Python 3.12 or newer is required. Container builds use Python 3.12 and locked
dependencies; the web/worker and tile server use the same Terracotta version.
Compose waits for PostgreSQL and Redis health checks. This checks service readiness,
not application migration state; the explicit database setup below is still required.
The worker defaults to two processes to avoid spawning one raster-processing
process per laptop CPU; override `CELERY_CONCURRENCY` when needed.

### In production

Build and run the production version using docker-compose or podman-compose:

```console
podman-compose up
```

### In development

Build the dev version of the main container:

```console
podman build -f Dockerfile.dev -t recall:dev .
```

Run the development version:

```console
podman-compose -f compose.yml -f compose.dev.yml up
```

The development version will mount the source code into the container, so changes to the source code will be reflected in the running container.
However, changes to background callbacks require a restart of the celery worker container.

### First setup and upgrades

Database initialization is explicit; simply opening the UI does not create tables
or sample events. For a **new** stack, run:

```sh
podman-compose -f compose.yml -f compose.dev.yml exec web flask --app recall.app:server db upgrade
podman-compose -f compose.yml -f compose.dev.yml exec web flask --app recall.app:server seed
podman-compose -f compose.yml -f compose.dev.yml exec web flask --app recall.app:server init-tiles
```

Existing installations need the safe baseline procedure in
[Database lifecycle and migrations](docs/database-migrations.md) **before upgrading**.
Do not reset an existing catalog. The same guide describes disposable integration
tests and separate Terracotta version handling.

To restore an existing TOML export into a fresh event database, run
`flask --app recall.app:server import-events /path/to/events.toml --dry-run`
and then repeat without `--dry-run`. The command preserves exported IDs and tag
assignments, refuses to overwrite a differing catalog, and performs no raster I/O.
See the migration guide for details; start **Ingest all** only after verification.

## Event times

Event times are UTC and must fall on five-minute boundaries. Intervals include the
start and exclude the end, so adjacent events may share a boundary but not a scan.
The end must be later than the start. Overlapping events for the same radar are
rejected. Times are not silently rounded.

Saving an event preserves its annotation independently of radar imagery availability.
New events or changed radar/time intervals request background imagery preparation;
description/tag-only edits do not. **Prepare imagery** retries the selected saved
event, and **Ingest all** prepares the entire catalog. Preparation reports available,
missing, and failed scans separately. If a page is closed before its background
request is submitted, retry preparation when returning; the catalog save is preserved.
Once queued, jobs run independently in Celery: preparing another event does not
cancel earlier work. Preparation feedback describes the latest completed job;
retry results do not accumulate obsolete failures. Results are session UI feedback,
not a durable job history.

## Development checks

Use [uv](https://docs.astral.sh/uv/) to reproduce the committed dependency resolution:

```sh
uv sync --locked --python 3.12 --extra test --extra dev
uv run --locked pytest -m 'not integration'
uv run --locked ruff check src tests migrations
```

Unit tests do not need the running stack or network access.
Integration tests use an explicitly configured disposable PostGIS database; see the
[migration guide](docs/database-migrations.md#disposable-postgis-integration-tests).
GitHub Actions runs unit tests/lint on Python 3.12 and 3.14, PostGIS integration
tests on 3.12, and distribution/dependency-export checks.
The existing Hatch mypy environment remains available, but is not yet a passing
type-checking baseline or CI gate.

Use `uv run --locked ruff format <changed-files>` for formatting touched Python
files. Do not reformat unrelated files as part of a feature change.

### Dependency updates

Edit `pyproject.toml`, resolve intentionally, and regenerate the tile server's
hashed requirements from the same lock:

```sh
uv lock
uv export --locked --only-group tile --no-emit-project --output-file terracotta/requirements.txt
```

For intentional upgrades, use `uv lock --upgrade-package <package>` (or `--upgrade`
for a coordinated update) before exporting. Commit both lock artifacts with
manifest changes, run the checks, and rebuild affected images. Terracotta upgrades
also require checking database-format compatibility. Do not edit the generated
tile requirements by hand. Python/uv image versions are explicit in the Dockerfiles.

Local secrets are excluded from wheels, source distributions, and container build
contexts. Supply the optional `FMI_COMMERCIAL_API_KEY` environment variable at
runtime for commercial basemaps; it takes precedence over the legacy local
`src/recall/secrets.py` development fallback. Do not bake credentials into application
artifacts. The WMS key is necessarily sent to the browser for direct tile requests;
use a key intended for that deployment.
