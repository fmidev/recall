# RECALL - Copilot Instructions

## Architecture Overview

RECALL is a **Plotly Dash** web application for browsing weather radar precipitation events. The app uses a **multi-container architecture**:

- **web**: Dash app serving the UI (port 8050)
- **celery_worker**: Handles background callbacks (long-running tasks)
- **terracotta**: Tile server for radar GeoTIFF imagery (port 8088)
- **db**: PostGIS database with two schemas: `recalldb` (events) and `terracotta` (raster metadata)
- **redis**: Celery message broker

Data flows: UI → Dash callbacks → PostgreSQL (events/tags) + Terracotta API (radar tiles from FMI S3)

## Project Structure

```
src/recall/
├── app.py           # Dash app factory, Celery setup, some callbacks
├── layout.py        # UI layout definition (Dash Bootstrap Components)
├── aios.py          # All-in-One Components (e.g., PlaybackSliderAIO)
├── callbacks/       # Callback modules auto-imported in app.py
│   ├── events.py    # Event CRUD, dropdown population
│   ├── tags.py      # Tag management with pattern-matching callbacks
│   ├── map.py       # dash-leaflet map updates, radar layer rendering
│   └── maintenance.py
├── database/
│   ├── models.py    # SQLAlchemy models: Event, Tag, Radar (with GeoAlchemy2)
│   ├── queries.py   # Database operations, event validation
│   └── connection.py
└── terracotta/
    ├── client.py    # Terracotta XYZ tile URL builder
    └── ingest.py    # S3 → Terracotta metadata ingestion
```

## Key Patterns

### Callbacks
- Callbacks are **organized by feature** in `src/recall/callbacks/` and imported via `import recall.callbacks.events  # noqa: F401` in `app.py`
- **Background callbacks** use Celery via `background=True` parameter; these run in the `celery_worker` container
- Pattern-matching callbacks use `MATCH`/`ALL` for dynamic components (see `tags.py`)
- Use `dcc.Store` for inter-callback signals (e.g., `events-update-signal`, `tag-update-signal`)

### All-in-One Components (AIOs)
- Encapsulate component + callbacks together (see `aios.py` for `PlaybackSliderAIO`)
- Use dict-based IDs: `{'component': 'Name', 'subcomponent': 'part', 'aio_id': id}`

### Database
- Flask-SQLAlchemy + Flask-Migrate (Alembic) for ORM and migrations
- GeoAlchemy2 for spatial data (`Geography` type for radar locations)
- Initial data seeded via SQLAlchemy `@event.listens_for` hooks in `models.py`
- Access pattern: `db.session.query(Model)` within Flask app context

### Environment Variables
| Variable | Purpose |
|----------|---------|
| `PREVENT_DB_URI` | PostgreSQL connection for events DB |
| `TC_DB_URI` | PostgreSQL connection for Terracotta |
| `TC_URL` | Terracotta server URL |
| `CELERY_BROKER_URL` | Redis broker |

## Development Workflow

```bash
# Build dev image (hot-reload enabled)
podman build -f Dockerfile.dev -t recall:dev .

# Run dev stack (mounts ./src for live changes)
podman-compose -f compose.yml -f compose.dev.yml up

# Background callback changes require celery_worker restart
podman-compose restart celery_worker
```

- Dev mode enables `DASH_DEBUG=true` for Dash debug tools
- The UI runs at http://localhost:8050

It may take 10-20 seconds to stop all containers cleanly with `podman-compose down`.

## Database Migrations

```bash
# Inside web container or with Flask context
flask db migrate -m "description"
flask db upgrade
```

## Code Style

- Follow **Black** formatting style
- No CI/CD currently; local development only (may deploy to FMI intranet later)
- Tests will go in `tests/` (not yet implemented)

## External Dependencies

- **FMI Open Data S3** (`s3://fmi-opendata-radar-geotiff`): Public radar GeoTIFFs, unsigned requests
- **Terracotta**: Ingests S3 paths, serves XYZ tiles with colormaps

### Optional: Premium Basemaps

For FMI commercial basemaps, create `src/recall/secrets.py`:

```python
FMI_COMMERCIAL_API_KEY = "your-api-key-here"
```

This enables WMS layers from `wms.fmi.fi` instead of the default OpenStreetMap tiles.
