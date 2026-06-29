from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AdmissionsDecision, Application, ApplicationStatusHistory, Prospect, Student
from app.models.application_models import (
    AdmissionsDecisionCreateRequest,
    AdmissionsDecisionRecord,
    ApplicationCreateRequest,
    ApplicationRecord,
    ApplicationStatusUpdateRequest,
)


class ApplicationNotFoundError(LookupError):
    pass


class ApplicationValidationError(ValueError):
    pass


class ApplicationService:
    def list_applications(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        student_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ApplicationRecord], int]:
        stmt = select(Application).where(Application.tenant_id == tenant_id)
        count_stmt = select(func.count()).select_from(Application).where(Application.tenant_id == tenant_id)
        if student_id:
            parsed_student_id = self._parse_uuid(student_id, "studentId")
            stmt = stmt.where(Application.student_id == parsed_student_id)
            count_stmt = count_stmt.where(Application.student_id == parsed_student_id)
        if status:
            stmt = stmt.where(Application.status == status)
            count_stmt = count_stmt.where(Application.status == status)
        rows = db.execute(stmt.order_by(Application.created_at.desc()).limit(limit).offset(offset)).scalars().all()
        total = int(db.execute(count_stmt).scalar_one())
        return [self._to_record(row) for row in rows], total

    def get_application(self, *, db: Session, tenant_id: UUID, application_id: str) -> ApplicationRecord:
        application = self._get_application_row(db=db, tenant_id=tenant_id, application_id=application_id)
        return self._to_record(application)

    def create_application(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        payload: ApplicationCreateRequest,
    ) -> ApplicationRecord:
        student_id = self._parse_uuid(payload.studentId, "studentId")
        student = db.get(Student, student_id)
        if student is None or student.tenant_id != tenant_id:
            raise ApplicationValidationError("Student not found for this tenant.")

        prospect_id = self._optional_uuid(payload.prospectId, "prospectId")
        if prospect_id:
            prospect = db.get(Prospect, prospect_id)
            if prospect is None or prospect.tenant_id != tenant_id:
                raise ApplicationValidationError("Prospect not found for this tenant.")

        application = Application(
            tenant_id=tenant_id,
            student_id=student_id,
            prospect_id=prospect_id,
            application_number=payload.applicationNumber or self._generate_application_number(),
            application_type=payload.applicationType,
            student_type=payload.studentType,
            population=payload.population,
            admit_term_code=payload.admitTermCode,
            entry_term_code=payload.entryTermCode,
            program_id=self._optional_uuid(payload.programId, "programId"),
            campus_id=self._optional_uuid(payload.campusId, "campusId"),
            modality=payload.modality,
            status=payload.status,
        )
        db.add(application)
        db.flush()
        self._record_status_history(
            db=db,
            tenant_id=tenant_id,
            application=application,
            from_status=None,
            to_status=payload.status,
            reason="application_created",
            actor_user_id=actor_user_id,
        )
        db.commit()
        db.refresh(application)
        return self._to_record(application)

    def update_status(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        application_id: str,
        payload: ApplicationStatusUpdateRequest,
    ) -> ApplicationRecord:
        application = self._get_application_row(db=db, tenant_id=tenant_id, application_id=application_id)
        previous_status = application.status
        application.status = payload.status
        application.updated_at = datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        if payload.status == "submitted" and application.submitted_at is None:
            application.submitted_at = now
        if payload.status in {"complete", "completed"} and application.completed_at is None:
            application.completed_at = now
        self._record_status_history(
            db=db,
            tenant_id=tenant_id,
            application=application,
            from_status=previous_status,
            to_status=payload.status,
            reason=payload.reason,
            actor_user_id=actor_user_id,
        )
        db.commit()
        db.refresh(application)
        return self._to_record(application)

    def create_decision(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        application_id: str,
        payload: AdmissionsDecisionCreateRequest,
    ) -> AdmissionsDecisionRecord:
        application = self._get_application_row(db=db, tenant_id=tenant_id, application_id=application_id)
        now = datetime.now(timezone.utc)
        decision = AdmissionsDecision(
            tenant_id=tenant_id,
            student_id=application.student_id,
            application_id=application.id,
            decision_code=payload.decisionCode,
            decision_reason=payload.decisionReason,
            decided_by_user_id=actor_user_id,
            decided_at=now,
            effective_term=payload.effectiveTerm,
            conditions_json=payload.conditions,
            letter_template_id=self._optional_uuid(payload.letterTemplateId, "letterTemplateId"),
            released_to_student_at=now if payload.releaseToStudent else None,
        )
        application.decision_status = payload.decisionCode
        application.decision_at = now
        application.updated_at = now
        db.add(decision)
        db.commit()
        db.refresh(decision)
        return AdmissionsDecisionRecord(
            id=str(decision.id),
            applicationId=str(decision.application_id),
            studentId=str(decision.student_id),
            decisionCode=decision.decision_code,
            decisionReason=decision.decision_reason,
            decidedAt=decision.decided_at,
            effectiveTerm=decision.effective_term,
            conditions=decision.conditions_json,
            releasedToStudentAt=decision.released_to_student_at,
        )

    def _get_application_row(self, *, db: Session, tenant_id: UUID, application_id: str) -> Application:
        parsed_application_id = self._parse_uuid(application_id, "applicationId")
        application = db.get(Application, parsed_application_id)
        if application is None or application.tenant_id != tenant_id:
            raise ApplicationNotFoundError("Application not found.")
        return application

    def _record_status_history(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        application: Application,
        from_status: str | None,
        to_status: str,
        reason: str | None,
        actor_user_id: UUID | None,
    ) -> None:
        db.add(
            ApplicationStatusHistory(
                tenant_id=tenant_id,
                application_id=application.id,
                student_id=application.student_id,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                actor_user_id=actor_user_id,
            )
        )

    def _to_record(self, application: Application) -> ApplicationRecord:
        return ApplicationRecord(
            id=str(application.id),
            studentId=str(application.student_id),
            prospectId=str(application.prospect_id) if application.prospect_id else None,
            applicationNumber=application.application_number,
            applicationType=application.application_type,
            studentType=application.student_type,
            population=application.population,
            admitTermCode=application.admit_term_code,
            entryTermCode=application.entry_term_code,
            programId=str(application.program_id) if application.program_id else None,
            campusId=str(application.campus_id) if application.campus_id else None,
            modality=application.modality,
            status=application.status,
            submittedAt=application.submitted_at,
            completedAt=application.completed_at,
            decisionStatus=application.decision_status,
            decisionAt=application.decision_at,
            createdAt=application.created_at,
            updatedAt=application.updated_at,
        )

    def _generate_application_number(self) -> str:
        return f"APP-{uuid4().hex[:12].upper()}"

    def _parse_uuid(self, value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except ValueError as exc:
            raise ApplicationValidationError(f"{field_name} must be a valid UUID.") from exc

    def _optional_uuid(self, value: str | None, field_name: str) -> UUID | None:
        if not value:
            return None
        return self._parse_uuid(value, field_name)
