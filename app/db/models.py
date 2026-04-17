import uuid
from datetime import date, datetime

from sqlalchemy import JSON, BIGINT, BOOLEAN, DATE, DATETIME, NUMERIC, TEXT, TIMESTAMP, UUID, Boolean, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    primary_region: Mapped[str | None] = mapped_column(Text)
    data_retention_days: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    default_document_type: Mapped[str | None] = mapped_column(Text)
    use_bedrock_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    student_match_strategy: Mapped[str | None] = mapped_column(Text)
    queue_sla_hours: Mapped[int | None] = mapped_column(Integer)
    settings_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    email: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    cognito_sub: Mapped[str | None] = mapped_column(Text, unique=True)
    identity_provider: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class TenantUserMembership(Base):
    __tablename__ = "tenant_user_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user_memberships_tenant_id_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    external_code: Mapped[str | None] = mapped_column(Text)
    ceeb_code: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    institution_type: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Program(Base):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("tenant_id", "institution_id", "name", name="uq_programs_tenant_id_institution_id_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    program_code: Mapped[str | None] = mapped_column(Text)
    degree_type: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    external_student_id: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str | None] = mapped_column(Text)
    middle_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    preferred_name: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    target_program_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("programs.id", ondelete="SET NULL"))
    target_institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="SET NULL"))
    advisor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    current_stage: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'low'"))
    summary: Mapped[str | None] = mapped_column(Text)
    latest_cumulative_gpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    accepted_credits: Mapped[float | None] = mapped_column(Numeric(8, 2))
    latest_activity_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_students_tenant_last_first", Student.tenant_id, Student.last_name, Student.first_name)
Index("ix_students_tenant_stage", Student.tenant_id, Student.current_stage)
Index("ix_students_tenant_advisor_stage", Student.tenant_id, Student.advisor_user_id, Student.current_stage)
Index("ix_students_tenant_latest_activity", Student.tenant_id, Student.latest_activity_at.desc())
Index(
    "uq_students_tenant_external_student_id_not_null",
    Student.tenant_id,
    Student.external_student_id,
    unique=True,
    postgresql_where=text("external_student_id IS NOT NULL"),
)


class StudentIdentifier(Base):
    __tablename__ = "student_identifiers"
    __table_args__ = (UniqueConstraint("tenant_id", "identifier_type", "identifier_value", name="uq_student_identifiers_lookup"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    identifier_type: Mapped[str] = mapped_column(Text, nullable=False)
    identifier_value: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class DocumentUpload(Base):
    __tablename__ = "document_uploads"
    __table_args__ = (UniqueConstraint("tenant_id", "storage_bucket", "storage_key", name="uq_document_uploads_tenant_id_storage_bucket_storage_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    storage_bucket: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    storage_version_id: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    upload_status: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    document_upload_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_uploads.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="SET NULL"))
    source_institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="SET NULL"))
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    finalized_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finalized_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    is_fraudulent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fraud_flagged_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    matched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    matched_by: Mapped[str | None] = mapped_column(Text)
    parser_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2))
    page_count: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_transcripts_tenant_student_created_desc", Transcript.tenant_id, Transcript.student_id, Transcript.created_at.desc())
Index("ix_transcripts_tenant_status_created_desc", Transcript.tenant_id, Transcript.status, Transcript.created_at.desc())
Index("ix_transcripts_tenant_is_fraudulent_status", Transcript.tenant_id, Transcript.is_fraudulent, Transcript.status)


class TranscriptParseRun(Base):
    __tablename__ = "transcript_parse_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    parser_name: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str | None] = mapped_column(Text)
    request_json: Mapped[dict | None] = mapped_column(JSONB)
    response_json: Mapped[dict | None] = mapped_column(JSONB)
    raw_text_excerpt: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_parse_runs_tenant_transcript_started_desc", TranscriptParseRun.tenant_id, TranscriptParseRun.transcript_id, TranscriptParseRun.started_at.desc())


