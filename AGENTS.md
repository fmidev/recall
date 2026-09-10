# Working on RECALL

## Purpose and priorities

RECALL (Radar Event Catalog and Archive Lookup Library) helps researchers browse
weather radar observations and curate interesting events with descriptive tags.
The main use is finding cases for testing processing algorithms, such as attenuation
correction or melting layer detection. It is a case-discovery and annotation tool,
not itself a radar processing pipeline.

Prioritize scientific correctness, preservation of curated data, and maintainability.
Keep the workflow simple: select a radar and time interval, inspect the animation,
describe and tag the event, then retrieve observations or export the catalog.
Do not infer new scientific requirements or change data semantics without confirmation.

This is the shared, repository-wide agent guide. Keep it current when architecture,
commands, or conventions change; avoid duplicating it in tool-specific instructions.

## Start here

- Read [README.md](README.md) for the overview and
  [pyproject.toml](pyproject.toml) for packaging and dependencies.
- Inspect the working tree before editing; preserve unrelated work.
- Trace a feature through its layout IDs, callback inputs/outputs, database operations,
  and background work before changing it.
- Prefer a focused, complete change over a framework rewrite or speculative abstraction.
  Ask before changing scientific conventions, persistence formats, or deployment scope.

## Architecture and code map

The application is Python, Plotly Dash, Dash Bootstrap Components, and dash-leaflet.
[compose.yml](compose.yml) defines five services:

| Service | Role |
| --- | --- |
| `web` | Dash UI, served by Gunicorn on port 8050 in production |
| `celery_worker` | Dash background callbacks, including radar metadata ingestion |
| `redis` | Celery broker and result backend |
| `db` | PostGIS; hosts separate **databases** `recalldb` and `terracotta`, not two application schemas |
| `terracotta` | Reads radar GeoTIFFs and serves XYZ map tiles on port 8088 |

The browser talks to Dash and fetches tiles directly from Terracotta. App/worker
code writes event data through SQLAlchemy and raster metadata through the Terracotta
driver. GeoTIFFs remain in public FMI S3; ingestion registers their paths and metadata,
not a local archive of raw observations.

| Location | Responsibility |
| --- | --- |
| [src/recall/app.py](src/recall/app.py) | App factory, module-level Dash/Flask/Celery instances, explicit callback imports, startup and event-save/ingestion callbacks |
| [src/recall/layout.py](src/recall/layout.py) | Component tree, IDs, stores, forms, basemaps |
| [src/recall/aios.py](src/recall/aios.py) | Reusable playback slider and its callbacks |
| [src/recall/callbacks/](src/recall/callbacks/) | Event selection/deletion, tags, map rendering, TOML export |
| [src/recall/database/models.py](src/recall/database/models.py) | ORM models, relationships, initial radar/tag seeds |
| [src/recall/database/queries.py](src/recall/database/queries.py) | Event operations, overlap checks, startup setup, export records |
| [src/recall/database/__init__.py](src/recall/database/__init__.py) | Shared scan timestamp generation |
| [src/recall/terracotta/](src/recall/terracotta/) | S3 path construction, metadata ingestion, tile URLs |
| [src/recall/utils.py](src/recall/utils.py), [src/recall/visuals.py](src/recall/visuals.py) | Timeline labels and display colormap helpers |
| [terracotta/](terracotta/) | Separate tile-server image, dependencies, generated colormaps |
| [migrations/](migrations/) | Flask-Migrate/Alembic configuration |

## Domain and data contracts

- An event belongs to one radar and has a start/end time, description, and many-to-many
  tags. Radar names such as `fikor` are identifiers used in archive paths, not UI-only
  labels. Tags have unique names; parent/child relationships exist in the model but
  are not exposed by the current tag editor. Event filtering by tags is not implemented.
- The UI labels times as **UTC**, while current Python/SQLAlchemy timestamps are
  timezone-naive. Do not apply local-time conversions implicitly. A move to aware
  timestamps needs coordinated input, storage, export, and archive-lookup changes.
