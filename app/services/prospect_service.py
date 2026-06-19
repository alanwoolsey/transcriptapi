from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AppUser,
    AuditEvent,
    Institution,
    Program,
    Prospect,
    ProspectFitResult,
    ProspectNextAction,
    ProspectSourceReference,
    ProspectTranscriptUpload,
    Student,
)
from app.db.session import get_session_factory
from app.models.ops_models import WorkItemOwner, WorkItemReason, WorkTodayItemResponse
from app.models.prospect_models import (
    ProspectConvertResponse,
    ProspectCounselor,
    ProspectFitResponse,
    ProspectInquiryRequest,
    ProspectInquiryResponse,
    ProspectNextStep,
    ProspectProgramFit,
    ProspectRecordResponse,
    ProspectSignal,
    ProspectUploadResponse,
    ProspectUploadStatusResponse,
)
from app.services.pipeline_status import canonical_pipeline_status


class ProspectNotFoundError(Exception):
    pass


class ProspectValidationError(Exception):
    pass


class ProspectService:
    VALID_LIFECYCLE_STAGES = {"prospect", "inquiry", "applicant", "withdrawn", "duplicate_candidate"}
    VALID_STATUSES = {
        "new",
        "needs_follow_up",
        "transcript_received",
        "fit_ready",
        "application_started",
        "converted",
        "duplicate_candidate",
        "archived",
    }
    VALID_UPLOAD_STATUSES = {"received", "processing", "fit_ready", "needs_review", "failed"}
    VALID_ACTION_CODES = {
        "start_application",
        "upload_transcript",
        "schedule_counselor",
        "answer_question",
        "review_transfer_fit",
        "resolve_duplicate",
    }

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def create_inquiry(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        payload: ProspectInquiryRequest,
    ) -> ProspectInquiryResponse:
        self._validate_inquiry(payload)
        now = datetime.now(timezone.utc)
        email = self._normalize_email(payload.email)
        owner = self._default_owner(db, tenant_id, actor_user_id)
        duplicate_student = self._find_duplicate_student(db, tenant_id, email, payload.phone)
        prospect = self._find_duplicate_prospect(db, tenant_id, email, payload.phone, payload.externalReferenceId)
        duplicate_candidate = duplicate_student is not None and (prospect is None or prospect.student_id != duplicate_student.id)

        if prospect is None:
            prospect = Prospect(
                tenant_id=tenant_id,
                first_name=payload.firstName.strip(),
                last_name=payload.lastName.strip(),
                email=email,
                population=self._normalize_population(payload.population),
                lifecycle_stage="duplicate_candidate" if duplicate_candidate else "inquiry",
                status="duplicate_candidate" if duplicate_candidate else "new",
                owner_user_id=owner.id if owner else actor_user_id,
                source=payload.source.strip() or "manual_entry",
                source_category=payload.sourceCategory.strip() or "direct",
                consent_captured=payload.consent,
                created_at=now,
                updated_at=now,
            )
            db.add(prospect)
            db.flush()

        prospect.first_name = payload.firstName.strip()
        prospect.last_name = payload.lastName.strip()
        prospect.email = email
        prospect.phone = self._blank_to_none(payload.phone)
        prospect.population = self._normalize_population(payload.population)
        prospect.program_interest = self._blank_to_none(payload.programInterest)
        prospect.term_interest = self._blank_to_none(payload.termInterest)
        prospect.prior_institution = self._blank_to_none(payload.priorInstitution)
        prospect.source = payload.source.strip() or prospect.source
        prospect.source_category = payload.sourceCategory.strip() or prospect.source_category
        prospect.campaign = self._blank_to_none(payload.campaign)
        prospect.consent_captured = payload.consent
        prospect.question = self._blank_to_none(payload.question)
        prospect.owner_user_id = prospect.owner_user_id or (owner.id if owner else actor_user_id)
        prospect.student_id = prospect.student_id or (duplicate_student.id if duplicate_student else None)
        prospect.lifecycle_stage = "duplicate_candidate" if duplicate_candidate else "inquiry"
        prospect.status = self._initial_status(payload, duplicate_candidate)
        prospect.updated_at = now

        db.add(
            ProspectSourceReference(
                tenant_id=tenant_id,
                prospect_id=prospect.id,
                source=prospect.source,
                source_category=prospect.source_category,
                campaign=prospect.campaign,
                external_reference_id=self._blank_to_none(payload.externalReferenceId),
                metadata_json={
                    "transcriptUploadId": payload.transcriptUploadId,
                    "transcriptFilename": payload.transcriptFilename,
                },
                captured_at=now,
            )
        )

        upload = self._resolve_upload(db, tenant_id, payload.transcriptUploadId, email)
        if upload is not None:
            upload.prospect_id = prospect.id
            upload.status = "fit_ready"
            upload.updated_at = now

        fit = self._upsert_fit_result(db, tenant_id, prospect, upload)
        action = self._upsert_next_action(db, tenant_id, prospect, fit, owner)
        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type="prospect",
            entity_id=prospect.id,
            action="prospect_inquiry_created",
            metadata={"email": email, "status": prospect.status, "duplicateCandidate": duplicate_candidate},
        )
        db.commit()
        return ProspectInquiryResponse(prospect=self._serialize_prospect(db, tenant_id, prospect, fit, action, upload))

    def create_transcript_upload(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        email: str,
        population: str,
        program_interest: str | None,
        term_interest: str | None,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ProspectUploadResponse:
        if not content:
            raise ProspectValidationError("Transcript upload file is required.")
        normalized_email = self._normalize_email(email)
        safe_filename = self._safe_filename(filename)
        upload = ProspectTranscriptUpload(
            tenant_id=tenant_id,
            prospect_id=None,
            email=normalized_email,
            filename=safe_filename,
            content_type=content_type or "application/octet-stream",
            file_size=len(content),
            storage_uri="pending",
            status="received",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(upload)
        db.flush()
        storage_uri = self._store_upload(tenant_id, upload.id, safe_filename, content)
        upload.storage_uri = storage_uri
        upload.status = "fit_ready"
        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type="prospect_transcript_upload",
            entity_id=upload.id,
            action="prospect_transcript_uploaded",
            metadata={
                "email": normalized_email,
                "population": population,
                "programInterest": program_interest,
                "termInterest": term_interest,
                "filename": safe_filename,
            },
        )
        db.commit()
        return ProspectUploadResponse(uploadId=self._public_id("upl", upload.id), status=upload.status, filename=upload.filename)

    def get_upload_status(self, tenant_id: UUID, upload_id: str) -> ProspectUploadStatusResponse:
        session_factory = self.session_factory()
        with session_factory() as db:
            upload = self._get_upload(db, tenant_id, upload_id)
            return ProspectUploadStatusResponse(
                uploadId=self._public_id("upl", upload.id),
                status=upload.status,
                processingRunId=(str(upload.processing_run_id) if upload.processing_run_id else None),
                message=self._upload_status_message(upload.status),
            )

    def get_fit(self, tenant_id: UUID, prospect_id: str) -> ProspectFitResponse:
        session_factory = self.session_factory()
        with session_factory() as db:
            prospect = self._get_prospect(db, tenant_id, prospect_id)
            fit = self._latest_fit(db, tenant_id, prospect.id)
            action = self._latest_action(db, tenant_id, prospect.id)
            return ProspectFitResponse(
                programFit=self._serialize_fit(fit),
                missingItems=list(fit.missing_items_json or []) if fit else self._missing_items(prospect),
                signals=[ProspectSignal(**item) for item in list(fit.signals_json or [])] if fit else self._signals(prospect),
                nextStep=self._serialize_next_step(action),
            )

    def convert_application(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        prospect_id: str,
    ) -> ProspectConvertResponse:
        prospect = self._get_prospect(db, tenant_id, prospect_id)
        if prospect.status == "converted" and prospect.student_id:
            return ProspectConvertResponse(studentId=str(prospect.student_id), prospectId=self._public_id("pro", prospect.id), status=prospect.status)

        student = self._find_duplicate_student(db, tenant_id, prospect.email, prospect.phone)
        if student is None and prospect.student_id is not None:
            student = db.execute(
                select(Student).where(Student.tenant_id == tenant_id, Student.id == prospect.student_id).limit(1)
            ).scalar_one_or_none()
        if student is None:
            student = self._create_student_from_prospect(db, tenant_id, prospect)

        prospect.student_id = student.id
        prospect.lifecycle_stage = "applicant"
        prospect.status = "converted"
        prospect.updated_at = datetime.now(timezone.utc)
        for action in db.execute(
            select(ProspectNextAction).where(
                ProspectNextAction.tenant_id == tenant_id,
                ProspectNextAction.prospect_id == prospect.id,
                ProspectNextAction.status == "open",
            )
        ).scalars().all():
            action.status = "completed"
            action.completed_at = datetime.now(timezone.utc)
        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type="prospect",
            entity_id=prospect.id,
            action="prospect_converted_to_application",
            metadata={"studentId": str(student.id)},
        )
        db.commit()
        return ProspectConvertResponse(studentId=str(student.id), prospectId=self._public_id("pro", prospect.id), status=prospect.status)

    def get_today_work_items(self, tenant_id: UUID, *, limit: int = 50) -> list[WorkTodayItemResponse]:
        session_factory = self.session_factory()
        with session_factory() as db:
            rows = db.execute(
                select(Prospect, ProspectNextAction, ProspectFitResult, AppUser)
                .join(ProspectNextAction, ProspectNextAction.prospect_id == Prospect.id)
                .outerjoin(ProspectFitResult, ProspectFitResult.prospect_id == Prospect.id)
                .outerjoin(AppUser, AppUser.id == Prospect.owner_user_id)
                .where(
                    Prospect.tenant_id == tenant_id,
                    ProspectNextAction.tenant_id == tenant_id,
                    ProspectNextAction.status == "open",
                    Prospect.status.in_(["new", "needs_follow_up", "transcript_received", "fit_ready", "duplicate_candidate"]),
                )
                .order_by(Prospect.updated_at.desc())
                .limit(limit)
            ).all()
            seen: set[UUID] = set()
            items: list[WorkTodayItemResponse] = []
            for prospect, action, fit, owner in rows:
                if prospect.id in seen:
                    continue
                seen.add(prospect.id)
                items.append(self._build_work_item(prospect, action, fit, owner))
            return items

    def _validate_inquiry(self, payload: ProspectInquiryRequest) -> None:
        required = [payload.firstName, payload.lastName, payload.email, payload.population, payload.source, payload.sourceCategory]
        if any(not value or not str(value).strip() for value in required):
            raise ProspectValidationError("First name, last name, email, population, source, and source category are required.")
        if not payload.consent:
            raise ProspectValidationError("Consent is required to create a follow-up-capable prospect.")
        self._normalize_email(payload.email)

    def _normalize_email(self, email: str) -> str:
        normalized = (email or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ProspectValidationError("A valid email is required.")
        return normalized

    def _normalize_population(self, population: str) -> str:
        normalized = (population or "").strip().lower().replace("-", "_").replace(" ", "_")
        return normalized or "prospect"

    def _initial_status(self, payload: ProspectInquiryRequest, duplicate_candidate: bool) -> str:
        if duplicate_candidate:
            return "duplicate_candidate"
        if payload.transcriptUploadId or payload.transcriptFilename:
            return "fit_ready"
        if payload.question and payload.question.strip():
            return "needs_follow_up"
        return "new"

    def _find_duplicate_prospect(self, db: Session, tenant_id: UUID, email: str, phone: str | None, external_reference_id: str | None) -> Prospect | None:
        predicates = [func.lower(Prospect.email) == email.lower()]
        if phone and phone.strip():
            predicates.append(Prospect.phone == phone.strip())
        if external_reference_id and external_reference_id.strip():
            source_ref = db.execute(
                select(ProspectSourceReference.prospect_id)
                .where(
                    ProspectSourceReference.tenant_id == tenant_id,
                    ProspectSourceReference.external_reference_id == external_reference_id.strip(),
                )
                .limit(1)
            ).scalar_one_or_none()
            if source_ref is not None:
                predicates.append(Prospect.id == source_ref)
        return db.execute(select(Prospect).where(Prospect.tenant_id == tenant_id, or_(*predicates)).limit(1)).scalar_one_or_none()

    def _find_duplicate_student(self, db: Session, tenant_id: UUID, email: str, phone: str | None) -> Student | None:
        predicates = [func.lower(Student.email) == email.lower()]
        if phone and phone.strip():
            predicates.append(Student.phone == phone.strip())
        return db.execute(select(Student).where(Student.tenant_id == tenant_id, or_(*predicates)).limit(1)).scalar_one_or_none()

    def _resolve_upload(self, db: Session, tenant_id: UUID, upload_id: str | None, email: str) -> ProspectTranscriptUpload | None:
        if not upload_id:
            return None
        upload = self._get_upload(db, tenant_id, upload_id)
        if upload.email.lower() != email.lower():
            raise ProspectValidationError("Transcript upload does not belong to this prospect email.")
        return upload

    def _get_upload(self, db: Session, tenant_id: UUID, upload_id: str) -> ProspectTranscriptUpload:
        resolved_id = self._parse_public_id(upload_id, "upl")
        upload = db.execute(
            select(ProspectTranscriptUpload).where(ProspectTranscriptUpload.tenant_id == tenant_id, ProspectTranscriptUpload.id == resolved_id).limit(1)
        ).scalar_one_or_none()
        if upload is None:
            raise ProspectNotFoundError("Transcript upload not found.")
        return upload

    def _get_prospect(self, db: Session, tenant_id: UUID, prospect_id: str) -> Prospect:
        resolved_id = self._parse_public_id(prospect_id, "pro")
        prospect = db.execute(select(Prospect).where(Prospect.tenant_id == tenant_id, Prospect.id == resolved_id).limit(1)).scalar_one_or_none()
        if prospect is None:
            raise ProspectNotFoundError("Prospect not found.")
        return prospect

    def _parse_public_id(self, value: str, prefix: str) -> UUID:
        normalized = value.strip()
        if normalized.startswith(f"{prefix}_"):
            normalized = normalized[len(prefix) + 1 :]
        try:
            return UUID(normalized)
        except ValueError as exc:
            raise ProspectValidationError(f"Invalid {prefix} identifier.") from exc

    def _public_id(self, prefix: str, value: UUID) -> str:
        return f"{prefix}_{value}"

    def _upsert_fit_result(
        self,
        db: Session,
        tenant_id: UUID,
        prospect: Prospect,
        upload: ProspectTranscriptUpload | None,
    ) -> ProspectFitResult:
        now = datetime.now(timezone.utc)
        existing = self._latest_fit(db, tenant_id, prospect.id)
        program = prospect.program_interest or "Admissions fit preview"
        fit_score = self._fit_score(prospect, upload)
        transfer_credits = self._transfer_credits(prospect, upload)
        confidence = 0.82 if upload else 0.62
        missing_items = self._missing_items(prospect)
        signals = [signal.model_dump() for signal in self._signals(prospect)]
        if existing is None:
            existing = ProspectFitResult(tenant_id=tenant_id, prospect_id=prospect.id, program=program, fit_score=fit_score, confidence=confidence)
            db.add(existing)
        existing.transcript_upload_id = upload.id if upload else existing.transcript_upload_id
        existing.program = program
        existing.fit_score = fit_score
        existing.confidence = confidence
        existing.transfer_credits = transfer_credits
        existing.estimated_completion = "2.1 years" if prospect.population == "transfer" else "3.8 years"
        existing.scholarship_potential = "$8.5k-$11k" if fit_score >= 85 else ("$3k-$6k" if fit_score >= 70 else None)
        existing.missing_items_json = missing_items
        existing.signals_json = signals
        existing.computed_at = now
        return existing

    def _upsert_next_action(
        self,
        db: Session,
        tenant_id: UUID,
        prospect: Prospect,
        fit: ProspectFitResult,
        owner: AppUser | None,
    ) -> ProspectNextAction:
        code, label = self._next_action(prospect, fit)
        action = db.execute(
            select(ProspectNextAction).where(
                ProspectNextAction.tenant_id == tenant_id,
                ProspectNextAction.prospect_id == prospect.id,
                ProspectNextAction.status == "open",
            ).limit(1)
        ).scalar_one_or_none()
        if action is None:
            action = ProspectNextAction(tenant_id=tenant_id, prospect_id=prospect.id, status="open", created_at=datetime.now(timezone.utc))
            db.add(action)
        action.code = code
        action.label = label
        action.url = f"/apply?prospectId={self._public_id('pro', prospect.id)}" if code == "start_application" else None
        action.owner_user_id = prospect.owner_user_id or (owner.id if owner else None)
        return action

    def _next_action(self, prospect: Prospect, fit: ProspectFitResult) -> tuple[str, str]:
        if prospect.status == "duplicate_candidate":
            return ("resolve_duplicate", "Resolve duplicate")
        if prospect.question:
            return ("answer_question", "Answer prospect question")
        if fit.fit_score >= 80:
            return ("start_application", "Start application")
        if prospect.status in {"transcript_received", "fit_ready"}:
            return ("review_transfer_fit", "Review transfer fit")
        return ("upload_transcript", "Upload transcript")

    def _latest_fit(self, db: Session, tenant_id: UUID, prospect_id: UUID) -> ProspectFitResult | None:
        return db.execute(
            select(ProspectFitResult)
            .where(ProspectFitResult.tenant_id == tenant_id, ProspectFitResult.prospect_id == prospect_id)
            .order_by(ProspectFitResult.computed_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _latest_action(self, db: Session, tenant_id: UUID, prospect_id: UUID) -> ProspectNextAction | None:
        return db.execute(
            select(ProspectNextAction)
            .where(ProspectNextAction.tenant_id == tenant_id, ProspectNextAction.prospect_id == prospect_id, ProspectNextAction.status == "open")
            .order_by(ProspectNextAction.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _serialize_prospect(
        self,
        db: Session,
        tenant_id: UUID,
        prospect: Prospect,
        fit: ProspectFitResult | None,
        action: ProspectNextAction | None,
        upload: ProspectTranscriptUpload | None,
    ) -> ProspectRecordResponse:
        owner = db.execute(select(AppUser).where(AppUser.id == prospect.owner_user_id).limit(1)).scalar_one_or_none() if prospect.owner_user_id else None
        latest_upload = upload or db.execute(
            select(ProspectTranscriptUpload)
            .where(ProspectTranscriptUpload.tenant_id == tenant_id, ProspectTranscriptUpload.prospect_id == prospect.id)
            .order_by(ProspectTranscriptUpload.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return ProspectRecordResponse(
            prospectId=self._public_id("pro", prospect.id),
            studentId=(str(prospect.student_id) if prospect.student_id else None),
            studentName=f"{prospect.first_name} {prospect.last_name}".strip(),
            status=prospect.status,
            population=prospect.population,
            programInterest=prospect.program_interest,
            termInterest=prospect.term_interest,
            source=prospect.source,
            programFit=self._serialize_fit(fit),
            nextStep=self._serialize_next_step(action),
            counselor=ProspectCounselor(
                id=(str(owner.id) if owner else None),
                name=(owner.display_name if owner else "Admissions counselor"),
                email=(owner.email if owner else None),
            ),
            transcriptStatus=(latest_upload.status if latest_upload else None),
            missingItems=list(fit.missing_items_json or []) if fit else self._missing_items(prospect),
            signals=[ProspectSignal(**item) for item in list(fit.signals_json or [])] if fit else self._signals(prospect),
        )

    def _serialize_fit(self, fit: ProspectFitResult | None) -> ProspectProgramFit | None:
        if fit is None:
            return None
        return ProspectProgramFit(
            program=fit.program,
            fitScore=fit.fit_score,
            confidence=float(fit.confidence),
            transferCredits=fit.transfer_credits,
            estimatedCompletion=fit.estimated_completion,
            scholarshipPotential=fit.scholarship_potential,
        )

    def _serialize_next_step(self, action: ProspectNextAction | None) -> ProspectNextStep | None:
        if action is None:
            return None
        return ProspectNextStep(code=action.code, label=action.label, url=action.url)

    def _build_work_item(self, prospect: Prospect, action: ProspectNextAction, fit: ProspectFitResult | None, owner: AppUser | None) -> WorkTodayItemResponse:
        reason_code = self._reason_code(prospect, fit)
        queue_group = self._queue_group(prospect, reason_code)
        pipeline_status = canonical_pipeline_status(prospect.lifecycle_stage)
        return WorkTodayItemResponse(
            id=f"prospect_{prospect.id.hex[:12]}",
            studentId=self._public_id("pro", prospect.id),
            studentName=f"{prospect.first_name} {prospect.last_name}".strip(),
            population=prospect.population,
            stage=pipeline_status,
            pipelineStatus=pipeline_status,
            completionPercent=0,
            section="attention",
            priority="urgent" if queue_group in {"new_inquiries", "duplicate_candidate"} else "today",
            priorityScore=86 if fit and fit.fit_score >= 80 else 72,
            owner=WorkItemOwner(id=(str(owner.id) if owner else None), name=(owner.display_name if owner else "Unassigned")),
            reasonToAct=WorkItemReason(code=reason_code, label=self._reason_label(reason_code)),
            suggestedAction=WorkItemReason(code=action.code, label=action.label),
            readiness={"state": prospect.status, "label": self._title_case(prospect.status), "tone": "medium"},
            blockingItems=[],
            checklistSummary=None,
            program=prospect.program_interest or "Program interest pending",
            institutionGoal=prospect.prior_institution or "Prior institution pending",
            risk="Medium" if prospect.status == "duplicate_candidate" else "Low",
            lastActivity=self._relative_time(prospect.updated_at),
            nextAction=action.label,
            currentOwnerAgent=None,
            currentStage=prospect.lifecycle_stage,
            recommendedAgent="document_agent" if action.code in {"upload_transcript", "review_transfer_fit"} else "decision_agent",
            queueGroup=queue_group,
            updatedAt=prospect.updated_at.isoformat() if prospect.updated_at else None,
        )

    def _reason_code(self, prospect: Prospect, fit: ProspectFitResult | None) -> str:
        if prospect.status == "duplicate_candidate":
            return "duplicate_candidate"
        if prospect.question:
            return "question_needs_answer"
        if prospect.status in {"transcript_received", "fit_ready"} and fit and fit.fit_score >= 80:
            return "high_fit_prospect"
        if prospect.status in {"transcript_received", "fit_ready"}:
            return "transcript_first_lead"
        return "new_inquiry"

    def _queue_group(self, prospect: Prospect, reason_code: str) -> str:
        if reason_code == "duplicate_candidate":
            return "duplicate_candidate"
        if reason_code == "new_inquiry":
            return "new_inquiries"
        if reason_code == "question_needs_answer":
            return "no_first_touch"
        return "started_not_submitted"

    def _reason_label(self, reason_code: str) -> str:
        labels = {
            "new_inquiry": "New inquiry needs first touch",
            "transcript_first_lead": "Transcript-first lead needs review",
            "high_fit_prospect": "High-fit prospect is ready for application follow-up",
            "question_needs_answer": "Prospect question needs counselor response",
            "duplicate_candidate": "Duplicate candidate needs resolution",
        }
        return labels.get(reason_code, self._title_case(reason_code))

    def _create_student_from_prospect(self, db: Session, tenant_id: UUID, prospect: Prospect) -> Student:
        institution = self._ensure_institution(db, tenant_id, prospect.prior_institution)
        program = self._ensure_program(db, tenant_id, institution.id if institution else None, prospect.program_interest)
        student = Student(
            tenant_id=tenant_id,
            external_student_id=None,
            first_name=prospect.first_name,
            last_name=prospect.last_name,
            preferred_name=prospect.first_name,
            email=prospect.email,
            phone=prospect.phone,
            target_program_id=(program.id if program else None),
            target_institution_id=(institution.id if institution else None),
            advisor_user_id=prospect.owner_user_id,
            current_stage="applicant",
            risk_level="medium" if prospect.status == "duplicate_candidate" else "low",
            summary=f"Converted from prospect inquiry sourced by {prospect.source}.",
            latest_activity_at=datetime.now(timezone.utc),
        )
        db.add(student)
        db.flush()
        return student

    def _ensure_institution(self, db: Session, tenant_id: UUID, name: str | None) -> Institution | None:
        if not name:
            return None
        institution = db.execute(select(Institution).where(Institution.tenant_id == tenant_id, Institution.name == name).limit(1)).scalar_one_or_none()
        if institution is None:
            institution = Institution(tenant_id=tenant_id, name=name, country="US")
            db.add(institution)
            db.flush()
        return institution

    def _ensure_program(self, db: Session, tenant_id: UUID, institution_id: UUID | None, name: str | None) -> Program | None:
        if not name:
            return None
        program = db.execute(select(Program).where(Program.tenant_id == tenant_id, Program.institution_id == institution_id, Program.name == name).limit(1)).scalar_one_or_none()
        if program is None:
            program = Program(tenant_id=tenant_id, institution_id=institution_id, name=name, is_active=True)
            db.add(program)
            db.flush()
        return program

    def _default_owner(self, db: Session, tenant_id: UUID, actor_user_id: UUID) -> AppUser | None:
        return db.execute(
            select(AppUser)
            .where(AppUser.tenant_id == tenant_id, AppUser.id == actor_user_id, AppUser.is_active.is_(True))
            .limit(1)
        ).scalar_one_or_none() or db.execute(
            select(AppUser).where(AppUser.tenant_id == tenant_id, AppUser.is_active.is_(True)).order_by(AppUser.created_at.asc()).limit(1)
        ).scalar_one_or_none()

    def _fit_score(self, prospect: Prospect, upload: ProspectTranscriptUpload | None) -> int:
        score = 68
        if prospect.population == "transfer":
            score += 12
        if upload is not None:
            score += 8
        if prospect.program_interest:
            score += 5
        return max(40, min(95, score))

    def _transfer_credits(self, prospect: Prospect, upload: ProspectTranscriptUpload | None) -> int | None:
        if prospect.population != "transfer":
            return None
        return 42 if upload else 24

    def _missing_items(self, prospect: Prospect) -> list[str]:
        items = ["Application form"]
        if prospect.status not in {"transcript_received", "fit_ready", "converted"}:
            items.insert(0, "Unofficial transcript")
        items.append("Official transcript")
        return items

    def _signals(self, prospect: Prospect) -> list[ProspectSignal]:
        signals = [
            ProspectSignal(label="Population", value=prospect.population),
            ProspectSignal(label="Source", value=prospect.source),
        ]
        if prospect.campaign:
            signals.append(ProspectSignal(label="Campaign", value=prospect.campaign))
        if prospect.prior_institution:
            signals.append(ProspectSignal(label="Prior institution", value=prospect.prior_institution))
        return signals

    def _store_upload(self, tenant_id: UUID, upload_id: UUID, filename: str, content: bytes) -> str:
        root = Path(settings.document_storage_dir).resolve() / "prospects" / str(tenant_id) / str(upload_id)
        root.mkdir(parents=True, exist_ok=True)
        target = root / filename
        target.write_bytes(content)
        return str(target)

    def _safe_filename(self, filename: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "transcript.pdf").strip("._")
        return cleaned or "transcript.pdf"

    def _upload_status_message(self, status: str) -> str:
        return {
            "received": "Transcript upload was received.",
            "processing": "Transcript processing is in progress.",
            "fit_ready": "Fit preview is ready.",
            "needs_review": "Transcript needs review.",
            "failed": "Transcript processing failed.",
        }.get(status, "Transcript upload status is available.")

    def _write_audit_event(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        entity_type: str,
        entity_id: UUID,
        action: str,
        metadata: dict,
    ) -> None:
        db.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                category="ProspectPortal",
                action=action,
                success=True,
                error_message=None,
                payload_json={"metadata_json": metadata},
                correlation_id=None,
                source="ProspectService",
                occurred_at=datetime.now(timezone.utc),
            )
        )

    def _blank_to_none(self, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    def _title_case(self, value: str | None) -> str:
        return (value or "").replace("_", " ").title()

    def _relative_time(self, value: datetime | None) -> str:
        if value is None:
            return "Unknown"
        delta = datetime.now(timezone.utc) - value
        seconds = max(0, int(delta.total_seconds()))
        if seconds < 3600:
            return f"{max(1, seconds // 60)} min ago"
        if seconds < 86400:
            return f"{seconds // 3600} hours ago"
        return f"{seconds // 86400} days ago"
