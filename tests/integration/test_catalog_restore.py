from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from recall.database.catalog import CatalogEvent, restore_catalog
from recall.database.connection import db
from recall.database.models import Event, Tag
from recall.database.queries import save_event
from recall.domain import EventValidationError


pytestmark = pytest.mark.integration


@pytest.fixture
def records(radars):
    return [
        CatalogEvent(
            21,
            radars[0].name,
            datetime(2023, 8, 28, 10),
            datetime(2023, 8, 28, 11),
            "Preserve this description",
            ("new tag", "rain"),
        ),
        CatalogEvent(
            5,
            radars[1].name,
            datetime(2023, 8, 28, 10),
            datetime(2023, 8, 28, 11),
            "",
            (),
        ),
    ]


def test_restore_preserves_ids_and_reuses_named_tags(records):
    tag = Tag(name="rain", description="Preserve tag description")
    db.session.add(tag)
    db.session.commit()
    result = restore_catalog(records)
    assert (result.events, result.new_tags, result.scans) == (2, 1, 24)
    event = db.session.get(Event, 21)
    assert event.description == records[0].description
    assert event.start_time == records[0].start_time
    assert {tag.name for tag in event.tags} == {"rain", "new tag"}
    assert tag.description == "Preserve tag description"
    assert db.session.get(Event, 5).description == ""
    radar_id = event.radar_id
    later, _ = save_event(
        radar_id, datetime(2023, 8, 28, 11), datetime(2023, 8, 28, 12), "Later", []
    )
    assert later.id > 21


def test_dry_run_does_not_write_events_or_tags(records):
    assert restore_catalog(records, dry_run=True).events == 2
    assert db.session.scalar(db.select(db.func.count()).select_from(Event)) == 0
    assert db.session.scalar(db.select(db.func.count()).select_from(Tag)) == 0


def test_identical_repeat_is_read_only(records):
    restore_catalog(records)
    assert restore_catalog(records).already_present
    assert db.session.scalar(db.select(db.func.count()).select_from(Event)) == 2


def test_conflicting_catalog_is_not_overwritten(records):
    restore_catalog(records)
    changed = [replace(records[0], description="Different"), records[1]]
    with pytest.raises(EventValidationError, match="does not exactly match"):
        restore_catalog(changed)
    assert db.session.get(Event, 21).description == "Preserve this description"


def test_unknown_radar_aborts_without_writing(records):
    records[1] = replace(records[1], radar="missing-radar")
    with pytest.raises(EventValidationError, match="Unknown radars"):
        restore_catalog(records)
    assert db.session.scalar(db.select(db.func.count()).select_from(Event)) == 0
    assert db.session.scalar(db.select(db.func.count()).select_from(Tag)) == 0


def test_database_failure_rolls_back_new_tags_and_all_events(records):
    records[1] = replace(records[1], end_time=records[1].start_time)
    with pytest.raises(IntegrityError):
        restore_catalog(records)
    assert db.session.scalar(db.select(db.func.count()).select_from(Event)) == 0
    assert db.session.scalar(db.select(db.func.count()).select_from(Tag)) == 0


def test_import_cli_accepts_toml_and_reports_dry_run(migrated_db, tmp_path):
    assert migrated_db.test_cli_runner().invoke(args=["seed"]).exit_code == 0
    catalog = tmp_path / "events.toml"
    catalog.write_text(
        '[[event]]\nid = 21\nradar = "fikor"\n'
        "start_time = 2023-08-28T10:00:00\nend_time = 2023-08-28T10:05:00\n"
        'description = "Case"\ntags = ["new tag"]\n',
        encoding="utf-8",
    )
    runner = migrated_db.test_cli_runner()
    preview = runner.invoke(args=["import-events", str(catalog), "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert "Would import 1 events and 1 new tags (1 expected scans)" in preview.output
    assert db.session.get(Event, 21) is None
    restored = runner.invoke(args=["import-events", str(catalog)])
    assert restored.exit_code == 0, restored.output
    assert "Imported 1 events" in restored.output
    assert db.session.get(Event, 21).description == "Case"