- Event intervals are UTC, five-minute-aligned, and half-open: start included, end
  excluded. The end must be later than the start; adjacent events are allowed, overlaps
  for the same radar are not. Reuse `validate_event_interval` and
  `list_scan_timestamps`; never silently round. Scan times are expected timestamps,
  not a guarantee that an archive file exists.
- Radar locations are PostGIS geography points in EPSG:4326: database coordinates are
  longitude/latitude, Leaflet centers are latitude/longitude. Reuse `get_coords`.
- Terracotta key order is `(timestamp, radar, product)`; timestamps use `YYYYMMDDHHMM`.
  S3 paths use `YYYY/MM/DD/<radar>/<timestamp>_<radar>_<PRODUCT>.tif` in
  `fmi-opendata-radar-geotiff`, with unsigned access.
- Current ingestion tries `DBZH`, then legacy `DBZ-1`, normalizing reflectivity to the
  `DBZH` dataset key. Changes to products, scaling, or colormaps must stay consistent
  across ingestion, tile URLs, and the displayed legend. Do not conflate encoded pixel
  values with physical reflectivity units (dBZ).
- Creating/updating events ingests metadata; merely selecting an event does not.
  Maintenance **Ingest all** processes every event, not just the selected one.
  HDF5 download links use a separate FMI NutShell endpoint; availability can depend
  on the user's network. TOML export is catalog metadata, not radar imagery or a full
  database backup.

## Implementation conventions

- Organize new callbacks by feature and explicitly import their modules in
  [app.py](src/recall/app.py) so Dash registers them. Keep callbacks thin where practical;
  extract testable domain logic rather than adding more work to the entry point.
- Treat component IDs and `dcc.Store` payloads as interfaces. Update every producer
  and consumer together, including `events-update-signal` and `tag-update-signal`.
  Reuse AIO ID helpers (`component`, `subcomponent`, `aio_id`) and existing `MATCH`/`ALL`
  patterns. Preserve intentional `PreventUpdate`, initial-call, and duplicate-output behavior.
- Keep slow S3/raster work in Celery background callbacks, with meaningful progress and
  running-state feedback. Worker database access needs a Flask application context.
  Do not pass live ORM sessions between processes or store user state in module globals.
- Reuse [database/connection.py](src/recall/database/connection.py)'s shared `db`.
  Make transaction boundaries explicit; account for partial failures across the event
  database and Terracotta, since they do not share an atomic transaction.
- For new/touched code, favor clear names, small functions, useful type hints,
  parameterized SQLAlchemy queries, and public dependency APIs. Prefer modern
  SQLAlchemy select/session APIs over extending legacy `Query.get` usage.
  Existing private Terracotta calls and broad exception handlers are not patterns to copy.
- Catch specific expected errors, preserve diagnostic context, and surface failures
  through logging and appropriate UI feedback. Missing observations are not equivalent
  to successful ingestion; avoid success-shaped fallbacks and unbounded retries.
- Follow Black-style formatting without reformatting unrelated code. There is no
  configured formatter/linter pipeline yet. Add dependencies or tooling only when
  justified by the task, and document how to use them.
- App images use Python 3.12, but package metadata still declares Python >=3.8.
  Do not silently introduce a newer minimum; reconcile metadata/runtime support
  explicitly when modernizing. The tile-server image has a floating Python base.
- Dependency declarations are separate for the app and tile server. Coordinate
  Terracotta upgrades across both and check database compatibility; dependencies
  currently are not locked.

## Development and configuration

Run from the repository root with Podman and podman-compose available:

```sh
podman build -f Dockerfile.dev -t recall:dev .
podman-compose -f compose.yml -f compose.dev.yml up
```

Open `http://localhost:8050`. The development overlay mounts `./src` into both the
web and worker containers; the app is installed editable. Web code reloads, but
worker code does not:

```sh
podman-compose -f compose.yml -f compose.dev.yml restart celery_worker
podman-compose -f compose.yml -f compose.dev.yml logs --tail=100 web celery_worker terracotta
```

