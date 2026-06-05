"""phase2 prospect intake

Revision ID: 20260604_000015
Revises: 20260604_000014
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260604_000015"
down_revision = "20260604_000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prospects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("population", sa.Text(), nullable=False),
        sa.Column("program_interest", sa.Text(), nullable=True),
        sa.Column("term_interest", sa.Text(), nullable=True),
        sa.Column("prior_institution", sa.Text(), nullable=True),
        sa.Column("lifecycle_stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_category", sa.Text(), nullable=False),
        sa.Column("campaign", sa.Text(), nullable=True),
        sa.Column("consent_captured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prospects_tenant_email", "prospects", ["tenant_id", "email"])
    op.create_index("ix_prospects_tenant_status", "prospects", ["tenant_id", "status"])
    op.create_index("ix_prospects_tenant_student", "prospects", ["tenant_id", "student_id"])

    op.create_table(
        "prospect_source_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prospect_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_category", sa.Text(), nullable=False),
        sa.Column("campaign", sa.Text(), nullable=True),
        sa.Column("external_reference_id", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("captured_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prospect_source_refs_tenant_prospect", "prospect_source_references", ["tenant_id", "prospect_id"])
    op.create_index("ix_prospect_source_refs_tenant_external", "prospect_source_references", ["tenant_id", "external_reference_id"])

    op.create_table(
        "prospect_transcript_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prospect_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("file_size", sa.BIGINT(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("processing_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prospect_uploads_tenant_email", "prospect_transcript_uploads", ["tenant_id", "email"])
    op.create_index("ix_prospect_uploads_tenant_prospect", "prospect_transcript_uploads", ["tenant_id", "prospect_id"])
    op.create_index("ix_prospect_uploads_tenant_status", "prospect_transcript_uploads", ["tenant_id", "status"])

    op.create_table(
        "prospect_fit_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prospect_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_transcript_uploads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("program", sa.Text(), nullable=False),
        sa.Column("fit_score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("transfer_credits", sa.Integer(), nullable=True),
        sa.Column("estimated_completion", sa.Text(), nullable=True),
        sa.Column("scholarship_potential", sa.Text(), nullable=True),
        sa.Column("missing_items_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("signals_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_prospect_fit_results_tenant_prospect",
        "prospect_fit_results",
        ["tenant_id", "prospect_id", sa.text("computed_at DESC")],
    )

    op.create_table(
        "prospect_next_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prospect_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_prospect_next_actions_tenant_prospect", "prospect_next_actions", ["tenant_id", "prospect_id"])
    op.create_index("ix_prospect_next_actions_tenant_status", "prospect_next_actions", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_prospect_next_actions_tenant_status", table_name="prospect_next_actions")
    op.drop_index("ix_prospect_next_actions_tenant_prospect", table_name="prospect_next_actions")
    op.drop_table("prospect_next_actions")
    op.drop_index("ix_prospect_fit_results_tenant_prospect", table_name="prospect_fit_results")
    op.drop_table("prospect_fit_results")
    op.drop_index("ix_prospect_uploads_tenant_status", table_name="prospect_transcript_uploads")
    op.drop_index("ix_prospect_uploads_tenant_prospect", table_name="prospect_transcript_uploads")
    op.drop_index("ix_prospect_uploads_tenant_email", table_name="prospect_transcript_uploads")
    op.drop_table("prospect_transcript_uploads")
    op.drop_index("ix_prospect_source_refs_tenant_external", table_name="prospect_source_references")
    op.drop_index("ix_prospect_source_refs_tenant_prospect", table_name="prospect_source_references")
    op.drop_table("prospect_source_references")
    op.drop_index("ix_prospects_tenant_student", table_name="prospects")
    op.drop_index("ix_prospects_tenant_status", table_name="prospects")
    op.drop_index("ix_prospects_tenant_email", table_name="prospects")
    op.drop_table("prospects")
