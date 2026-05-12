import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    DocumentUpload,
    Institution,
    Tenant,
    Transcript,
    TranscriptProcessingFailure,
    TranscriptUploadBatch,
    TranscriptUploadBatchItem,
    TranscriptCourse,
    TranscriptDemographics,
    TranscriptGpaSummary,
    TranscriptParseRun,
    TranscriptTerm,
)
from app.db.session import get_database_url, get_session_factory
from app.models.api_models import ParseTranscriptResponse
from app.services.student_resolution import StudentResolutionService
from app.services.work_state_projector import WorkStateProjector
from app.utils.storage_utils import build_document_storage_key, build_pending_storage_key, slugify_storage_filename


class TranscriptPersistenceService:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory or get_session_factory
        self.student_resolution = StudentResolutionService()
        self.work_state_projector = WorkStateProjector(session_factory=self.session_factory)

    def is_enabled(self) -> bool:
        return bool(get_database_url())

    def create_processing_upload(
        self,
        filename: str,
        content: bytes,
        content_type: str | None,
        requested_document_type: str,
        use_bedrock: bool,
        tenant_id: str,
        uploaded_by_user_id: UUID | None = None,
    ) -> dict[str, str]:
        if not self.is_enabled():
            raise ValueError("Database is not configured.")

        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                tenant = self._get_tenant(session, tenant_id)
                now = datetime.now(timezone.utc)
                checksum = hashlib.sha256(content).hexdigest()

                upload = DocumentUpload(
                    tenant_id=tenant.id,
                    uploaded_by_user_id=uploaded_by_user_id,
                    original_filename=filename,
                    mime_type=content_type or "application/octet-stream",
                    file_size_bytes=len(content),
                    storage_bucket="direct-upload",
                    storage_key=build_pending_storage_key(filename),
                    checksum_sha256=checksum,
                    upload_status="processing",
                    uploaded_at=now,
                )
                session.add(upload)
                session.flush()

                transcript = Transcript(
                    tenant_id=tenant.id,
                    document_upload_id=upload.id,
                    student_id=None,
                    source_institution_id=None,
                    document_type=requested_document_type or "auto",
                    status="processing",
                    is_official=False,
                    is_finalized=False,
                    finalized_at=None,
                    finalized_by_user_id=None,
                    is_fraudulent=False,
                    fraud_flagged_at=None,
                    matched_at=None,
                    matched_by=None,
                    parser_confidence=None,
                    page_count=None,
                    notes=None,
                )
                session.add(transcript)
                session.flush()

                upload.storage_key = build_document_storage_key(str(transcript.id), filename)

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
                    response_json=None,
                    raw_text_excerpt=None,
                    warnings_json=[],
                    confidence_score=None,
                    started_at=now,
                    completed_at=None,
                    status="processing",
                    error_message=None,
                )
                session.add(parse_run)
                session.flush()

            return {
                "tenantId": str(tenant.id),
                "documentUploadId": str(upload.id),
                "transcriptId": str(transcript.id),
                "parseRunId": str(parse_run.id),
                "status": transcript.status,
            }

    def create_processing_upload_batch(
        self,
        files: list[dict[str, Any]],
        requested_document_type: str,
        use_bedrock: bool,
        tenant_id: str,
        uploaded_by_user_id: UUID | None = None,
        original_filename: str = "batch.zip",
    ) -> dict[str, Any]:
        if not self.is_enabled():
            raise ValueError("Database is not configured.")
        if not files:
            raise ValueError("ZIP archive did not contain any supported transcript files.")

        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                tenant = self._get_tenant(session, tenant_id)
                batch = TranscriptUploadBatch(
                    tenant_id=tenant.id,
                    uploaded_by_user_id=uploaded_by_user_id,
                    original_filename=original_filename,
                    file_count=len(files),
                    status="processing",
                )
                session.add(batch)
                session.flush()

                items: list[dict[str, str]] = []
                for index, file_info in enumerate(files):
                    upload_record = self._create_processing_upload_in_session(
                        session=session,
                        tenant=tenant,
                        filename=file_info["filename"],
                        content=file_info["content"],
                        content_type=file_info.get("content_type"),
                        requested_document_type=requested_document_type,
                        use_bedrock=use_bedrock,
                        uploaded_by_user_id=uploaded_by_user_id,
                    )
                    batch_item = TranscriptUploadBatchItem(
                        tenant_id=tenant.id,
                        batch_id=batch.id,
                        transcript_id=UUID(upload_record["transcriptId"]),
                        filename=file_info["filename"],
                        position=index,
                        status=upload_record["status"],
                        error_message=None,
                    )
                    session.add(batch_item)
                    items.append(
                        {
                            "filename": file_info["filename"],
                            "transcriptId": upload_record["transcriptId"],
                            "documentUploadId": upload_record["documentUploadId"],
                            "parseRunId": upload_record["parseRunId"],
                            "status": upload_record["status"],
                        }
                    )

            return {
                "batchId": str(batch.id),
                "status": batch.status,
                "totalFiles": len(items),
                "completedFiles": 0,
                "failedFiles": 0,
                "items": items,
            }

    def persist_upload(
        self,
        filename: str,
        content: bytes,
        content_type: str | None,
        requested_document_type: str,
        use_bedrock: bool,
        response_payload: dict[str, Any],
        tenant_id: str,
    ) -> dict[str, str]:
        if not self.is_enabled():
            return {}

        parsed = ParseTranscriptResponse(**response_payload)
        try:
            self._validate_parsed_transcript(parsed)
        except ValueError as exc:
            self._record_processing_failure_without_transcript(
                tenant_id=tenant_id,
                filename=filename,
                error_message=str(exc),
                details={
                    "document_type": requested_document_type,
                    "content_type": content_type,
                    "documentId": parsed.documentId,
                },
            )
            raise
        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                tenant = self._get_tenant(session, tenant_id)
                institution = self._find_or_create_institution(session, tenant.id, parsed.demographic.institutionName)
                now = datetime.now(timezone.utc)
                checksum = hashlib.sha256(content).hexdigest()
                storage_key = build_document_storage_key(parsed.documentId, filename)

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
                session.flush()
                resolved_student = self.student_resolution.ensure_student_for_transcript(
                    session=session,
                    tenant_id=tenant.id,
                    transcript=transcript,
                    demographics=demographics,
                )
                if resolved_student is None:
                    raise ValueError("Could not identify student from transcript.")

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
                self.work_state_projector.refresh_transcript_projection(
                    session,
                    tenant_id=tenant.id,
                    student_id=transcript.student_id,
                )

            return {
                "tenantId": str(tenant.id),
                "documentUploadId": str(upload.id),
                "transcriptId": str(transcript.id),
                "parseRunId": str(parse_run.id),
            }

    def complete_processing_upload(
        self,
        transcript_id: str,
        response_payload: dict[str, Any],
        tenant_id: str,
    ) -> dict[str, str]:
        if not self.is_enabled():
            raise ValueError("Database is not configured.")

        parsed = ParseTranscriptResponse(**response_payload)
        self._validate_parsed_transcript(parsed)
        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                tenant = self._get_tenant(session, tenant_id)
                transcript = self._get_transcript(session, transcript_id, tenant.id)
                upload = session.get(DocumentUpload, transcript.document_upload_id)
                parse_run = self._get_latest_parse_run(session, transcript.id, tenant.id)
                institution = self._find_or_create_institution(session, tenant.id, parsed.demographic.institutionName)
                now = datetime.now(timezone.utc)

                transcript.source_institution_id = institution.id if institution else None
                transcript.document_type = parsed.metadata.get("document_type") or transcript.document_type
                transcript.status = "completed"
                transcript.is_official = parsed.isOfficial
                transcript.is_finalized = parsed.isFinalized
                transcript.finalized_at = self._parse_datetime(parsed.finalizedAt)
                transcript.is_fraudulent = parsed.isFraudulent
                transcript.fraud_flagged_at = self._parse_datetime(parsed.fraudFlaggedAt)
                transcript.parser_confidence = self._to_decimal(parsed.metadata.get("parser_confidence"))
                transcript.page_count = self._page_count(parsed)
                transcript.notes = None

                upload.upload_status = "completed"
                self._update_batch_item_status(session, tenant.id, transcript.id, "completed", None)

                parse_run.response_json = parsed.model_dump(mode="json")
                parse_run.raw_text_excerpt = str(parsed.metadata.get("raw_text_excerpt") or "")
                parse_run.warnings_json = list(parsed.metadata.get("warnings") or [])
                parse_run.confidence_score = self._to_decimal(parsed.metadata.get("overall_confidence"))
                parse_run.completed_at = now
                parse_run.status = "completed"
                parse_run.error_message = None

                self._clear_transcript_artifacts(session, tenant.id, transcript.id)

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
                session.flush()
                resolved_student = self.student_resolution.ensure_student_for_transcript(
                    session=session,
                    tenant_id=tenant.id,
                    transcript=transcript,
                    demographics=demographics,
                )
                if resolved_student is None:
                    raise ValueError("Could not identify student from transcript.")

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

    def fail_processing_upload(self, transcript_id: str, tenant_id: str, error_message: str) -> None:
        if not self.is_enabled():
            raise ValueError("Database is not configured.")

        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                tenant = self._get_tenant(session, tenant_id)
                transcript = self._get_transcript(session, transcript_id, tenant.id)
                upload = session.get(DocumentUpload, transcript.document_upload_id)
                parse_run = self._get_latest_parse_run(session, transcript.id, tenant.id)

                transcript.status = "failed"
                transcript.notes = error_message
                upload.upload_status = "failed"
                parse_run.status = "failed"
                parse_run.completed_at = datetime.now(timezone.utc)
                parse_run.error_message = error_message
                self._update_batch_item_status(session, tenant.id, transcript.id, "failed", error_message)
                self._record_processing_failure(
                    session=session,
                    tenant_id=tenant.id,
                    transcript_id=transcript.id,
                    document_upload_id=upload.id,
                    filename=upload.original_filename,
                    error_message=error_message,
                    details={
                        "document_type": transcript.document_type,
                        "parse_run_id": str(parse_run.id) if parse_run else None,
                    },
                )
                self.work_state_projector.refresh_transcript_projection(
                    session,
                    tenant_id=tenant.id,
                    student_id=transcript.student_id,
                )

    def get_transcript_status(self, transcript_id: str, tenant_id: str) -> dict[str, Any]:
        if not self.is_enabled():
            raise ValueError("Database is not configured.")

        session_factory = self.session_factory()
        with session_factory() as session:
            tenant = self._get_tenant(session, tenant_id)
            transcript = self._get_transcript(session, transcript_id, tenant.id)
            upload = session.get(DocumentUpload, transcript.document_upload_id)
            parse_run = self._get_latest_parse_run(session, transcript.id, tenant.id)
            status = parse_run.status if parse_run else transcript.status
            return {
                "transcriptId": str(transcript.id),
                "documentUploadId": str(upload.id),
                "parseRunId": str(parse_run.id) if parse_run else None,
                "status": status,
                "error": parse_run.error_message if parse_run else None,
                "completed": status == "completed",
            }

    def get_upload_batch_status(self, batch_id: str, tenant_id: str) -> dict[str, Any]:
        if not self.is_enabled():
            raise ValueError("Database is not configured.")

        session_factory = self.session_factory()
        with session_factory() as session:
            tenant = self._get_tenant(session, tenant_id)
            batch = self._get_batch(session, batch_id, tenant.id)
            item_rows = session.execute(
                select(TranscriptUploadBatchItem, DocumentUpload, TranscriptParseRun)
                .join(Transcript, Transcript.id == TranscriptUploadBatchItem.transcript_id)
                .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
                .outerjoin(
                    TranscriptParseRun,
                    (TranscriptParseRun.transcript_id == TranscriptUploadBatchItem.transcript_id)
                    & (TranscriptParseRun.tenant_id == tenant.id),
                )
                .where(
                    TranscriptUploadBatchItem.tenant_id == tenant.id,
                    TranscriptUploadBatchItem.batch_id == batch.id,
                )
                .order_by(TranscriptUploadBatchItem.position.asc(), TranscriptParseRun.started_at.desc())
            ).all()

            latest_by_item: dict[UUID, tuple[TranscriptUploadBatchItem, DocumentUpload, TranscriptParseRun | None]] = {}
            for item, upload, parse_run in item_rows:
                latest_by_item.setdefault(item.id, (item, upload, parse_run))

            items: list[dict[str, Any]] = []
            completed_files = 0
            failed_files = 0
            active_files = 0
            for item, upload, parse_run in latest_by_item.values():
                status = parse_run.status if parse_run else item.status
                error = parse_run.error_message if parse_run and parse_run.error_message else item.error_message
                completed = status == "completed"
                if completed:
                    completed_files += 1
                if status == "failed":
                    failed_files += 1
                if status == "processing":
                    active_files += 1
                items.append(
                    {
                        "filename": item.filename,
                        "transcriptId": str(item.transcript_id),
                        "documentUploadId": str(upload.id),
                        "parseRunId": str(parse_run.id) if parse_run else None,
                        "status": status,
                        "error": error,
                        "completed": completed,
                        "startedAt": self._format_datetime(parse_run.started_at) if parse_run else None,
                        "completedAt": self._format_datetime(parse_run.completed_at) if parse_run else None,
                    }
                )

            if failed_files and completed_files + failed_files == len(items):
                batch_status = "completed_with_failures"
            elif completed_files == len(items):
                batch_status = "completed"
            elif failed_files > 0:
                batch_status = "processing"
            else:
                batch_status = "processing"

            if batch.status != batch_status:
                batch.status = batch_status
                session.commit()

            return {
                "batchId": str(batch.id),
                "status": batch_status,
                "totalFiles": len(items),
                "completedFiles": completed_files,
                "failedFiles": failed_files,
                "activeFiles": active_files,
                "items": items,
            }

    def get_transcript_result(self, transcript_id: str, tenant_id: str) -> dict[str, Any]:
        if not self.is_enabled():
            raise ValueError("Database is not configured.")

        session_factory = self.session_factory()
        with session_factory() as session:
            tenant = self._get_tenant(session, tenant_id)
            transcript = self._get_transcript(session, transcript_id, tenant.id)
            parse_run = self._get_latest_parse_run(session, transcript.id, tenant.id)

            if parse_run is None or parse_run.status != "completed" or not parse_run.response_json:
                raise ValueError("Transcript result is not ready.")

            return parse_run.response_json

    def _get_tenant(self, session: Session, tenant_id: str) -> Tenant:
        try:
            resolved_tenant_id = UUID(str(tenant_id))
        except ValueError as exc:
            raise ValueError("A valid tenant_id is required for persistence.") from exc

        tenant = (
            session.query(Tenant)
            .filter(Tenant.id == resolved_tenant_id, Tenant.status == "active")
            .one_or_none()
        )
        if tenant is None:
            raise ValueError("Tenant not found.")
        return tenant

    def _get_transcript(self, session: Session, transcript_id: str, tenant_id: UUID) -> Transcript:
        try:
            resolved_transcript_id = UUID(str(transcript_id))
        except ValueError as exc:
            raise ValueError("A valid transcript_id is required.") from exc

        transcript = (
            session.query(Transcript)
            .filter(Transcript.id == resolved_transcript_id, Transcript.tenant_id == tenant_id)
            .one_or_none()
        )
        if transcript is None:
            raise ValueError("Transcript not found.")
        return transcript

    def _get_latest_parse_run(self, session: Session, transcript_id: UUID, tenant_id: UUID) -> TranscriptParseRun | None:
        stmt = (
            select(TranscriptParseRun)
            .where(
                TranscriptParseRun.transcript_id == transcript_id,
                TranscriptParseRun.tenant_id == tenant_id,
            )
            .order_by(TranscriptParseRun.started_at.desc())
            .limit(1)
        )
        return session.execute(stmt).scalar_one_or_none()

    def _get_batch(self, session: Session, batch_id: str, tenant_id: UUID) -> TranscriptUploadBatch:
        try:
            resolved_batch_id = UUID(str(batch_id))
        except ValueError as exc:
            raise ValueError("A valid batch_id is required.") from exc

        batch = (
            session.query(TranscriptUploadBatch)
            .filter(TranscriptUploadBatch.id == resolved_batch_id, TranscriptUploadBatch.tenant_id == tenant_id)
            .one_or_none()
        )
        if batch is None:
            raise ValueError("Upload batch not found.")
        return batch

    def _update_batch_item_status(
        self,
        session: Session,
        tenant_id: UUID,
        transcript_id: UUID,
        status: str,
        error_message: str | None,
    ) -> None:
        item = (
            session.query(TranscriptUploadBatchItem)
            .filter(
                TranscriptUploadBatchItem.tenant_id == tenant_id,
                TranscriptUploadBatchItem.transcript_id == transcript_id,
            )
            .one_or_none()
        )
        if item is None:
            return
        item.status = status
        item.error_message = error_message

    def _clear_transcript_artifacts(self, session: Session, tenant_id: UUID, transcript_id: UUID) -> None:
        session.execute(
            delete(TranscriptCourse).where(
                TranscriptCourse.tenant_id == tenant_id,
                TranscriptCourse.transcript_id == transcript_id,
            )
        )
        session.execute(
            delete(TranscriptTerm).where(
                TranscriptTerm.tenant_id == tenant_id,
                TranscriptTerm.transcript_id == transcript_id,
            )
        )
        session.execute(
            delete(TranscriptGpaSummary).where(
                TranscriptGpaSummary.tenant_id == tenant_id,
                TranscriptGpaSummary.transcript_id == transcript_id,
            )
        )
        session.execute(
            delete(TranscriptDemographics).where(
                TranscriptDemographics.tenant_id == tenant_id,
                TranscriptDemographics.transcript_id == transcript_id,
            )
        )

    def _create_processing_upload_in_session(
        self,
        session: Session,
        tenant: Tenant,
        filename: str,
        content: bytes,
        content_type: str | None,
        requested_document_type: str,
        use_bedrock: bool,
        uploaded_by_user_id: UUID | None,
    ) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        checksum = hashlib.sha256(content).hexdigest()

        upload = DocumentUpload(
            tenant_id=tenant.id,
            uploaded_by_user_id=uploaded_by_user_id,
            original_filename=filename,
            mime_type=content_type or "application/octet-stream",
            file_size_bytes=len(content),
            storage_bucket="direct-upload",
            storage_key=build_pending_storage_key(filename),
            checksum_sha256=checksum,
            upload_status="processing",
            uploaded_at=now,
        )
        session.add(upload)
        session.flush()

        transcript = Transcript(
            tenant_id=tenant.id,
            document_upload_id=upload.id,
            student_id=None,
            source_institution_id=None,
            document_type=requested_document_type or "auto",
            status="processing",
            is_official=False,
            is_finalized=False,
            finalized_at=None,
            finalized_by_user_id=None,
            is_fraudulent=False,
            fraud_flagged_at=None,
            matched_at=None,
            matched_by=None,
            parser_confidence=None,
            page_count=None,
            notes=None,
        )
        session.add(transcript)
        session.flush()

        upload.storage_key = build_document_storage_key(str(transcript.id), filename)

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
            response_json=None,
            raw_text_excerpt=None,
            warnings_json=[],
            confidence_score=None,
            started_at=now,
            completed_at=None,
            status="processing",
            error_message=None,
        )
        session.add(parse_run)
        session.flush()

        return {
            "tenantId": str(tenant.id),
            "documentUploadId": str(upload.id),
            "transcriptId": str(transcript.id),
            "parseRunId": str(parse_run.id),
            "status": transcript.status,
        }

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

    def _validate_parsed_transcript(self, parsed: ParseTranscriptResponse) -> None:
        has_student_identity = bool(
            parsed.demographic.studentId
            or (parsed.demographic.firstName and parsed.demographic.lastName)
        )
        if not has_student_identity:
            raise ValueError("Could not identify student from transcript.")
        if not parsed.courses:
            raise ValueError("No courses were extracted from transcript.")

    def _record_processing_failure(
        self,
        session: Session,
        tenant_id: UUID,
        filename: str,
        error_message: str,
        details: dict[str, Any] | None = None,
        transcript_id: UUID | None = None,
        document_upload_id: UUID | None = None,
    ) -> None:
        session.add(
            TranscriptProcessingFailure(
                tenant_id=tenant_id,
                transcript_id=transcript_id,
                document_upload_id=document_upload_id,
                filename=filename,
                failure_code=self._failure_code_from_message(error_message),
                failure_message=error_message,
                failure_details=details or {},
            )
        )

    def _record_processing_failure_without_transcript(
        self,
        tenant_id: str,
        filename: str,
        error_message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not self.is_enabled():
            return
        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                tenant = self._get_tenant(session, tenant_id)
                self._record_processing_failure(
                    session=session,
                    tenant_id=tenant.id,
                    filename=filename,
                    error_message=error_message,
                    details=details,
                )

    def _failure_code_from_message(self, error_message: str) -> str:
        lowered = (error_message or "").lower()
        if "identify student" in lowered:
            return "student_resolution_failed"
        if "no courses were extracted" in lowered:
            return "course_mapping_failed"
        return "processing_failed"

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
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%d-%b-%Y"):
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

    def _format_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

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
        return slugify_storage_filename(value)
