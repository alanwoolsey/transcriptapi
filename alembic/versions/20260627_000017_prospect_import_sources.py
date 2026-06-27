"""prospect import sources and batches

Revision ID: 20260627_000017
Revises: 20260619_000016
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260627_000017"
down_revision = "20260619_000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prospect_import_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_category", sa.Text(), nullable=False),
        sa.Column("default_lifecycle_stage", sa.Text(), nullable=True),
        sa.Column("default_population", sa.Text(), nullable=True),
        sa.Column("default_student_type", sa.Text(), nullable=True),
        sa.Column("default_entry_term", sa.Text(), nullable=True),
        sa.Column("default_mapping_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_prospect_import_sources_tenant_name"),
    )
    op.create_index("ix_prospect_import_sources_tenant_active", "prospect_import_sources", ["tenant_id", "is_active"])

    op.create_table(
        "prospect_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("import_mode", sa.Text(), nullable=False),
        sa.Column("mapping_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_prospect_import_batches_tenant_created", "prospect_import_batches", ["tenant_id", sa.text("created_at DESC")])
    op.create_index("ix_prospect_import_batches_tenant_source", "prospect_import_batches", ["tenant_id", "source_id"])


def downgrade() -> None:
    op.drop_index("ix_prospect_import_batches_tenant_source", table_name="prospect_import_batches")
    op.drop_index("ix_prospect_import_batches_tenant_created", table_name="prospect_import_batches")
    op.drop_table("prospect_import_batches")
    op.drop_index("ix_prospect_import_sources_tenant_active", table_name="prospect_import_sources")
    op.drop_table("prospect_import_sources")
