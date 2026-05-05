"""add trust flag assignment

Revision ID: 20260505_000013
Revises: 20260505_000012
Create Date: 2026-05-05 20:45:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260505_000013"
down_revision = "20260505_000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trust_flags",
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_trust_flags_assigned_to_user_id_app_users",
        "trust_flags",
        "app_users",
        ["assigned_to_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_trust_flags_assigned_to_user_id_app_users", "trust_flags", type_="foreignkey")
    op.drop_column("trust_flags", "assigned_to_user_id")
