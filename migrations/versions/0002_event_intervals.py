"""Enforce aligned, positive, radar-specific half-open event intervals.

Revision ID: 0002_event_intervals
Revises: 0001_initial
"""

from alembic import context, op
import sqlalchemy as sa

revision = "0002_event_intervals"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

ALIGNMENT = (
    "date_trunc('minute', start_time) = start_time "
    "AND extract(minute FROM start_time)::integer % 5 = 0 "
    "AND date_trunc('minute', end_time) = end_time "
    "AND extract(minute FROM end_time)::integer % 5 = 0"
)


def upgrade():
    if context.is_offline_mode():
        raise RuntimeError("This migration requires an online legacy-data audit.")
    connection = op.get_bind()
    # Hold the audit and DDL in one transaction without concurrent event writes.
    op.execute('LOCK TABLE "event" IN ACCESS EXCLUSIVE MODE')
    invalid = (
        connection.execute(
            sa.text(
                'SELECT id FROM "event" WHERE NOT (end_time > start_time AND '
                + ALIGNMENT
                + ") ORDER BY id"
            )
        )
        .scalars()
        .all()
    )
    overlaps = connection.execute(
        sa.text(
            'SELECT a.id, b.id FROM "event" a JOIN "event" b '
            "ON a.id < b.id AND a.radar_id = b.radar_id "
            "AND a.start_time < b.end_time AND b.start_time < a.end_time "
            "ORDER BY a.id, b.id"
        )
    ).all()
    if invalid or overlaps:
        raise RuntimeError(
            "Cannot enforce event intervals; no curated data was changed. "
            f"Invalid event IDs: {invalid}. Overlapping event ID pairs: "
            f"{[tuple(pair) for pair in overlaps]}. "
            "Review and correct these records explicitly, then retry db upgrade."
        )
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_check_constraint(
        "event_positive_interval", "event", "end_time > start_time"
    )
    op.create_check_constraint("event_five_minute_alignment", "event", ALIGNMENT)
    op.execute(
        'ALTER TABLE "event" ADD CONSTRAINT event_radar_no_overlap '
        "EXCLUDE USING gist "
        "(radar_id WITH =, tsrange(start_time, end_time, '[)') WITH &&)"
    )


def downgrade():
    op.drop_constraint("event_radar_no_overlap", "event")
    op.drop_constraint("event_five_minute_alignment", "event", type_="check")
    op.drop_constraint("event_positive_interval", "event", type_="check")
