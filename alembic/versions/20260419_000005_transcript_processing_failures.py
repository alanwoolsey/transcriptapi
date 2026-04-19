"""transcript processing failures

Revision ID: 20260419_000005
Revises: 20260419_000004
Create Date: 2026-04-19 17:25:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260419_000005"
down_revision: Union[str, None] = "20260419_000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transcript_processing_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_uploads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("failure_code", sa.Text(), nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=False),
        sa.Column("failure_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_transcript_processing_failures_tenant_created_at",
        "transcript_processing_failures",
        [sa.text("tenant_id"), sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_transcript_processing_failures_tenant_code_created_at",
        "transcript_processing_failures",
        [sa.text("tenant_id"), sa.text("failure_code"), sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_processing_failures_tenant_code_created_at", table_name="transcript_processing_failures")
    op.drop_index("ix_transcript_processing_failures_tenant_created_at", table_name="transcript_processing_failures")
    op.drop_table("transcript_processing_failures")
