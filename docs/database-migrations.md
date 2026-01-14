# Database Migrations

RECALL uses two databases that may require migrations:

1. **recalldb** (PostgreSQL) - Events, tags, and application data (managed by Flask-Migrate/Alembic)
2. **terracotta** (PostgreSQL) - Radar raster metadata (managed by Terracotta)

## Flask-Migrate (recalldb)

The `recalldb` schema is managed with Flask-Migrate (Alembic). Migrations are stored in `migrations/versions/`.

```bash
# Inside the web container or with Flask context
flask db migrate -m "description"  # Generate migration
flask db upgrade                   # Apply migrations
flask db downgrade                 # Rollback one migration
```

## Terracotta Database

Terracotta does **not** provide automatic migrations between versions. If you upgrade Terracotta and see this error:

```
terracotta.exceptions.InvalidDatabaseError: Version conflict: database was created in v0.8.5, but this is v0.10.0
```

You have two options:

### Option 1: Drop and Re-ingest (Recommended)

Drop the Terracotta tables and let the new version recreate them:

```bash
# Drop old Terracotta tables
podman-compose exec db psql -U postgres -d terracotta -c \
  "DROP TABLE IF EXISTS datasets CASCADE; DROP TABLE IF EXISTS keys CASCADE; DROP TABLE IF EXISTS metadata CASCADE; DROP TABLE IF EXISTS key_names CASCADE; DROP TABLE IF EXISTS terracotta CASCADE;"

# Restart Terracotta to recreate tables with new schema
podman-compose restart terracotta
```

After this, the database is empty. Re-ingest radar data using either:

- **UI**: Use the "Ingest all" button in the Maintenance section to ingest all radar data for the currently selected event
- **On-demand**: Data is automatically ingested when you view an event

### Option 2: Pin Terracotta Version

If you need to preserve existing data, pin the version in `terracotta/requirements.txt`:

```
terracotta==0.8.5
```

Then rebuild the image:

```bash
podman-compose build terracotta
podman-compose up -d terracotta
```

This is not recommended long-term as you won't receive updates.

## Full Database Reset

To completely reset all databases (useful for development):

```bash
# Stop all containers
podman-compose down

# Remove the database volume
podman volume rm recall_db_data

# Restart (databases will be recreated)
podman-compose up -d
```

Note: This removes all events, tags, and ingested radar metadata.
