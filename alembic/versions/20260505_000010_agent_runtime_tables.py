"""add agent runtime persistence tables

Revision ID: 20260505_000010
Revises: 20260505_000009
Create Date: 2026-05-05 09:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260505_000010"
down_revision: Union[str, None] = "20260505_000009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL")),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="SET NULL")),
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL")),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("agent_type", sa.Text()),
        sa.Column("trigger_event", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text()),
        sa.Column("correlation_id", sa.Text()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_runs_tenant_agent_status", "agent_runs", ["tenant_id", "agent_name", "status"])
    op.create_index("ix_agent_runs_tenant_student_created_desc", "agent_runs", ["tenant_id", "student_id", sa.text("created_at DESC")])
    op.create_index("ix_agent_runs_tenant_transcript_created_desc", "agent_runs", ["tenant_id", "transcript_id", sa.text("created_at DESC")])
    op.create_index("ix_agent_runs_correlation_id", "agent_runs", ["correlation_id"])

    op.create_table(
        "agent_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL")),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="SET NULL")),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_actions_tenant_run_created_desc", "agent_actions", ["tenant_id", "run_id", sa.text("created_at DESC")])
    op.create_index("ix_agent_actions_tenant_tool_status", "agent_actions", ["tenant_id", "tool_name", "status"])

    op.create_table(
        "agent_handoffs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL")),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="SET NULL")),
        sa.Column("from_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("to_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("from_agent_name", sa.Text(), nullable=False),
        sa.Column("to_agent_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'requested'")),
        sa.Column("reason", sa.Text()),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_handoffs_tenant_student_created_desc", "agent_handoffs", ["tenant_id", "student_id", sa.text("created_at DESC")])
    op.create_index("ix_agent_handoffs_tenant_to_agent_status", "agent_handoffs", ["tenant_id", "to_agent_name", "status"])

    op.create_table(
        "student_agent_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_owner_agent", sa.Text()),
        sa.Column("current_stage", sa.Text()),
        sa.Column("state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_document_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("last_trust_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("last_decision_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("last_orchestrator_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_agent_state_tenant_student", "student_agent_state", ["tenant_id", "student_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_student_agent_state_tenant_student", table_name="student_agent_state")
    op.drop_table("student_agent_state")

    op.drop_index("ix_agent_handoffs_tenant_to_agent_status", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_tenant_student_created_desc", table_name="agent_handoffs")
    op.drop_table("agent_handoffs")

    op.drop_index("ix_agent_actions_tenant_tool_status", table_name="agent_actions")
    op.drop_index("ix_agent_actions_tenant_run_created_desc", table_name="agent_actions")
    op.drop_table("agent_actions")

    op.drop_index("ix_agent_runs_correlation_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_transcript_created_desc", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_student_created_desc", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_agent_status", table_name="agent_runs")
    op.drop_table("agent_runs")
