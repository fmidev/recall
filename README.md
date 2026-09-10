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

## Event times

Event times are UTC and must fall on five-minute boundaries. Intervals include the
start and exclude the end, so adjacent events may share a boundary but not a scan.
The end must be later than the start. Overlapping events for the same radar are
rejected. Times are not silently rounded.

## Tests

Install the project and its test dependencies in a virtual environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -m 'not integration'
```

Unit tests do not need the running stack or network access.
