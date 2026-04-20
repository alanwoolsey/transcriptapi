"""admissions ops wave 1

Revision ID: 20260420_000006
Revises: 20260419_000005
Create Date: 2026-04-20 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260420_000006"
down_revision: Union[str, None] = "20260419_000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "checklist_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("population", sa.Text(), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("programs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("start_term_code", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_checklist_templates_tenant_population_active", "checklist_templates", ["tenant_id", "population", "active"])

    op.create_table(
        "checklist_template_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("checklist_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("document_type", sa.Text(), nullable=True),
        sa.Column("review_required_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_checklist_template_items_template_sort", "checklist_template_items", ["template_id", "sort_order"])

    op.create_table(
        "student_checklists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("checklist_templates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("population", sa.Text(), nullable=False),
        sa.Column("completion_percent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("one_item_away", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'incomplete'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_checklists_tenant_student", "student_checklists", ["tenant_id", "student_id"], unique=True)
    op.create_index("ix_student_checklists_tenant_status", "student_checklists", ["tenant_id", "status"])

    op.create_table(
        "student_checklist_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("student_checklist_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("student_checklists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("checklist_template_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'missing'")),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_uploads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_checklist_items_tenant_student_status", "student_checklist_items", ["tenant_id", "student_id", "status"])
    op.create_index("ix_student_checklist_items_checklist", "student_checklist_items", ["student_checklist_id", "code"])

    op.create_table(
        "student_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("signal_label", sa.Text(), nullable=False),
        sa.Column("signal_value", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_student_signals_tenant_student_active", "student_signals", ["tenant_id", "student_id", "active"])
    op.create_index("ix_student_signals_tenant_type_active", "student_signals", ["tenant_id", "signal_type", "active"])

    op.create_table(
        "student_priority_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False),
        sa.Column("priority_band", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_priority_scores_tenant_student", "student_priority_scores", ["tenant_id", "student_id"], unique=True)
    op.create_index("ix_student_priority_scores_tenant_band", "student_priority_scores", ["tenant_id", "priority_band"])

    op.create_table(
        "student_decision_readiness",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("readiness_state", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("reason_label", sa.Text(), nullable=False),
        sa.Column("blocking_item_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("trust_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_decision_readiness_tenant_student", "student_decision_readiness", ["tenant_id", "student_id"], unique=True)
    op.create_index("ix_student_decision_readiness_tenant_state", "student_decision_readiness", ["tenant_id", "readiness_state"])

    op.create_table(
        "document_checklist_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checklist_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("student_checklist_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("match_status", sa.Text(), nullable=False),
        sa.Column("linked_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("linked_by", sa.Text(), nullable=False),
    )
    op.create_index("ix_document_checklist_links_tenant_student", "document_checklist_links", ["tenant_id", "student_id"])
    op.create_index("ix_document_checklist_links_tenant_document", "document_checklist_links", ["tenant_id", "document_id"])

    op.create_table(
        "duplicate_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("primary_student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("match_reasons_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_duplicate_candidates_tenant_status", "duplicate_candidates", ["tenant_id", "status"])

    op.create_table(
        "duplicate_merge_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duplicate_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("field_conflicts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_duplicate_merge_actions_tenant_candidate", "duplicate_merge_actions", ["tenant_id", "candidate_id"])

    op.create_table(
        "student_enrollment_milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("milestone_code", sa.Text(), nullable=False),
        sa.Column("milestone_label", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("achieved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_enrollment_milestones_tenant_student", "student_enrollment_milestones", ["tenant_id", "student_id"])

    op.create_table(
        "student_yield_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_yield_scores_tenant_student", "student_yield_scores", ["tenant_id", "student_id"], unique=True)

    op.create_table(
        "student_melt_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_melt_scores_tenant_student", "student_melt_scores", ["tenant_id", "student_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_student_melt_scores_tenant_student", table_name="student_melt_scores")
    op.drop_table("student_melt_scores")
    op.drop_index("ix_student_yield_scores_tenant_student", table_name="student_yield_scores")
    op.drop_table("student_yield_scores")
    op.drop_index("ix_student_enrollment_milestones_tenant_student", table_name="student_enrollment_milestones")
    op.drop_table("student_enrollment_milestones")
    op.drop_index("ix_duplicate_merge_actions_tenant_candidate", table_name="duplicate_merge_actions")
    op.drop_table("duplicate_merge_actions")
    op.drop_index("ix_duplicate_candidates_tenant_status", table_name="duplicate_candidates")
    op.drop_table("duplicate_candidates")
    op.drop_index("ix_document_checklist_links_tenant_document", table_name="document_checklist_links")
    op.drop_index("ix_document_checklist_links_tenant_student", table_name="document_checklist_links")
    op.drop_table("document_checklist_links")
    op.drop_index("ix_student_decision_readiness_tenant_state", table_name="student_decision_readiness")
    op.drop_index("ix_student_decision_readiness_tenant_student", table_name="student_decision_readiness")
    op.drop_table("student_decision_readiness")
    op.drop_index("ix_student_priority_scores_tenant_band", table_name="student_priority_scores")
    op.drop_index("ix_student_priority_scores_tenant_student", table_name="student_priority_scores")
    op.drop_table("student_priority_scores")
    op.drop_index("ix_student_signals_tenant_type_active", table_name="student_signals")
    op.drop_index("ix_student_signals_tenant_student_active", table_name="student_signals")
    op.drop_table("student_signals")
    op.drop_index("ix_student_checklist_items_checklist", table_name="student_checklist_items")
    op.drop_index("ix_student_checklist_items_tenant_student_status", table_name="student_checklist_items")
    op.drop_table("student_checklist_items")
    op.drop_index("ix_student_checklists_tenant_status", table_name="student_checklists")
    op.drop_index("ix_student_checklists_tenant_student", table_name="student_checklists")
    op.drop_table("student_checklists")
    op.drop_index("ix_checklist_template_items_template_sort", table_name="checklist_template_items")
    op.drop_table("checklist_template_items")
    op.drop_index("ix_checklist_templates_tenant_population_active", table_name="checklist_templates")
    op.drop_table("checklist_templates")
