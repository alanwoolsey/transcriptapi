"""decision workflow phase 1

Revision ID: 20260419_000003
Revises: 20260419_000002
Create Date: 2026-04-19 16:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260419_000003"
down_revision: Union[str, None] = "20260419_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("decision_packets", sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("decision_packets", sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "decision_packets",
        sa.Column("queue_name", sa.Text(), nullable=False, server_default=sa.text("'Admissions Review'")),
    )
    op.add_column(
        "decision_packets",
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'Draft'")),
    )
    op.create_foreign_key(
        "fk_decision_packets_transcript_id_transcripts",
        "decision_packets",
        "transcripts",
        ["transcript_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_decision_packets_assigned_to_user_id_app_users",
        "decision_packets",
        "app_users",
        ["assigned_to_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_decision_packets_tenant_transcript_id",
        "decision_packets",
        ["tenant_id", "transcript_id"],
    )

    op.create_table(
        "decision_packet_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_packet_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("decision_packets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_decision_packet_notes_tenant_packet_created_at",
        "decision_packet_notes",
        [sa.text("tenant_id"), sa.text("decision_packet_id"), sa.text("created_at DESC")],
    )

    op.create_table(
        "decision_packet_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_packet_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("decision_packets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("event_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_decision_packet_events_tenant_packet_event_at",
        "decision_packet_events",
        [sa.text("tenant_id"), sa.text("decision_packet_id"), sa.text("event_at DESC")],
    )

    op.execute(
        """
        CREATE TRIGGER trg_decision_packet_notes_updated_at
        BEFORE UPDATE ON decision_packet_notes
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_decision_packet_notes_updated_at ON decision_packet_notes")
    op.drop_index("ix_decision_packet_events_tenant_packet_event_at", table_name="decision_packet_events")
    op.drop_table("decision_packet_events")
    op.drop_index("ix_decision_packet_notes_tenant_packet_created_at", table_name="decision_packet_notes")
    op.drop_table("decision_packet_notes")
    op.drop_index("ix_decision_packets_tenant_transcript_id", table_name="decision_packets")
    op.drop_constraint("fk_decision_packets_assigned_to_user_id_app_users", "decision_packets", type_="foreignkey")
    op.drop_constraint("fk_decision_packets_transcript_id_transcripts", "decision_packets", type_="foreignkey")
    op.drop_column("decision_packets", "status")
    op.drop_column("decision_packets", "queue_name")
    op.drop_column("decision_packets", "assigned_to_user_id")
    op.drop_column("decision_packets", "transcript_id")
