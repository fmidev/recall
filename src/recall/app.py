"""Dash app for visualizing radar case studies."""

import os

import click
import dash_bootstrap_components as dbc
from celery import Celery
from dash import CeleryManager, Dash
from flask_migrate import Migrate

from recall.database.connection import db
from recall.database.cli import register_commands
from recall.layout import create_layout
from recall.terracotta.ingest import get_driver, KEYS, KEY_DESCRIPTIONS
from recall.tasks import register_tasks
import recall.callbacks.events  # noqa: F401
import recall.callbacks.tags  # noqa: F401
import recall.callbacks.map  # noqa: F401
import recall.callbacks.maintenance  # noqa: F401
import recall.callbacks.ingestion  # noqa: F401


def create_app(config=None):
    celery_app = Celery(
        __name__,
        broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    )
    app = Dash(
        __name__,
        title="Recall",
        background_callback_manager=CeleryManager(celery_app),
        external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
    )
    server = app.server
    server.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "PREVENT_DB_URI", "postgresql://localhost/recall"
    )
    if config:
        server.config.update(config)
    db.init_app(server)
    celery_app.conf.broker_connection_timeout = 3
    register_tasks(celery_app, server)
    migrate = Migrate(server, db)
    register_commands(server)

    @server.cli.command("init-tiles")
    def init_tiles():
        """Create a new Terracotta database; never reset an existing database."""
        get_driver().create(KEYS, key_descriptions=KEY_DESCRIPTIONS)
        click.echo("Terracotta database created.")

    app.layout = create_layout()
    return app, server, celery_app, migrate


app, server, celery_app, migrate = create_app()


def main(**kws):
    """Run the development server; production uses Gunicorn."""
    app.run(debug=True, host="0.0.0.0", port=8050, **kws)


if __name__ == "__main__":
    main()
