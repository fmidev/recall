"""Baseline the schema previously created by SQLAlchemy create_all.

Revision ID: 0001_initial
Revises:
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "radar",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fmisid", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(10), nullable=False, unique=True),
        sa.Column(
            "location", Geography(geometry_type="POINT", srid=4326), nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_table(
        "event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("radar_id", sa.Integer(), sa.ForeignKey("radar.id"), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=False), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=False), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_table(
        "event_tag",
        sa.Column(
            "event_id", sa.Integer(), sa.ForeignKey("event.id"), primary_key=True
        ),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tag.id"), primary_key=True),
    )
    op.create_table(
        "tag_tag",
        sa.Column(
            "parent_tag_id", sa.Integer(), sa.ForeignKey("tag.id"), primary_key=True
        ),
        sa.Column(
            "child_tag_id", sa.Integer(), sa.ForeignKey("tag.id"), primary_key=True
        ),
    )


def downgrade():
    op.drop_table("tag_tag")
    op.drop_table("event_tag")
    op.drop_table("event")
    op.drop_table("tag")
    op.drop_table("radar")
    # Extensions may be used by other objects; leave them installed.