Rebuild affected images after dependency or Dockerfile changes; the source mount
does not install new dependencies. The `recall` entry point runs Dash in debug mode;
production uses `gunicorn recall.app:server`. Do not expose the debug server publicly.

| Variable | Consumer/purpose |
| --- | --- |
| `PREVENT_DB_URI` | Web/worker event database URI; the historical name is intentional |
| `TC_DB_URI` | App/worker Terracotta metadata driver |
| `TC_DRIVER_PATH` | Tile server's metadata database connection |
| `TC_URL` | Browser-reachable tile-server base URL |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Redis task queue and results |
| `TC_EXTRA_CMAP_FOLDER` | Colormaps shared through `/tmp/recall` |
| `AWS_NO_SIGN_REQUEST` | Unsigned public S3 raster access |

Compose service names are container-network addresses. `TC_URL` must resolve from
the **browser**; `localhost:8088` only works when the browser is on the serving host.
Use environment configuration rather than hardcoding deployment-specific hosts.
Optional commercial basemaps read `FMI_COMMERCIAL_API_KEY` from ignored
`src/recall/secrets.py`; without it, the app uses the default OpenStreetMap layer.
Never commit keys or expose them in logs, screenshots, or generated artifacts.
Do not assume ignored files are excluded from image or wheel builds.

## Persistence and migrations

- Curated events and tags are valuable. Never drop tables, remove volumes, reset
  databases, or run bulk writes against a shared deployment without explicit approval.
  Use disposable data for verification. Compose credentials are development defaults,
  not a production security configuration.
- Startup runs `db.create_all()`, seeds radars/tags, and adds a sample event if the
  event table is empty. That sample creation also performs ingestion/network I/O.
  Starting the UI is therefore not a read-only operation on a fresh database.
- `create_all()` does not migrate existing tables. Schema changes require reviewed,
  version-controlled Alembic revisions. See
  [database migration notes](docs/database-migrations.md), but treat reset recipes
  there as destructive procedures, not routine troubleshooting.
- With dependencies installed and database environment configured, run Flask commands
  from the repository root with an explicit app target, for example
  `flask --app recall.app:server db migrate -m "description"` and
  `flask --app recall.app:server db upgrade`. Check the actual database and migration
  history first: migration scaffolding exists, but no revisions are currently checked in.
  The dev overlay mounts only `src`, so migrations generated inside a container must
  be copied back or generated using an explicit migration-directory mount.
- Terracotta manages its own database format separately from Alembic. An upgrade can
  make existing metadata incompatible. Investigate version mismatches before rebuilding
  metadata; never reset the event database to repair the tile server.

## Validation and completion

Pytest unit tests live in `tests`; install `.[test]` and run
`python -m pytest -m 'not integration'`. There is not yet a CI workflow.
[pyproject.toml](pyproject.toml) includes a Hatch mypy environment and coverage settings,
but these are not evidence of a passing type-checking baseline. If Hatch is available,
`hatch run types:check src/recall` scopes the existing type command to actual sources
(pass explicit paths for targeted checks).

- Run the smallest relevant checks available. For behavior changes, add focused
  regression tests where feasible; if introducing the first test setup, keep it minimal
  and document the invocation. Separate pure unit tests from service-dependent tests.
- Useful test boundaries are timestamp generation, interval validation, S3/tile URL
  construction, product normalization, and export records. Mock network I/O in unit
  tests; use a disposable PostGIS database for spatial/ORM integration, not SQLite as
  an assumed equivalent.
- For UI changes, verify the affected workflow in the browser against a development
  stack: event selection, playback/scrubbing and timestamp agreement, map tiles/legend,
  form state, tag changes, and download/export as applicable. Exercise mutations only
  on disposable records; check worker logs and progress for background work.
- Check no-selection, empty/short intervals, unavailable scans/services, and stale
  selections when relevant. A successful page load alone does not validate Celery,
  persistence, or tile rendering.
- Documentation-only changes need link/command review and `git diff --check`, not a
  running stack. Finish with a concise summary of changes, checks performed, and any
  unverified behavior or environmental blockers. Do not claim checks that were not run.