class TranscriptDemographics(Base):
    __tablename__ = "transcript_demographics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, unique=True)
    student_first_name: Mapped[str | None] = mapped_column(Text)
    student_middle_name: Mapped[str | None] = mapped_column(Text)
    student_last_name: Mapped[str | None] = mapped_column(Text)
    student_external_id: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    institution_name: Mapped[str | None] = mapped_column(Text)
    institution_city: Mapped[str | None] = mapped_column(Text)
    institution_state: Mapped[str | None] = mapped_column(Text)
    institution_postal_code: Mapped[str | None] = mapped_column(Text)
    institution_country: Mapped[str | None] = mapped_column(Text)
    cumulative_gpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    weighted_gpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    unweighted_gpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    total_credits_attempted: Mapped[float | None] = mapped_column(Numeric(8, 2))
    total_credits_earned: Mapped[float | None] = mapped_column(Numeric(8, 2))
    total_grade_points: Mapped[float | None] = mapped_column(Numeric(10, 2))
    degree_awarded: Mapped[str | None] = mapped_column(Text)
    graduation_date: Mapped[date | None] = mapped_column(Date)
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class TranscriptTerm(Base):
    __tablename__ = "transcript_terms"
    __table_args__ = (UniqueConstraint("transcript_id", "display_order", name="uq_transcript_terms_transcript_id_display_order"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    term_name: Mapped[str] = mapped_column(Text, nullable=False)
    academic_year: Mapped[str | None] = mapped_column(Text)
    units_earned: Mapped[float | None] = mapped_column(Numeric(8, 2))
    grade_points: Mapped[float | None] = mapped_column(Numeric(10, 2))
    term_gpa: Mapped[float | None] = mapped_column(Numeric(5, 4))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class TranscriptCourse(Base):
    __tablename__ = "transcript_courses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    term_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("transcript_terms.id", ondelete="SET NULL"))
    source_institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="SET NULL"))
    subject_code: Mapped[str | None] = mapped_column(Text)
    course_code: Mapped[str | None] = mapped_column(Text)
    course_level: Mapped[str | None] = mapped_column(Text)
    course_title: Mapped[str] = mapped_column(Text, nullable=False)
    credits_attempted: Mapped[float | None] = mapped_column(Numeric(8, 2))
    credits_earned: Mapped[float | None] = mapped_column(Numeric(8, 2))
    grade_alpha: Mapped[str | None] = mapped_column(Text)
    grade_points: Mapped[float | None] = mapped_column(Numeric(6, 2))
    course_gpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    term_name: Mapped[str | None] = mapped_column(Text)
    academic_year: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    mapping_status: Mapped[str | None] = mapped_column(Text)
    transfer_status: Mapped[str | None] = mapped_column(Text)
    repeat_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    raw_course_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_transcript_courses_tenant_transcript", TranscriptCourse.tenant_id, TranscriptCourse.transcript_id)
Index("ix_transcript_courses_tenant_course_code", TranscriptCourse.tenant_id, TranscriptCourse.course_code)
Index("ix_transcript_courses_tenant_source_institution_course_code", TranscriptCourse.tenant_id, TranscriptCourse.source_institution_id, TranscriptCourse.course_code)


class TranscriptGpaSummary(Base):
    __tablename__ = "transcript_gpa_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, unique=True)
    units_earned: Mapped[float | None] = mapped_column(Numeric(8, 2))
    simple_gpa_points: Mapped[float | None] = mapped_column(Numeric(10, 2))
    cumulative_gpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    weighted_gpa: Mapped[float | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class TranscriptStudentMatch(Base):
    __tablename__ = "transcript_student_matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    match_status: Mapped[str] = mapped_column(Text, nullable=False)
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    match_reason: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_matches_tenant_student_current", TranscriptStudentMatch.tenant_id, TranscriptStudentMatch.student_id, TranscriptStudentMatch.is_current)
Index("ix_matches_tenant_transcript_current", TranscriptStudentMatch.tenant_id, TranscriptStudentMatch.transcript_id, TranscriptStudentMatch.is_current)


class WorkflowCase(Base):
    __tablename__ = "workflow_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="SET NULL"))
    transcript_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="SET NULL"))
    case_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'medium'"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    queue_name: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_workflow_cases_tenant_queue_status_priority", WorkflowCase.tenant_id, WorkflowCase.queue_name, WorkflowCase.status, WorkflowCase.priority)
Index("ix_workflow_cases_tenant_owner_status", WorkflowCase.tenant_id, WorkflowCase.owner_user_id, WorkflowCase.status)
Index("ix_workflow_cases_tenant_opened_at", WorkflowCase.tenant_id, WorkflowCase.opened_at)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workflow_case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_cases.id", ondelete="SET NULL"))
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="SET NULL"))
    transcript_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="SET NULL"))
    event_category: Mapped[str] = mapped_column(Text, nullable=False)
    event_action: Mapped[str] = mapped_column(Text, nullable=False)
    event_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_workflow_events_tenant_student_event_time_desc", WorkflowEvent.tenant_id, WorkflowEvent.student_id, WorkflowEvent.event_time.desc())
Index("ix_workflow_events_tenant_transcript_event_time_desc", WorkflowEvent.tenant_id, WorkflowEvent.transcript_id, WorkflowEvent.event_time.desc())


class TrustFlag(Base):
    __tablename__ = "trust_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="SET NULL"))
    flag_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    detected_by: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_trust_flags_tenant_status_severity_detected_desc", TrustFlag.tenant_id, TrustFlag.status, TrustFlag.severity, TrustFlag.detected_at.desc())
Index("ix_trust_flags_tenant_transcript_status", TrustFlag.tenant_id, TrustFlag.transcript_id, TrustFlag.status)


class StudentNote(Base):
    __tablename__ = "student_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="SET NULL"))
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    note_type: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class StudentTask(Base):
    __tablename__ = "student_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="SET NULL"))
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    due_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_student_tasks_tenant_student_status", StudentTask.tenant_id, StudentTask.student_id, StudentTask.status)
Index("ix_student_tasks_tenant_assigned_status", StudentTask.tenant_id, StudentTask.assigned_to_user_id, StudentTask.status)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="SET NULL"))
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    category: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    correlation_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


Index("ix_audit_events_tenant_entity_type_entity_id_occurred_desc", AuditEvent.tenant_id, AuditEvent.entity_type, AuditEvent.entity_id, AuditEvent.occurred_at.desc())
Index("ix_audit_events_tenant_occurred_desc", AuditEvent.tenant_id, AuditEvent.occurred_at.desc())
Index("ix_audit_events_correlation_id", AuditEvent.correlation_id)
