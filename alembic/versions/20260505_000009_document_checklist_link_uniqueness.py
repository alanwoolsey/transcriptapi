"""dedupe document checklist links and enforce uniqueness

Revision ID: 20260505_000009
Revises: 20260420_000008
Create Date: 2026-05-05 08:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260505_000009"
down_revision: Union[str, None] = "20260420_000008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY tenant_id, document_id, checklist_item_id
                        ORDER BY linked_at DESC, id DESC
                    ) AS rn
                FROM document_checklist_links
            )
            DELETE FROM document_checklist_links d
            USING ranked r
            WHERE d.id = r.id
              AND r.rn > 1
            """
        )
    )

    op.create_index(
        "uq_document_checklist_links_tenant_document_item",
        "document_checklist_links",
        ["tenant_id", "document_id", "checklist_item_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_document_checklist_links_tenant_document_item", table_name="document_checklist_links")
