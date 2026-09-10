"""Validate and restore the unversioned TOML catalog export, without raster I/O."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from recall.database.connection import db
from recall.database.models import Event, Radar, Tag
from recall.domain import EventValidationError, SCAN_INTERVAL, validate_event_interval


@dataclass(frozen=True)
class CatalogEvent:
    id: int
    radar: str
    start_time: datetime
    end_time: datetime
    description: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ImportResult:
    events: int
    new_tags: int
    scans: int
    already_present: bool = False


def parse_catalog(document: dict) -> list[CatalogEvent]:
    """Reject incomplete/ambiguous input before accessing a database."""
    if set(document) != {"event"} or not isinstance(document["event"], list):
        raise EventValidationError(
            "Expected a TOML catalog containing [[event]] records."
        )
    if not document["event"]:
        raise EventValidationError("The catalog contains no events.")
    records = []
    ids = set()
    fields = {"id", "radar", "start_time", "end_time", "description", "tags"}
    for position, record in enumerate(document["event"], 1):
        if not isinstance(record, dict) or set(record) != fields:
            raise EventValidationError(
                f"Record {position}: expected fields {sorted(fields)}."
            )
        event_id = record["id"]
        if type(event_id) is not int or not 0 < event_id < 2**31:
            raise EventValidationError(
                f"Record {position}: id must be a positive PostgreSQL integer."
            )
        if event_id in ids:
            raise EventValidationError(f"Duplicate event ID {event_id}.")
        ids.add(event_id)
        radar = record["radar"]
        if not isinstance(radar, str) or not radar or radar != radar.strip():
            raise EventValidationError(f"Event {event_id}: invalid radar identifier.")
        if not isinstance(record["description"], str):
            raise EventValidationError(f"Event {event_id}: description must be text.")
        tags = record["tags"]
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) or not tag.strip() or len(tag) > 255
            for tag in tags
        ):
            raise EventValidationError(
                f"Event {event_id}: tags must be nonempty names up to 255 characters."
            )
        if len(tags) != len(set(tags)):
            raise EventValidationError(f"Event {event_id}: duplicate tag names.")
        try:
            start, end = validate_event_interval(
                record["start_time"], record["end_time"]
            )
        except EventValidationError as exc:
            raise EventValidationError(f"Event {event_id}: {exc}") from exc
        records.append(
            CatalogEvent(
                event_id, radar, start, end, record["description"], tuple(sorted(tags))
            )
        )
    ordered = sorted(records, key=lambda record: (record.radar, record.start_time))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.radar == current.radar and current.start_time < previous.end_time:
            raise EventValidationError(
                f"Events {previous.id} and {current.id} overlap for radar {current.radar}."
            )
    return records


def _record(event: Event) -> CatalogEvent:
    return CatalogEvent(
        event.id,
        event.radar.name,
        event.start_time,
        event.end_time,
        event.description,
        tuple(sorted(tag.name for tag in event.tags)),
    )


def restore_catalog(
    records: list[CatalogEvent], *, dry_run: bool = False
) -> ImportResult:
    """Restore atomically into an empty catalog, or recognize an exact repeat."""
    scans = sum(
        (record.end_time - record.start_time) // SCAN_INTERVAL for record in records
    )
    try:
        # Serialize the empty-catalog check with writes; readers remain available.
        db.session.execute(text('LOCK TABLE "event", tag IN SHARE ROW EXCLUSIVE MODE'))
        existing = db.session.scalars(
            db.select(Event).options(
                selectinload(Event.tags), selectinload(Event.radar)
            )
        ).all()
        if existing:
            if {_record(event) for event in existing} == set(records):
                db.session.rollback()
                return ImportResult(len(records), 0, scans, already_present=True)
            raise EventValidationError(
                "The event catalog is not empty and does not exactly match this export. "
                "No records were changed; use a fresh database or review the difference."
            )
        radars = {radar.name: radar for radar in db.session.scalars(db.select(Radar))}
        unknown = {record.radar for record in records} - radars.keys()
        if unknown:
            raise EventValidationError(
                f"Unknown radars: {', '.join(sorted(unknown))}. Run seed or review the identifiers."
            )
        tags = {tag.name: tag for tag in db.session.scalars(db.select(Tag))}
        missing = {name for record in records for name in record.tags} - tags.keys()
        result = ImportResult(len(records), len(missing), scans)
        if dry_run:
            db.session.rollback()
            return result
        for name in sorted(missing):
            tags[name] = Tag(name=name, description="")
        db.session.add_all(
            [
                Event(
                    id=record.id,
                    radar=radars[record.radar],
                    start_time=record.start_time,
                    end_time=record.end_time,
                    description=record.description,
                    tags=[tags[name] for name in record.tags],
                )
                for record in records
            ]
        )
        db.session.flush()
        # Explicit imported IDs must not collide with subsequent ordinary inserts.
        # nextval also keeps an already-advanced sequence from moving backwards.
        db.session.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('event', 'id'), "
                "GREATEST((SELECT max(id) FROM event), "
                "nextval(pg_get_serial_sequence('event', 'id'))), true)"
            )
        )
        db.session.commit()
        return result
    except (EventValidationError, SQLAlchemyError):
        db.session.rollback()
        raise
