"""prospect import roadmap tables

Revision ID: 20260627_000018
Revises: 20260627_000017
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260627_000018"
down_revision = "20260627_000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prospect_import_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("normalized_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("matched_student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
        sa.Column("matched_prospect_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("match_confidence", sa.Integer(), nullable=True),
        sa.Column("error_messages_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "batch_id", "row_number", name="uq_prospect_import_rows_batch_row"),
    )
    op.create_index("ix_prospect_import_rows_tenant_batch", "prospect_import_rows", ["tenant_id", "batch_id"])
    op.create_index("ix_prospect_import_rows_tenant_status", "prospect_import_rows", ["tenant_id", "status"])

    op.create_table(
        "prospect_import_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_batches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("row_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_rows.id", ondelete="CASCADE"), nullable=True),
        sa.Column("exception_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_prospect_import_exceptions_tenant_status", "prospect_import_exceptions", ["tenant_id", "status"])
    op.create_index("ix_prospect_import_exceptions_tenant_batch", "prospect_import_exceptions", ["tenant_id", "batch_id"])

    op.create_table(
        "prospect_import_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_detail", sa.Text(), nullable=True),
        sa.Column("default_lifecycle_stage", sa.Text(), nullable=True),
        sa.Column("field_mappings_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("normalization_rules_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("dedupe_rules_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("assignment_rules_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("campaign_rules_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_rules_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_prospect_import_templates_tenant_name"),
    )
    op.create_index("ix_prospect_import_templates_tenant_type", "prospect_import_templates", ["tenant_id", "source_type"])

    op.create_table(
        "prospect_assignment_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_sources.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("operator", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_team_id", sa.Text(), nullable=True),
        sa.Column("territory", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prospect_assignment_rules_tenant_source", "prospect_assignment_rules", ["tenant_id", "source_id", "active"])

    op.create_table(
        "student_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_team_id", sa.Text(), nullable=True),
        sa.Column("territory", sa.Text(), nullable=True),
        sa.Column("assignment_reason", sa.Text(), nullable=False),
        sa.Column("assigned_by_rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_assignment_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_assignments_tenant_student", "student_assignments", ["tenant_id", "student_id"])

    op.create_table(
        "student_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_detail", sa.Text(), nullable=True),
        sa.Column("source_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("primary_source", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw_source_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("first_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_sources_tenant_student", "student_sources", ["tenant_id", "student_id"])
    op.create_index("ix_student_sources_tenant_source", "student_sources", ["tenant_id", "source_name"])

    op.create_table(
        "prospect_scheduled_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_sources.id", ondelete="CASCADE"), nullable=True),
        sa.Column("mapping_template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("delivery_method", sa.Text(), nullable=False),
        sa.Column("inbound_folder", sa.Text(), nullable=True),
        sa.Column("schedule", sa.Text(), nullable=True),
        sa.Column("import_mode", sa.Text(), nullable=False),
        sa.Column("failure_notification_email", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("last_run_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prospect_scheduled_imports_tenant_status", "prospect_scheduled_imports", ["tenant_id", "status"])

    op.create_table(
        "prospect_api_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_sources.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prospect_api_credentials_tenant_active", "prospect_api_credentials", ["tenant_id", "active"])

    op.create_table(
        "prospect_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prospect_import_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prospect_webhook_events_tenant_received", "prospect_webhook_events", ["tenant_id", sa.text("received_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_prospect_webhook_events_tenant_received", table_name="prospect_webhook_events")
    op.drop_table("prospect_webhook_events")
    op.drop_index("ix_prospect_api_credentials_tenant_active", table_name="prospect_api_credentials")
    op.drop_table("prospect_api_credentials")
    op.drop_index("ix_prospect_scheduled_imports_tenant_status", table_name="prospect_scheduled_imports")
    op.drop_table("prospect_scheduled_imports")
    op.drop_index("ix_student_sources_tenant_source", table_name="student_sources")
    op.drop_index("ix_student_sources_tenant_student", table_name="student_sources")
    op.drop_table("student_sources")
    op.drop_index("ix_student_assignments_tenant_student", table_name="student_assignments")
    op.drop_table("student_assignments")
    op.drop_index("ix_prospect_assignment_rules_tenant_source", table_name="prospect_assignment_rules")
    op.drop_table("prospect_assignment_rules")
    op.drop_index("ix_prospect_import_templates_tenant_type", table_name="prospect_import_templates")
    op.drop_table("prospect_import_templates")
    op.drop_index("ix_prospect_import_exceptions_tenant_batch", table_name="prospect_import_exceptions")
    op.drop_index("ix_prospect_import_exceptions_tenant_status", table_name="prospect_import_exceptions")
    op.drop_table("prospect_import_exceptions")
    op.drop_index("ix_prospect_import_rows_tenant_status", table_name="prospect_import_rows")
    op.drop_index("ix_prospect_import_rows_tenant_batch", table_name="prospect_import_rows")
    op.drop_table("prospect_import_rows")
