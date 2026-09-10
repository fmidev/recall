from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event as ThreadEvent

import pytest
from flask_migrate import downgrade, stamp, upgrade
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import IntegrityError

from recall.database.connection import db
from recall.database.models import Event, IngestionJob, Radar, Tag

from conftest import MIGRATIONS, require_test_database


pytestmark = pytest.mark.integration
START = datetime(2024, 1, 1, 12)


def make_event(radar, start=0, end=30):
    return Event(
        radar=radar,
        start_time=START + timedelta(minutes=start),
        end_time=START + timedelta(minutes=end),
    )


@pytest.mark.parametrize(
    "uri",
    [
        "postgresql://localhost/recall",
        "postgresql://localhost/",
        "sqlite:///recall_test",
    ],
)
def test_fixture_refuses_unsafe_database(uri):
    with pytest.raises(ValueError, match="disposable PostgreSQL"):
        require_test_database(uri)


def test_migrate_blank_database_without_implicit_seed(migrated_db):
    assert (
        db.session.scalar(text("SELECT version_num FROM alembic_version"))
        == "0003_ingestion_jobs"
    )
    for model in (Event, IngestionJob, Radar, Tag):
        assert db.session.scalar(db.select(func.count()).select_from(model)) == 0
    checks = inspect(db.engine).get_check_constraints("event")
    assert {check["name"] for check in checks} == {
        "event_positive_interval",
        "event_five_minute_alignment",
    }
    assert (
        db.session.scalar(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conname = 'event_radar_no_overlap' AND contype = 'x'"
            )
        )
        == 1
    )


def test_seed_idempotence_preserves_curated_values(migrated_db):
    runner = migrated_db.test_cli_runner()
    assert runner.invoke(args=["seed"]).exit_code == 0
    radar = db.session.scalar(db.select(Radar).where(Radar.name == "fikor"))
    tag = db.session.scalar(db.select(Tag).where(Tag.name == "rain"))
    radar.description = "Curated radar description"
    tag.description = "Curated tag description"
    db.session.commit()
    assert runner.invoke(args=["seed"]).exit_code == 0
    db.session.expire_all()
    assert radar.description == "Curated radar description"
    assert tag.description == "Curated tag description"
    assert db.session.scalar(db.select(func.count()).select_from(Radar)) == 11
    assert db.session.scalar(db.select(func.count()).select_from(Tag)) == 6
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 0
    assert db.session.scalar(
        text("SELECT ST_X(location::geometry) FROM radar WHERE name = 'fikor'")
    ) == pytest.approx(21.643379)
    assert db.session.scalar(
        text("SELECT ST_Y(location::geometry) FROM radar WHERE name = 'fikor'")
    ) == pytest.approx(60.128469)


def test_seed_identifier_conflict_rolls_back(migrated_db):
    db.session.add(
        Radar(name="custom", fmisid=100926, location="SRID=4326;POINT(21 60)")
    )
    db.session.commit()
    result = migrated_db.test_cli_runner().invoke(args=["seed"])
    assert result.exit_code != 0
    assert "no seed changes were committed" in result.output
    assert db.session.scalar(db.select(func.count()).select_from(Radar)) == 1
    assert db.session.scalar(db.select(func.count()).select_from(Tag)) == 0


def test_unversioned_baseline_requires_verification_and_manual_stamp(db_app):
    upgrade(directory=MIGRATIONS, revision="0001_initial")
    db.session.execute(text("DELETE FROM alembic_version"))
    db.session.commit()
    result = db_app.test_cli_runner().invoke(args=["verify-baseline"])
    assert result.exit_code == 0, result.output
    assert "no changes made" in result.output
    assert db.session.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    db.session.commit()
    stamp(directory=MIGRATIONS, revision="0001_initial")
    upgrade(directory=MIGRATIONS)
    assert (
        db.session.scalar(text("SELECT version_num FROM alembic_version"))
        == "0003_ingestion_jobs"
    )


@pytest.mark.parametrize(
    "change, message",
    [
        (
            "ALTER TABLE event ALTER COLUMN start_time TYPE timestamp with time zone",
            "event: columns differ",
        ),
        (
            "ALTER TABLE tag DROP CONSTRAINT tag_name_key",
            "tag: unique constraints differ",
        ),
        ("DROP INDEX idx_radar_location", "radar.location: missing GiST spatial index"),
        (
            "ALTER TABLE event ALTER CONSTRAINT event_radar_id_fkey DEFERRABLE",
            "event: foreign keys or their actions differ",
        ),
        ("DROP TABLE event_tag", "event_tag: missing table"),
    ],
)
def test_baseline_rejects_schema_drift(db_app, change, message):
    upgrade(directory=MIGRATIONS, revision="0001_initial")
    db.session.execute(text("DELETE FROM alembic_version"))
    db.session.execute(text(change))
    db.session.commit()
    result = db_app.test_cli_runner().invoke(args=["verify-baseline"])
    assert result.exit_code != 0
    assert message in result.output
    assert db.session.scalar(text("SELECT count(*) FROM alembic_version")) == 0


def test_create_all_has_no_implicit_seed_hooks(db_app):
    with db.engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    db.create_all()
    for model in (Event, IngestionJob, Radar, Tag):
        assert db.session.scalar(db.select(func.count()).select_from(model)) == 0
    assert not db.session.new


