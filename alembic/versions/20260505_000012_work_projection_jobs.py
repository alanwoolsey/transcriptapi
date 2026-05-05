"""add work projection jobs table

Revision ID: 20260505_000012
Revises: 20260505_000011
Create Date: 2026-05-05 12:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260505_000012"
down_revision: Union[str, None] = "20260505_000011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_projection_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("reset_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("processed_students", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("remaining_students", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_cursor", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_work_projection_jobs_tenant_created_desc", "work_projection_jobs", ["tenant_id", sa.text("created_at DESC")])
    op.create_index("ix_work_projection_jobs_tenant_status", "work_projection_jobs", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_work_projection_jobs_tenant_status", table_name="work_projection_jobs")
    op.drop_index("ix_work_projection_jobs_tenant_created_desc", table_name="work_projection_jobs")
    op.drop_table("work_projection_jobs")
