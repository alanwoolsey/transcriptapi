"""enforce single-tenant app users

Revision ID: 20260420_000008
Revises: 20260420_000007
Create Date: 2026-04-20 15:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260420_000008"
down_revision: Union[str, None] = "20260420_000007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_app_users_tenant_id_tenants",
        "app_users",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )

    bind = op.get_bind()
    multi_tenant_rows = bind.execute(
        sa.text(
            """
            SELECT user_id
            FROM tenant_user_memberships
            GROUP BY user_id
            HAVING COUNT(DISTINCT tenant_id) > 1
            """
        )
    ).fetchall()
    if multi_tenant_rows:
        raise RuntimeError("Cannot migrate to single-tenant users: existing users are assigned to multiple tenants.")

    orphan_rows = bind.execute(
        sa.text(
            """
            SELECT au.id
            FROM app_users au
            LEFT JOIN tenant_user_memberships tum ON tum.user_id = au.id
            WHERE tum.user_id IS NULL
            """
        )
    ).fetchall()
    if orphan_rows:
        raise RuntimeError("Cannot migrate to single-tenant users: some app_users rows have no tenant membership.")

    bind.execute(
        sa.text(
            """
            UPDATE app_users au
            SET tenant_id = tum.tenant_id
            FROM tenant_user_memberships tum
            WHERE tum.user_id = au.id
            """
        )
    )

    op.alter_column("app_users", "tenant_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.create_index("ix_app_users_tenant_id", "app_users", ["tenant_id"], unique=False)
    op.create_unique_constraint("uq_tenant_user_memberships_user_id", "tenant_user_memberships", ["user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_tenant_user_memberships_user_id", "tenant_user_memberships", type_="unique")
    op.drop_index("ix_app_users_tenant_id", table_name="app_users")
    op.drop_constraint("fk_app_users_tenant_id_tenants", "app_users", type_="foreignkey")
    op.drop_column("app_users", "tenant_id")
