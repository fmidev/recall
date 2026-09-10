"""Explicit, local-only database administration commands."""

import click
from flask.cli import with_appcontext
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from recall.database.connection import db
from recall.database.models import Radar, Tag


RADARS = (
    ("fikor", 100926, "21.643379 60.128469", "Korppoo"),
    ("fivih", 107275, "24.49558603 60.5561915", "Vihti"),
    ("fivim", 101518, "23.82086 63.104835", "Vimpeli"),
    ("fiuta", 101872, "26.318877 64.774934", "Utajärvi"),
    ("filuo", 101939, "26.896916 67.139096", "Luosto"),
    ("finur", 107131, "29.44892 63.83786", "Nurmes"),
    ("fikuo", 101582, "27.381468 62.862598", "Kuopio"),
    ("fikes", 100690, "29.79772 61.90699", "Kesälahti"),
    ("fikan", 107307, "22.50204 61.81085", "Kankaanpää"),
    ("fipet", 103813, "25.44008118 62.30451365", "Petäjävesi"),
    ("fianj", 101234, "27.108057 60.903871", "Anjalankoski"),
)
TAGS = (
    (
        "squall line",
        "A line of thunderstorms that can form along and/or ahead of a cold front.",
    ),
    (
        "rain",
        "Precipitation in the form of liquid water drops with diameters "
        "greater than 0.5 millimetres.",
    ),
    (
        "convective",
        "A type of weather system that is characterized by vertical motion.",
    ),
    (
        "stratiform",
        "A broad shield of precipitation with a relatively similar intensity.",
    ),
    ("doppler snake", "A doppler filter artifact."),
    ("melting", "Melting layer signature."),
)


@click.command("seed")
@with_appcontext
def seed():
    """Insert missing radar/basic-tag records without replacing existing values."""
    try:
        db.session.execute(
            insert(Radar)
            .values(
                [
                    dict(
                        name=name,
                        fmisid=fmisid,
                        location=f"SRID=4326;POINT({coords})",
                        description=description,
                    )
                    for name, fmisid, coords, description in RADARS
                ]
            )
            .on_conflict_do_nothing(index_elements=["name"])
        )
        db.session.execute(
            insert(Tag)
            .values(
                [dict(name=name, description=description) for name, description in TAGS]
            )
            .on_conflict_do_nothing(index_elements=["name"])
        )
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise click.ClickException(
            "Seed conflicts with existing identifiers; no seed changes were committed. "
            "Review existing radar names/FMISIDs before retrying."
        ) from error
    click.echo("Missing radars and basic tags seeded; existing values preserved.")


# Freeze the legacy schema rather than compare against evolving ORM metadata.
BASELINE_COLUMNS = {
    "radar": {
        "id": ("integer", False),
        "fmisid": ("integer", False),
        "name": ("character varying(10)", False),
        "location": ("geography(Point,4326)", False),
        "description": ("text", True),
    },
    "tag": {
        "id": ("integer", False),
        "name": ("character varying(255)", False),
        "description": ("text", True),
    },
    "event": {
        "id": ("integer", False),
        "radar_id": ("integer", False),
        "start_time": ("timestamp without time zone", False),
        "end_time": ("timestamp without time zone", False),
        "description": ("text", True),
    },
    "event_tag": {"event_id": ("integer", False), "tag_id": ("integer", False)},
    "tag_tag": {
        "parent_tag_id": ("integer", False),
        "child_tag_id": ("integer", False),
    },
}
BASELINE_KEYS = {
    "radar": (("id",), {("name",), ("fmisid",)}, set()),
    "tag": (("id",), {("name",)}, set()),
    "event": (("id",), set(), {("radar_id", "radar", "id")}),
    "event_tag": (
        ("event_id", "tag_id"),
        set(),
        {("event_id", "event", "id"), ("tag_id", "tag", "id")},
    ),
    "tag_tag": (
        ("parent_tag_id", "child_tag_id"),
        set(),
        {("parent_tag_id", "tag", "id"), ("child_tag_id", "tag", "id")},
    ),
}


