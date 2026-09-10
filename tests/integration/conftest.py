"""Destructive fixtures restricted to an explicitly selected disposable test DB."""

import os
from pathlib import Path

import pytest
from flask import Flask, current_app
from flask_migrate import Migrate, upgrade
from sqlalchemy import text
from sqlalchemy.engine import make_url

from recall.database.cli import register_commands
from recall.database.connection import db
from recall.database.models import Radar


MIGRATIONS = str(Path(__file__).resolve().parents[2] / "migrations")


def require_test_database(uri):
    url = make_url(uri)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith(
        "_test"
    ):
        raise ValueError(
            "RECALL_TEST_DB_URI must select a disposable PostgreSQL *_test database"
        )
    return url


def clean_test_tables():
    # Verify the connected server as well as the URI before destructive SQL.
    with db.engine.begin() as connection:
        database = connection.scalar(text("SELECT current_database()"))
        expected = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"]).database
        if database != expected or not database.endswith("_test"):
            raise ValueError(
                "Refusing to clear a database other than the explicit *_test DB"
            )
        connection.execute(
            text(
                'DROP TABLE IF EXISTS public.event_tag, public.tag_tag, public."event", '
                "public.tag, public.radar, public.alembic_version CASCADE"
            )
        )


@pytest.fixture
def db_app():
    uri = os.environ.get("RECALL_TEST_DB_URI")
    if not uri:
        pytest.skip(
            "Set RECALL_TEST_DB_URI to an isolated disposable PostGIS *_test database"
        )
    require_test_database(uri)
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
    db.init_app(app)
    Migrate(app, db, directory=MIGRATIONS)
    register_commands(app)
    with app.app_context():
        clean_test_tables()
        try:
            yield app
        finally:
            db.session.remove()
            clean_test_tables()
            db.engine.dispose()


@pytest.fixture
def migrated_db(db_app):
    upgrade(directory=MIGRATIONS)
    return db_app


@pytest.fixture
def radars(migrated_db):
    first = Radar(name="test-one", fmisid=1, location="SRID=4326;POINT(21 60)")
    second = Radar(name="test-two", fmisid=2, location="SRID=4326;POINT(22 61)")
    db.session.add_all([first, second])
    db.session.commit()
    return first, second
