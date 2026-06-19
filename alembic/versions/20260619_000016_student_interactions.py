"""add student interactions

Revision ID: 20260619_000016
Revises: 20260604_000015
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260619_000016"
down_revision = "20260604_000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "student_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("next_follow_up_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_name", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_student_interactions_tenant_student_occurred_desc",
        "student_interactions",
        ["tenant_id", "student_id", sa.text("occurred_at DESC")],
    )
    op.create_index("ix_student_interactions_tenant_type", "student_interactions", ["tenant_id", "type"])


def downgrade() -> None:
    op.drop_index("ix_student_interactions_tenant_type", table_name="student_interactions")
    op.drop_index("ix_student_interactions_tenant_student_occurred_desc", table_name="student_interactions")
    op.drop_table("student_interactions")