def baseline_schema_errors(connection):
    """Return structural differences from revision 0001; never write or stamp."""
    inspector = inspect(connection)
    if connection.scalar(text("SELECT current_schema()")) != "public":
        return ["Expected the application tables in the public schema."]
    tables = set(inspector.get_table_names(schema="public"))
    if "alembic_version" in tables and connection.scalar(
        text("SELECT count(*) FROM public.alembic_version")
    ):
        return ["Database already has an Alembic revision; inspect db current/history."]
    errors = []
    for table, expected_columns in BASELINE_COLUMNS.items():
        if table not in tables:
            errors.append(f"{table}: missing table")
            continue
        columns = (
            connection.execute(
                text(
                    "SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS type, "
                    "NOT a.attnotnull AS nullable, "
                    "pg_get_expr(d.adbin, d.adrelid) AS default_value "
                    "FROM pg_attribute a "
                    "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid "
                    "AND d.adnum = a.attnum "
                    "WHERE a.attrelid = to_regclass(:table) "
                    "AND a.attnum > 0 AND NOT a.attisdropped"
                ),
                {"table": f"public.{table}"},
            )
            .mappings()
            .all()
        )
        actual = {c["attname"]: (c["type"], c["nullable"]) for c in columns}
        if actual != expected_columns:
            errors.append(f"{table}: columns differ: {actual!r}")
        for c in columns:
            default = c["default_value"]
            if c["attname"] == "id":
                if not default or not default.startswith("nextval("):
                    errors.append(f"{table}.id: expected a serial sequence default")
            elif default is not None:
                errors.append(f"{table}.{c['attname']}: unexpected default {default}")
        primary, unique, foreign = BASELINE_KEYS[table]
        if tuple(inspector.get_pk_constraint(table)["constrained_columns"]) != primary:
            errors.append(f"{table}: primary key differs")
        actual_unique = {
            tuple(c["column_names"]) for c in inspector.get_unique_constraints(table)
        }
        if actual_unique != unique:
            errors.append(f"{table}: unique constraints differ")
        foreign_keys = inspector.get_foreign_keys(table)
        actual_foreign = {
            (
                tuple(c["constrained_columns"]),
                c["referred_table"],
                tuple(c["referred_columns"]),
            )
            for c in foreign_keys
        }
        expected_foreign = {
            ((local,), target, (remote,)) for local, target, remote in foreign
        }
        if actual_foreign != expected_foreign or any(
            c["options"] or c["referred_schema"] not in (None, "public")
            for c in foreign_keys
        ):
            errors.append(f"{table}: foreign keys or their actions differ")
        if connection.scalar(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = to_regclass(:table) AND contype IN ('c', 'x')"
            ),
            {"table": f"public.{table}"},
        ):
            errors.append(f"{table}: unexpected check/exclusion constraints")
        if connection.scalar(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = to_regclass(:table) "
                "AND (NOT convalidated OR condeferrable)"
            ),
            {"table": f"public.{table}"},
        ):
            errors.append(f"{table}: unvalidated or deferrable constraints")
    if "radar" in tables and not any(
        index["column_names"] == ["location"]
        and index["dialect_options"].get("postgresql_using") == "gist"
        for index in inspector.get_indexes("radar")
    ):
        errors.append("radar.location: missing GiST spatial index")
    return errors


@click.command("verify-baseline")
@with_appcontext
def verify_baseline():
    """Read-only check before an operator manually stamps a legacy database."""
    with db.engine.connect() as connection:
        errors = baseline_schema_errors(connection)
    if errors:
        raise click.ClickException("Baseline mismatch:\n" + "\n".join(errors))
    click.echo(
        "Schema matches 0001_initial; no changes made. After backup and review, "
        "manually run db stamp 0001_initial, then db upgrade."
    )


def register_commands(server):
    """Register database maintenance commands on the Flask server."""
    server.cli.add_command(seed)
    server.cli.add_command(verify_baseline)
