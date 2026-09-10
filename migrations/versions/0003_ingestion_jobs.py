"""Keep imagery preparation history independently of Celery and the catalog."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_ingestion_jobs"
down_revision = "0002_event_intervals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshots", JSONB, nullable=False),
        sa.Column("results", JSONB, nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'ready', 'partial', 'failed')",
            name="ingestion_job_status",
        ),
        sa.CheckConstraint(
            "completed >= 0 AND total >= completed", name="ingestion_job_progress"
        ),
    )
    op.create_index("ix_ingestion_job_status", "ingestion_job", ["status"])
    op.create_index("ix_ingestion_job_created_at", "ingestion_job", ["created_at"])


def downgrade():
    op.drop_table("ingestion_job")