def test_migration_reports_invalid_records_without_changing_them(db_app, capsys):
    upgrade(directory=MIGRATIONS, revision="0001_initial")
    radar = Radar(name="test", fmisid=1, location="SRID=4326;POINT(21 60)")
    invalid = make_event(radar, start=1, end=0)
    first, contained = make_event(radar), make_event(radar, start=5, end=10)
    db.session.add_all([invalid, first, contained])
    db.session.commit()
    invalid_id, first_id, contained_id = invalid.id, first.id, contained.id
    db.session.remove()
    with pytest.raises(SystemExit) as error:
        upgrade(directory=MIGRATIONS)
    assert error.value.code == 1
    output = capsys.readouterr().err
    assert "no curated data was changed" in output
    assert f"Invalid event IDs: [{invalid_id}]" in output
    assert f"({first_id}, {contained_id})" in output
    assert (
        db.session.scalar(text("SELECT version_num FROM alembic_version"))
        == "0001_initial"
    )
    assert db.session.get(Event, invalid_id).start_time == START + timedelta(minutes=1)
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 3


@pytest.mark.parametrize(
    ("start", "end", "constraint"),
    [
        (START, START, "event_positive_interval"),
        (START, START - timedelta(minutes=5), "event_positive_interval"),
        (
            START + timedelta(minutes=1),
            START + timedelta(minutes=30),
            "event_five_minute_alignment",
        ),
        (START, START + timedelta(minutes=31), "event_five_minute_alignment"),
        (
            START + timedelta(seconds=1),
            START + timedelta(minutes=30),
            "event_five_minute_alignment",
        ),
        (
            START,
            START + timedelta(minutes=30, microseconds=1),
            "event_five_minute_alignment",
        ),
    ],
)
def test_interval_checks(radars, start, end, constraint):
    db.session.add(Event(radar=radars[0], start_time=start, end_time=end))
    with pytest.raises(IntegrityError) as error:
        db.session.commit()
    assert error.value.orig.diag.constraint_name == constraint
    db.session.rollback()
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 0


@pytest.mark.parametrize("start,end", [(5, 10), (-5, 35), (-5, 5), (25, 35), (0, 30)])
def test_overlap_constraint_including_containment(radars, start, end):
    db.session.add(make_event(radars[0]))
    db.session.commit()
    db.session.add(make_event(radars[0], start, end))
    with pytest.raises(IntegrityError) as error:
        db.session.commit()
    assert error.value.orig.diag.constraint_name == "event_radar_no_overlap"
    db.session.rollback()


def test_adjacency_cross_radar_and_update_excluding_self(radars):
    first = make_event(radars[0])
    following = make_event(radars[0], 30, 60)
    db.session.add_all([first, following, make_event(radars[1])])
    db.session.commit()
    first.description = "Edited"
    first.end_time = START + timedelta(minutes=25)
    db.session.commit()
    assert first.description == "Edited"
    first.end_time = START + timedelta(minutes=35)
    with pytest.raises(IntegrityError) as error:
        db.session.commit()
    assert error.value.orig.diag.constraint_name == "event_radar_no_overlap"
    db.session.rollback()


def test_concurrent_overlap_is_rejected(radars):
    radar_id = radars[0].id
    db.session.remove()
    started = ThreadEvent()
    statement = text(
        "INSERT INTO event (radar_id, start_time, end_time) VALUES (:radar, :start, :end)"
    )
    values = {"radar": radar_id, "start": START, "end": START + timedelta(minutes=30)}
    engine = db.engine

    def insert_competing_event():
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            started.set()
            connection.execute(statement, values)

    with engine.connect() as connection, ThreadPoolExecutor(max_workers=1) as executor:
        transaction = connection.begin()
        try:
            connection.execute(statement, values)
            future = executor.submit(insert_competing_event)
            assert started.wait(5)
            transaction.commit()
            with pytest.raises(IntegrityError) as error:
                future.result(timeout=10)
            assert error.value.orig.diag.constraint_name == "event_radar_no_overlap"
        finally:
            if transaction.is_active:
                transaction.rollback()
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 1


def test_query_overlap_excludes_self_and_accepts_adjacent_and_other_radar(radars):
    from recall.database.queries import event_overlaps_existing

    existing = make_event(radars[0])
    db.session.add(existing)
    db.session.commit()
    assert not event_overlaps_existing(db, existing)
    assert not event_overlaps_existing(db, make_event(radars[0], 30, 60))
    assert not event_overlaps_existing(db, make_event(radars[1]))
    assert event_overlaps_existing(db, make_event(radars[0], 5, 10))
    assert event_overlaps_existing(db, make_event(radars[0], -5, 35))


def test_downgrade_only_removes_interval_constraints(radars):
    db.session.add(make_event(radars[0]))
    db.session.commit()
    db.session.remove()
    downgrade(directory=MIGRATIONS, revision="0001_initial")
    assert db.session.scalar(db.select(func.count()).select_from(Event)) == 1
    assert inspect(db.engine).get_check_constraints("event") == []
    db.session.remove()
    upgrade(directory=MIGRATIONS)
