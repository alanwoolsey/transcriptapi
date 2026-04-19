import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    DocumentUpload,
    Institution,
    Tenant,
    Transcript,
    TranscriptCourse,
    TranscriptDemographics,
    TranscriptGpaSummary,
    TranscriptParseRun,
    TranscriptTerm,
)
from app.db.session import get_database_url, get_session_factory
from app.models.api_models import ParseTranscriptResponse


class TranscriptPersistenceService:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory or get_session_factory

    def is_enabled(self) -> bool:
        return bool(get_database_url())

    def persist_upload(
        self,
        filename: str,
        content: bytes,
        content_type: str | None,
        requested_document_type: str,
        use_bedrock: bool,
        response_payload: dict[str, Any],
    ) -> dict[str, str]:
        if not self.is_enabled():
            return {}

        parsed = ParseTranscriptResponse(**response_payload)
        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                tenant = self._ensure_default_tenant(session)
                institution = self._find_or_create_institution(session, tenant.id, parsed.demographic.institutionName)
                now = datetime.now(timezone.utc)
                checksum = hashlib.sha256(content).hexdigest()
                storage_key = f"{parsed.documentId}/{self._slugify(filename)}"

                upload = DocumentUpload(
                    tenant_id=tenant.id,
                    original_filename=filename,
                    mime_type=content_type or "application/octet-stream",
                    file_size_bytes=len(content),
                    storage_bucket="direct-upload",
                    storage_key=storage_key,
                    checksum_sha256=checksum,
                    upload_status="parsed",
                    uploaded_at=now,
                )
                session.add(upload)
                session.flush()

                transcript = Transcript(
                    tenant_id=tenant.id,
                    document_upload_id=upload.id,
                    student_id=None,
                    source_institution_id=institution.id if institution else None,
                    document_type=parsed.metadata.get("document_type") or requested_document_type or "auto",
                    status="parsed",
                    is_official=parsed.isOfficial,
                    is_finalized=parsed.isFinalized,
                    finalized_at=self._parse_datetime(parsed.finalizedAt),
                    finalized_by_user_id=None,
                    is_fraudulent=parsed.isFraudulent,
                    fraud_flagged_at=self._parse_datetime(parsed.fraudFlaggedAt),
                    matched_at=None,
                    matched_by=None,
                    parser_confidence=self._to_decimal(parsed.metadata.get("parser_confidence")),
                    page_count=self._page_count(parsed),
                    notes=None,
                )
                session.add(transcript)
                session.flush()

                parse_run = TranscriptParseRun(
                    tenant_id=tenant.id,
                    transcript_id=transcript.id,
                    parser_name="transcript_pipeline",
                    parser_version="v1",
                    request_json={
                        "filename": filename,
                        "content_type": content_type,
                        "requested_document_type": requested_document_type,
                        "use_bedrock": use_bedrock,
                    },
                    response_json=parsed.model_dump(mode="json"),
                    raw_text_excerpt=str(parsed.metadata.get("raw_text_excerpt") or ""),
                    warnings_json=list(parsed.metadata.get("warnings") or []),
                    confidence_score=self._to_decimal(parsed.metadata.get("overall_confidence")),
                    started_at=now,
                    completed_at=now,
                    status="completed",
                    error_message=None,
                )
                session.add(parse_run)

                demographics = TranscriptDemographics(
                    tenant_id=tenant.id,
                    transcript_id=transcript.id,
                    student_first_name=self._empty_to_none(parsed.demographic.firstName),
                    student_middle_name=self._empty_to_none(parsed.demographic.middleName),
                    student_last_name=self._empty_to_none(parsed.demographic.lastName),
                    student_external_id=self._empty_to_none(parsed.demographic.studentId),
                    date_of_birth=self._parse_date(parsed.demographic.dateOfBirth),
                    institution_name=self._empty_to_none(parsed.demographic.institutionName),
                    institution_city=self._empty_to_none(parsed.demographic.institutionCity),
                    institution_state=self._empty_to_none(parsed.demographic.institutionState),
                    institution_postal_code=self._empty_to_none(parsed.demographic.institutionPostalCode),
                    institution_country=self._empty_to_none(parsed.demographic.institutionCountry),
                    cumulative_gpa=self._to_decimal(parsed.demographic.cumulativeGpa),
                    weighted_gpa=self._to_decimal(parsed.demographic.weightedGpa),
                    unweighted_gpa=self._to_decimal(parsed.demographic.unweightedGpa),
                    total_credits_attempted=self._to_decimal(parsed.demographic.totalCreditsAttempted),
                    total_credits_earned=self._to_decimal(parsed.demographic.totalCreditsEarned),
                    total_grade_points=self._to_decimal(parsed.demographic.totalGradePoints),
                    degree_awarded=self._empty_to_none(parsed.demographic.degreeAwarded),
                    graduation_date=self._parse_date(parsed.demographic.graduationDate),
                    is_official=parsed.isOfficial,
                )
                session.add(demographics)

                gpa_summary = TranscriptGpaSummary(
                    tenant_id=tenant.id,
                    transcript_id=transcript.id,
                    units_earned=self._to_decimal(parsed.grandGPA.unitsEarned),
                    simple_gpa_points=self._to_decimal(parsed.grandGPA.simpleGPA),
                    cumulative_gpa=self._to_decimal(parsed.grandGPA.cumulativeGPA),
                    weighted_gpa=self._to_decimal(parsed.grandGPA.weightedGPA),
                )
                session.add(gpa_summary)

                term_lookup = self._persist_terms(session, tenant_id=tenant.id, transcript_id=transcript.id, parsed=parsed)
                self._persist_courses(
                    session,
                    tenant_id=tenant.id,
                    transcript_id=transcript.id,
                    source_institution_id=institution.id if institution else None,
                    parsed=parsed,
                    term_lookup=term_lookup,
                )
                self._persist_audit_events(session, tenant_id=tenant.id, transcript_id=transcript.id, parsed=parsed)

            return {
                "tenantId": str(tenant.id),
                "documentUploadId": str(upload.id),
                "transcriptId": str(transcript.id),
                "parseRunId": str(parse_run.id),
            }

    def _ensure_default_tenant(self, session: Session) -> Tenant:
        tenant = session.query(Tenant).filter(Tenant.slug == "default").one_or_none()
        if tenant:
            return tenant
        tenant = Tenant(name="Default Tenant", slug="default", status="active", primary_region=None, data_retention_days=None)
        session.add(tenant)
        session.flush()
        return tenant

    def _find_or_create_institution(self, session: Session, tenant_id: UUID, institution_name: str) -> Institution | None:
        if not institution_name.strip():
            return None
        institution = (
            session.query(Institution)
            .filter(Institution.tenant_id == tenant_id, Institution.name == institution_name.strip())
            .one_or_none()
        )
        if institution:
            return institution
        institution = Institution(
            tenant_id=tenant_id,
            name=institution_name.strip(),
            external_code=None,
            ceeb_code=None,
            city=None,
            state=None,
            country=None,
            institution_type=None,
        )
        session.add(institution)
        session.flush()
        return institution

    def _persist_terms(self, session: Session, tenant_id: UUID, transcript_id: UUID, parsed: ParseTranscriptResponse) -> dict[tuple[str, str], TranscriptTerm]:
        term_lookup: dict[tuple[str, str], TranscriptTerm] = {}
        ordered_terms: list[tuple[str, str, float | None, float | None, float | None]] = []
        for term_gpa in parsed.termGPAs:
            ordered_terms.append(
                (
                    term_gpa.year or "",
                    term_gpa.term or "",
                    term_gpa.simpleUnitsEarned,
                    term_gpa.simplePoints,
                    term_gpa.simpleGPA,
                )
            )
        for course in parsed.courses:
            key = (course.year or "", course.term or "")
            if key not in {(year, term) for year, term, *_ in ordered_terms}:
                ordered_terms.append((key[0], key[1], None, None, None))

        for index, (year, term, units, points, gpa) in enumerate(ordered_terms):
            term_row = TranscriptTerm(
                tenant_id=tenant_id,
                transcript_id=transcript_id,
                term_name=term or year or f"Term {index + 1}",
                academic_year=self._empty_to_none(year),
                units_earned=self._to_decimal(units),
                grade_points=self._to_decimal(points),
                term_gpa=self._to_decimal(gpa),
                display_order=index,
            )
            session.add(term_row)
            session.flush()
            term_lookup[(year, term)] = term_row
        return term_lookup

    def _persist_courses(
        self,
        session: Session,
        tenant_id: UUID,
        transcript_id: UUID,
        source_institution_id: UUID | None,
        parsed: ParseTranscriptResponse,
        term_lookup: dict[tuple[str, str], TranscriptTerm],
    ) -> None:
        for course in parsed.courses:
            term_row = term_lookup.get((course.year or "", course.term or ""))
            session.add(
                TranscriptCourse(
                    tenant_id=tenant_id,
                    transcript_id=transcript_id,
                    term_id=term_row.id if term_row else None,
                    source_institution_id=source_institution_id,
                    subject_code=self._empty_to_none(course.subject),
                    course_code=self._empty_to_none(course.courseId),
                    course_level=self._empty_to_none(course.courseLevel),
                    course_title=course.courseTitle or "",
                    credits_attempted=self._to_decimal(course.creditAttempted or course.credit),
                    credits_earned=self._to_decimal(course.credit),
                    grade_alpha=self._empty_to_none(course.grade),
                    grade_points=self._to_decimal(course.gradePoints),
                    course_gpa=self._to_decimal(course.courseGpa),
                    term_name=self._empty_to_none(course.term),
                    academic_year=self._empty_to_none(course.year),
                    page_number=course.pageNumber,
                    mapping_status=self._empty_to_none(course.mappingStatus),
                    transfer_status=self._empty_to_none(course.transferStatus),
                    repeat_flag=self._truthy(course.repeat),
                    raw_course_json=course.model_dump(mode="json"),
                )
            )

    def _persist_audit_events(self, session: Session, tenant_id: UUID, transcript_id: UUID, parsed: ParseTranscriptResponse) -> None:
        for audit in parsed.audit:
            entity_id = None
            try:
                entity_id = UUID(str(audit.entityId))
            except Exception:
                entity_id = transcript_id
            session.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    actor_user_id=None,
                    entity_type=audit.entityType or "Document",
                    entity_id=entity_id,
                    category=audit.category or "Document",
                    action=audit.action or "Ready Completed",
                    success=audit.success,
                    error_message=self._empty_to_none(audit.errorMessage),
                    payload_json=self._safe_json(audit.payloadJson),
                    correlation_id=self._empty_to_none(audit.correlationId),
                    source=self._empty_to_none(audit.source),
                    occurred_at=self._parse_datetime(audit.occurredOnUtc) or datetime.now(timezone.utc),
                )
            )

    def _page_count(self, parsed: ParseTranscriptResponse) -> int | None:
        page_numbers = [course.pageNumber for course in parsed.courses if course.pageNumber]
        return max(page_numbers) if page_numbers else None

    def _to_decimal(self, value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value).replace(",", ""))
        except Exception:
            return None

    def _parse_date(self, value: str | None):
        if not value:
            return None
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_datetime(self, value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _safe_json(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except Exception:
            return {"raw": value}

    def _empty_to_none(self, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def _truthy(self, value: str | None) -> bool:
        return str(value or "").strip().lower() in {"1", "true", "yes", "y", "repeat", "repl", "r"}

    def _slugify(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "upload.bin"
