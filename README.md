# RECALL - Radar Event Catalog and Archive Lookup Library

Simple web application to browse precipitation events and related weather radar data.

The events are tagged for interesting features, such as hail, birds, or heavy attenuation.
Events can be filtered by tags (not yet implemented). A radar animation is shown for each event.

## Deployment

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

## Tests

Install the project and its test dependencies in a virtual environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -m 'not integration'
```

Unit tests do not need the running stack or network access.
