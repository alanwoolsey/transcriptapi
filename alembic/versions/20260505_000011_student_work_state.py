"""add student work state projection table

Revision ID: 20260505_000011
Revises: 20260505_000010
Create Date: 2026-05-05 11:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260505_000011"
down_revision: Union[str, None] = "20260505_000010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_work_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_identifier", sa.Text(), nullable=False),
        sa.Column("student_name", sa.Text(), nullable=False),
        sa.Column("population", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("completion_percent", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Integer()),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL")),
        sa.Column("owner_name", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("reason_label", sa.Text(), nullable=False),
        sa.Column("suggested_action_code", sa.Text(), nullable=False),
        sa.Column("suggested_action_label", sa.Text(), nullable=False),
        sa.Column("readiness_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("blocking_items_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("checklist_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fit_score", sa.Integer(), nullable=False),
        sa.Column("deposit_likelihood", sa.Integer(), nullable=False),
        sa.Column("program", sa.Text(), nullable=False),
        sa.Column("institution_goal", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("last_activity_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("projected_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_work_state_tenant_student", "student_work_state", ["tenant_id", "student_id"], unique=True)
    op.create_index("ix_student_work_state_tenant_section_priority", "student_work_state", ["tenant_id", "section", "priority"])
    op.create_index("ix_student_work_state_tenant_population", "student_work_state", ["tenant_id", "population"])
    op.create_index("ix_student_work_state_tenant_projected_desc", "student_work_state", ["tenant_id", sa.text("projected_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_student_work_state_tenant_projected_desc", table_name="student_work_state")
    op.drop_index("ix_student_work_state_tenant_population", table_name="student_work_state")
    op.drop_index("ix_student_work_state_tenant_section_priority", table_name="student_work_state")
    op.drop_index("ix_student_work_state_tenant_student", table_name="student_work_state")
    op.drop_table("student_work_state")
