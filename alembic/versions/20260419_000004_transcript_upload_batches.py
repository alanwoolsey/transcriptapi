"""transcript upload batches

Revision ID: 20260419_000004
Revises: 20260419_000003
Create Date: 2026-04-19 16:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260419_000004"
down_revision: Union[str, None] = "20260419_000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transcript_upload_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'processing'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_transcript_upload_batches_tenant_created_at",
        "transcript_upload_batches",
        [sa.text("tenant_id"), sa.text("created_at DESC")],
    )

    op.create_table(
        "transcript_upload_batch_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcript_upload_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'processing'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_transcript_upload_batch_items_tenant_batch_position",
        "transcript_upload_batch_items",
        ["tenant_id", "batch_id", "position"],
    )

    op.execute(
        """
        CREATE TRIGGER trg_transcript_upload_batches_updated_at
        BEFORE UPDATE ON transcript_upload_batches
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_transcript_upload_batch_items_updated_at
        BEFORE UPDATE ON transcript_upload_batch_items
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_transcript_upload_batch_items_updated_at ON transcript_upload_batch_items")
    op.execute("DROP TRIGGER IF EXISTS trg_transcript_upload_batches_updated_at ON transcript_upload_batches")
    op.drop_index("ix_transcript_upload_batch_items_tenant_batch_position", table_name="transcript_upload_batch_items")
    op.drop_table("transcript_upload_batch_items")
    op.drop_index("ix_transcript_upload_batches_tenant_created_at", table_name="transcript_upload_batches")
    op.drop_table("transcript_upload_batches")
