"""initial schema

Revision ID: 20260417_000001
Revises:
Create Date: 2026-04-17 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260417_000001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UPDATED_AT_TABLES = [
    "tenants",
    "tenant_settings",
    "app_users",
    "tenant_user_memberships",
    "institutions",
    "programs",
    "students",
    "document_uploads",
    "transcripts",
    "transcript_demographics",
    "transcript_gpa_summaries",
    "workflow_cases",
    "trust_flags",
    "student_notes",
    "student_tasks",
]


def _create_update_timestamp_helpers() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def _attach_update_trigger(table_name: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table_name}_updated_at
        BEFORE UPDATE ON {table_name}
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )


def upgrade() -> None:
    _create_update_timestamp_helpers()

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("primary_region", sa.Text(), nullable=True),
        sa.Column("data_retention_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("default_document_type", sa.Text(), nullable=True),
        sa.Column("use_bedrock_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("student_match_strategy", sa.Text(), nullable=True),
        sa.Column("queue_sla_hours", sa.Integer(), nullable=True),
        sa.Column("settings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "app_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("cognito_sub", sa.Text(), nullable=True),
        sa.Column("identity_provider", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_app_users_email"),
        sa.UniqueConstraint("cognito_sub", name="uq_app_users_cognito_sub"),
    )

    op.create_table(
        "tenant_user_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user_memberships_tenant_id_user_id"),
    )

    op.create_table(
        "institutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("external_code", sa.Text(), nullable=True),
        sa.Column("ceeb_code", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("institution_type", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_institutions_name_trgm", "institutions", ["name"], postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"})

    op.create_table(
        "programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("program_code", sa.Text(), nullable=True),
        sa.Column("degree_type", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "institution_id", "name", name="uq_programs_tenant_id_institution_id_name"),
    )

    op.create_table(
        "students",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_student_id", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("middle_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("preferred_name", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("target_program_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("programs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_institution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("advisor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("current_stage", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.Text(), nullable=False, server_default=sa.text("'low'")),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("latest_cumulative_gpa", sa.Numeric(5, 2), nullable=True),
        sa.Column("accepted_credits", sa.Numeric(8, 2), nullable=True),
        sa.Column("latest_activity_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_students_tenant_last_first", "students", ["tenant_id", "last_name", "first_name"])
    op.create_index("ix_students_tenant_stage", "students", ["tenant_id", "current_stage"])
    op.create_index("ix_students_tenant_advisor_stage", "students", ["tenant_id", "advisor_user_id", "current_stage"])
    op.create_index("ix_students_tenant_latest_activity", "students", [sa.text("tenant_id"), sa.text("latest_activity_at DESC")])
    op.create_index(
        "uq_students_tenant_external_student_id_not_null",
        "students",
        ["tenant_id", "external_student_id"],
        unique=True,
        postgresql_where=sa.text("external_student_id IS NOT NULL"),
    )
    op.create_index("ix_students_last_name_trgm", "students", ["last_name"], postgresql_using="gin", postgresql_ops={"last_name": "gin_trgm_ops"})
    op.create_index("ix_students_first_name_trgm", "students", ["first_name"], postgresql_using="gin", postgresql_ops={"first_name": "gin_trgm_ops"})

    op.create_table(
        "student_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identifier_type", sa.Text(), nullable=False),
        sa.Column("identifier_value", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "identifier_type", "identifier_value", name="uq_student_identifiers_tenant_id_identifier_type_identifier_value"),
    )

    op.create_table(
        "document_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_bucket", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("storage_version_id", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.Text(), nullable=True),
        sa.Column("upload_status", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "storage_bucket", "storage_key", name="uq_document_uploads_tenant_id_storage_bucket_storage_key"),
    )
    op.create_index("ix_document_uploads_filename_trgm", "document_uploads", ["original_filename"], postgresql_using="gin", postgresql_ops={"original_filename": "gin_trgm_ops"})

    op.create_table(
        "transcripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_institution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("is_official", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_finalized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("finalized_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finalized_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_fraudulent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fraud_flagged_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("matched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("matched_by", sa.Text(), nullable=True),
        sa.Column("parser_confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_transcripts_tenant_student_created_desc", "transcripts", [sa.text("tenant_id"), sa.text("student_id"), sa.text("created_at DESC")])
    op.create_index("ix_transcripts_tenant_status_created_desc", "transcripts", [sa.text("tenant_id"), sa.text("status"), sa.text("created_at DESC")])
    op.create_index("ix_transcripts_tenant_is_fraudulent_status", "transcripts", ["tenant_id", "is_fraudulent", "status"])

    op.create_table(
        "transcript_parse_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parser_name", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=True),
        sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_text_excerpt", sa.Text(), nullable=True),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_parse_runs_tenant_transcript_started_desc", "transcript_parse_runs", [sa.text("tenant_id"), sa.text("transcript_id"), sa.text("started_at DESC")])

    op.create_table(
        "transcript_demographics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_first_name", sa.Text(), nullable=True),
        sa.Column("student_middle_name", sa.Text(), nullable=True),
        sa.Column("student_last_name", sa.Text(), nullable=True),
        sa.Column("student_external_id", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("institution_name", sa.Text(), nullable=True),
        sa.Column("institution_city", sa.Text(), nullable=True),
        sa.Column("institution_state", sa.Text(), nullable=True),
        sa.Column("institution_postal_code", sa.Text(), nullable=True),
        sa.Column("institution_country", sa.Text(), nullable=True),
        sa.Column("cumulative_gpa", sa.Numeric(5, 2), nullable=True),
        sa.Column("weighted_gpa", sa.Numeric(5, 2), nullable=True),
        sa.Column("unweighted_gpa", sa.Numeric(5, 2), nullable=True),
        sa.Column("total_credits_attempted", sa.Numeric(8, 2), nullable=True),
        sa.Column("total_credits_earned", sa.Numeric(8, 2), nullable=True),
        sa.Column("total_grade_points", sa.Numeric(10, 2), nullable=True),
        sa.Column("degree_awarded", sa.Text(), nullable=True),
        sa.Column("graduation_date", sa.Date(), nullable=True),
        sa.Column("is_official", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("transcript_id", name="uq_transcript_demographics_transcript_id"),
    )

    op.create_table(
        "transcript_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term_name", sa.Text(), nullable=False),
        sa.Column("academic_year", sa.Text(), nullable=True),
        sa.Column("units_earned", sa.Numeric(8, 2), nullable=True),
        sa.Column("grade_points", sa.Numeric(10, 2), nullable=True),
        sa.Column("term_gpa", sa.Numeric(5, 4), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("transcript_id", "display_order", name="uq_transcript_terms_transcript_id_display_order"),
    )

    op.create_table(
        "transcript_courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcript_terms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_institution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subject_code", sa.Text(), nullable=True),
        sa.Column("course_code", sa.Text(), nullable=True),
        sa.Column("course_level", sa.Text(), nullable=True),
        sa.Column("course_title", sa.Text(), nullable=False),
        sa.Column("credits_attempted", sa.Numeric(8, 2), nullable=True),
        sa.Column("credits_earned", sa.Numeric(8, 2), nullable=True),
        sa.Column("grade_alpha", sa.Text(), nullable=True),
        sa.Column("grade_points", sa.Numeric(6, 2), nullable=True),
        sa.Column("course_gpa", sa.Numeric(5, 2), nullable=True),
        sa.Column("term_name", sa.Text(), nullable=True),
        sa.Column("academic_year", sa.Text(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("mapping_status", sa.Text(), nullable=True),
        sa.Column("transfer_status", sa.Text(), nullable=True),
        sa.Column("repeat_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw_course_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_transcript_courses_tenant_transcript", "transcript_courses", ["tenant_id", "transcript_id"])
    op.create_index("ix_transcript_courses_tenant_course_code", "transcript_courses", ["tenant_id", "course_code"])
    op.create_index("ix_transcript_courses_tenant_source_institution_course_code", "transcript_courses", ["tenant_id", "source_institution_id", "course_code"])

    op.create_table(
        "transcript_gpa_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("units_earned", sa.Numeric(8, 2), nullable=True),
        sa.Column("simple_gpa_points", sa.Numeric(10, 2), nullable=True),
        sa.Column("cumulative_gpa", sa.Numeric(5, 2), nullable=True),
        sa.Column("weighted_gpa", sa.Numeric(5, 2), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("transcript_id", name="uq_transcript_gpa_summaries_transcript_id"),
    )

    op.create_table(
        "transcript_student_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_status", sa.Text(), nullable=False),
        sa.Column("match_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("match_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_matches_tenant_student_current", "transcript_student_matches", ["tenant_id", "student_id", "is_current"])
    op.create_index("ix_matches_tenant_transcript_current", "transcript_student_matches", ["tenant_id", "transcript_id", "is_current"])

    op.create_table(
        "workflow_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("case_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("queue_name", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_workflow_cases_tenant_queue_status_priority", "workflow_cases", ["tenant_id", "queue_name", "status", "priority"])
    op.create_index("ix_workflow_cases_tenant_owner_status", "workflow_cases", ["tenant_id", "owner_user_id", "status"])
    op.create_index("ix_workflow_cases_tenant_opened_at", "workflow_cases", ["tenant_id", "opened_at"])

    op.create_table(
        "workflow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_cases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_category", sa.Text(), nullable=False),
        sa.Column("event_action", sa.Text(), nullable=False),
        sa.Column("event_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_workflow_events_tenant_student_event_time_desc", "workflow_events", [sa.text("tenant_id"), sa.text("student_id"), sa.text("event_time DESC")])
    op.create_index("ix_workflow_events_tenant_transcript_event_time_desc", "workflow_events", [sa.text("tenant_id"), sa.text("transcript_id"), sa.text("event_time DESC")])

    op.create_table(
        "trust_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
        sa.Column("flag_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("detected_by", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_trust_flags_tenant_status_severity_detected_desc", "trust_flags", [sa.text("tenant_id"), sa.text("status"), sa.text("severity"), sa.text("detected_at DESC")])
    op.create_index("ix_trust_flags_tenant_transcript_status", "trust_flags", ["tenant_id", "transcript_id", "status"])

    op.create_table(
        "student_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note_type", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "student_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_student_tasks_tenant_student_status", "student_tasks", ["tenant_id", "student_id", "status"])
    op.create_index("ix_student_tasks_tenant_assigned_status", "student_tasks", ["tenant_id", "assigned_to_user_id", "status"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_events_tenant_entity_type_entity_id_occurred_desc", "audit_events", [sa.text("tenant_id"), sa.text("entity_type"), sa.text("entity_id"), sa.text("occurred_at DESC")])
    op.create_index("ix_audit_events_tenant_occurred_desc", "audit_events", [sa.text("tenant_id"), sa.text("occurred_at DESC")])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])

    for table_name in UPDATED_AT_TABLES:
        _attach_update_trigger(table_name)


def downgrade() -> None:
    for table_name in reversed(UPDATED_AT_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_updated_at ON {table_name}")

    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_occurred_desc", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_entity_type_entity_id_occurred_desc", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_student_tasks_tenant_assigned_status", table_name="student_tasks")
    op.drop_index("ix_student_tasks_tenant_student_status", table_name="student_tasks")
    op.drop_table("student_tasks")
    op.drop_table("student_notes")
    op.drop_index("ix_trust_flags_tenant_transcript_status", table_name="trust_flags")
    op.drop_index("ix_trust_flags_tenant_status_severity_detected_desc", table_name="trust_flags")
    op.drop_table("trust_flags")
    op.drop_index("ix_workflow_events_tenant_transcript_event_time_desc", table_name="workflow_events")
    op.drop_index("ix_workflow_events_tenant_student_event_time_desc", table_name="workflow_events")
    op.drop_table("workflow_events")
    op.drop_index("ix_workflow_cases_tenant_opened_at", table_name="workflow_cases")
    op.drop_index("ix_workflow_cases_tenant_owner_status", table_name="workflow_cases")
    op.drop_index("ix_workflow_cases_tenant_queue_status_priority", table_name="workflow_cases")
    op.drop_table("workflow_cases")
    op.drop_index("ix_matches_tenant_transcript_current", table_name="transcript_student_matches")
    op.drop_index("ix_matches_tenant_student_current", table_name="transcript_student_matches")
    op.drop_table("transcript_student_matches")
    op.drop_table("transcript_gpa_summaries")
    op.drop_index("ix_transcript_courses_tenant_source_institution_course_code", table_name="transcript_courses")
    op.drop_index("ix_transcript_courses_tenant_course_code", table_name="transcript_courses")
    op.drop_index("ix_transcript_courses_tenant_transcript", table_name="transcript_courses")
    op.drop_table("transcript_courses")
    op.drop_table("transcript_terms")
    op.drop_table("transcript_demographics")
    op.drop_index("ix_parse_runs_tenant_transcript_started_desc", table_name="transcript_parse_runs")
    op.drop_table("transcript_parse_runs")
    op.drop_index("ix_transcripts_tenant_is_fraudulent_status", table_name="transcripts")
    op.drop_index("ix_transcripts_tenant_status_created_desc", table_name="transcripts")
    op.drop_index("ix_transcripts_tenant_student_created_desc", table_name="transcripts")
    op.drop_table("transcripts")
    op.drop_index("ix_document_uploads_filename_trgm", table_name="document_uploads")
    op.drop_table("document_uploads")
    op.drop_table("student_identifiers")
    op.drop_index("uq_students_tenant_external_student_id_not_null", table_name="students")
    op.drop_index("ix_students_tenant_latest_activity", table_name="students")
    op.drop_index("ix_students_tenant_advisor_stage", table_name="students")
    op.drop_index("ix_students_tenant_stage", table_name="students")
    op.drop_index("ix_students_tenant_last_first", table_name="students")
    op.drop_index("ix_students_first_name_trgm", table_name="students")
    op.drop_index("ix_students_last_name_trgm", table_name="students")
    op.drop_table("students")
    op.drop_table("programs")
    op.drop_index("ix_institutions_name_trgm", table_name="institutions")
    op.drop_table("institutions")
    op.drop_table("tenant_user_memberships")
    op.drop_table("app_users")
    op.drop_table("tenant_settings")
    op.drop_table("tenants")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at")
