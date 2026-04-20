"""authz schema rbac foundation

Revision ID: 20260420_000007
Revises: 20260420_000006
Create Date: 2026-04-20 13:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260420_000007"
down_revision: Union[str, None] = "20260420_000006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AUTHZ_SCHEMA = "authz"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {AUTHZ_SCHEMA}"))

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("system_key", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=AUTHZ_SCHEMA,
    )
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=AUTHZ_SCHEMA,
    )
    op.create_table(
        "role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{AUTHZ_SCHEMA}.roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{AUTHZ_SCHEMA}.permissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_authz_role_permissions_role_permission"),
        schema=AUTHZ_SCHEMA,
    )
    op.create_table(
        "user_role_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{AUTHZ_SCHEMA}.roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("granted_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "user_id", "role_id", name="uq_authz_user_role_assignments"),
        schema=AUTHZ_SCHEMA,
    )
    op.create_table(
        "scope_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{AUTHZ_SCHEMA}.user_role_assignments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_value", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=AUTHZ_SCHEMA,
    )
    op.create_table(
        "record_exception_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exception_code", sa.Text(), nullable=False),
        sa.Column("record_type", sa.Text(), nullable=True),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=AUTHZ_SCHEMA,
    )
    op.create_table(
        "sensitivity_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sensitivity_tier", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=AUTHZ_SCHEMA,
    )

    op.create_index("ix_authz_user_role_assignments_tenant_user", "user_role_assignments", ["tenant_id", "user_id"], schema=AUTHZ_SCHEMA)
    op.create_index("ix_authz_scope_grants_tenant_user_type", "scope_grants", ["tenant_id", "user_id", "scope_type"], schema=AUTHZ_SCHEMA)
    op.create_index("ix_authz_record_exception_grants_tenant_user", "record_exception_grants", ["tenant_id", "user_id"], schema=AUTHZ_SCHEMA)
    op.create_index("ix_authz_sensitivity_grants_tenant_user", "sensitivity_grants", ["tenant_id", "user_id"], schema=AUTHZ_SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_authz_sensitivity_grants_tenant_user", table_name="sensitivity_grants", schema=AUTHZ_SCHEMA)
    op.drop_index("ix_authz_record_exception_grants_tenant_user", table_name="record_exception_grants", schema=AUTHZ_SCHEMA)
    op.drop_index("ix_authz_scope_grants_tenant_user_type", table_name="scope_grants", schema=AUTHZ_SCHEMA)
    op.drop_index("ix_authz_user_role_assignments_tenant_user", table_name="user_role_assignments", schema=AUTHZ_SCHEMA)
    op.drop_table("sensitivity_grants", schema=AUTHZ_SCHEMA)
    op.drop_table("record_exception_grants", schema=AUTHZ_SCHEMA)
    op.drop_table("scope_grants", schema=AUTHZ_SCHEMA)
    op.drop_table("user_role_assignments", schema=AUTHZ_SCHEMA)
    op.drop_table("role_permissions", schema=AUTHZ_SCHEMA)
    op.drop_table("permissions", schema=AUTHZ_SCHEMA)
    op.drop_table("roles", schema=AUTHZ_SCHEMA)
    op.execute(sa.text(f"DROP SCHEMA IF EXISTS {AUTHZ_SCHEMA}"))
