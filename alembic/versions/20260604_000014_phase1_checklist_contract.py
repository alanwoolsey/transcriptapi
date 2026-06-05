"""phase1 checklist contract

Revision ID: 20260604_000014
Revises: 20260505_000013
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260604_000014"
down_revision = "20260505_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("checklist_templates", sa.Column("term_code", sa.Text(), nullable=True))
    op.add_column(
        "checklist_template_items",
        sa.Column("optional", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "checklist_template_items",
        sa.Column("conditional", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "checklist_template_items",
        sa.Column("waivable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "checklist_template_items",
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.execute("UPDATE student_checklist_items SET status = 'not_started' WHERE status = 'missing'")


def downgrade() -> None:
    op.execute("UPDATE student_checklist_items SET status = 'missing' WHERE status = 'not_started'")
    op.drop_column("checklist_template_items", "blocking")
    op.drop_column("checklist_template_items", "waivable")
    op.drop_column("checklist_template_items", "conditional")
    op.drop_column("checklist_template_items", "optional")
    op.drop_column("checklist_templates", "term_code")
