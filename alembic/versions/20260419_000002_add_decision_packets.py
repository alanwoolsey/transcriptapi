"""add decision packets

Revision ID: 20260419_000002
Revises: 20260417_000001
Create Date: 2026-04-19 15:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260419_000002"
down_revision: Union[str, None] = "20260417_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_packets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("student_name", sa.Text(), nullable=False),
        sa.Column("program_name", sa.Text(), nullable=False),
        sa.Column("fit_score", sa.Integer(), nullable=False),
        sa.Column("credit_estimate", sa.Integer(), nullable=False),
        sa.Column("readiness", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_decision_packets_tenant_created_at", "decision_packets", [sa.text("tenant_id"), sa.text("created_at DESC")])
    op.create_index(
        "ix_decision_packets_tenant_student_created_at",
        "decision_packets",
        [sa.text("tenant_id"), sa.text("student_id"), sa.text("created_at DESC")],
    )
    op.execute(
        """
        CREATE TRIGGER trg_decision_packets_updated_at
        BEFORE UPDATE ON decision_packets
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_decision_packets_updated_at ON decision_packets")
    op.drop_index("ix_decision_packets_tenant_student_created_at", table_name="decision_packets")
    op.drop_index("ix_decision_packets_tenant_created_at", table_name="decision_packets")
    op.drop_table("decision_packets")
