from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Student, Transcript, TranscriptDemographics, TrustFlag, WorkflowCase
from app.db.session import get_session_factory
from app.models.workflow_models import WorkflowListItem


@dataclass
class _TranscriptWorkflowBundle:
    transcript: Transcript
    demographics: TranscriptDemographics | None
    student: Student | None


class WorkflowService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def list_workflows(self, tenant_id: UUID) -> list[WorkflowListItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            case_items = self._list_workflow_cases(session, tenant_id)
            if case_items:
                return case_items
            return self._list_transcript_derived_workflows(session, tenant_id)

    def _list_workflow_cases(self, session: Session, tenant_id: UUID) -> list[WorkflowListItem]:
        stmt = (
            select(WorkflowCase, Student, TranscriptDemographics, AppUser)
            .outerjoin(Student, Student.id == WorkflowCase.student_id)
            .outerjoin(Transcript, Transcript.id == WorkflowCase.transcript_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(AppUser, AppUser.id == WorkflowCase.owner_user_id)
            .where(WorkflowCase.tenant_id == tenant_id)
            .order_by(WorkflowCase.opened_at.desc())
        )
        items: list[WorkflowListItem] = []
        now = datetime.now(timezone.utc)
        for workflow_case, student, demographics, owner in session.execute(stmt).all():
            items.append(
                WorkflowListItem(
                    id=str(workflow_case.id),
                    student=self._student_name(student, demographics),
                    studentId=self._student_identifier(student, demographics, workflow_case.id),
                    institution=self._institution_name(demographics),
                    status=self._title_case(workflow_case.status or workflow_case.case_type),
                    owner=owner.display_name if owner else self._owner_from_queue(workflow_case.queue_name),
                    age=self._relative_time(workflow_case.opened_at, now),
                    priority=self._title_case(workflow_case.priority),
                    reason=workflow_case.reason or "Workflow item requires review.",
                )
            )
        return items

    def _list_transcript_derived_workflows(self, session: Session, tenant_id: UUID) -> list[WorkflowListItem]:
        stmt = (
            select(Transcript, TranscriptDemographics, Student)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(Student, Student.id == Transcript.student_id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        bundles = [
            _TranscriptWorkflowBundle(transcript=transcript, demographics=demographics, student=student)
            for transcript, demographics, student in session.execute(stmt).all()
        ]
        trust_flags = session.execute(
            select(TrustFlag).where(TrustFlag.tenant_id == tenant_id).order_by(TrustFlag.detected_at.desc())
        ).scalars().all()
        latest_trust_by_transcript: dict[UUID, TrustFlag] = {}
        for trust_flag in trust_flags:
            latest_trust_by_transcript.setdefault(trust_flag.transcript_id, trust_flag)

        items: list[WorkflowListItem] = []
        now = datetime.now(timezone.utc)
        for bundle in bundles:
            item = self._workflow_item_from_bundle(bundle, latest_trust_by_transcript.get(bundle.transcript.id), now)
            if item:
                items.append(item)
        return items

    def _workflow_item_from_bundle(
        self,
        bundle: _TranscriptWorkflowBundle,
        trust_flag: TrustFlag | None,
        now: datetime,
    ) -> WorkflowListItem | None:
        transcript = bundle.transcript
        confidence = float(transcript.parser_confidence or 0.0)

        if trust_flag or transcript.is_fraudulent:
            return WorkflowListItem(
                id=f"WF-{str(transcript.id)[:8]}",
                student=self._student_name(bundle.student, bundle.demographics),
                studentId=self._student_identifier(bundle.student, bundle.demographics, transcript.id),
                institution=self._institution_name(bundle.demographics),
                status="Trust hold",
                owner="Trust Agent",
                age=self._relative_time((trust_flag.detected_at if trust_flag else transcript.created_at), now),
                priority=self._title_case(trust_flag.severity if trust_flag else "high"),
                reason=(trust_flag.reason if trust_flag else "Document trust signals require manual review."),
            )

        if transcript.status in {"processing", "failed"}:
            return WorkflowListItem(
                id=f"WF-{str(transcript.id)[:8]}",
                student=self._student_name(bundle.student, bundle.demographics),
                studentId=self._student_identifier(bundle.student, bundle.demographics, transcript.id),
                institution=self._institution_name(bundle.demographics),
                status="Need evidence" if transcript.status == "failed" else "In progress",
                owner="Decision Agent",
                age=self._relative_time(transcript.created_at, now),
                priority="Medium",
                reason=transcript.notes or ("Transcript processing failed and needs follow-up." if transcript.status == "failed" else "Transcript processing is still running."),
            )

        if confidence < 0.85:
            return WorkflowListItem(
                id=f"WF-{str(transcript.id)[:8]}",
                student=self._student_name(bundle.student, bundle.demographics),
                studentId=self._student_identifier(bundle.student, bundle.demographics, transcript.id),
                institution=self._institution_name(bundle.demographics),
                status="Human review",
                owner="Decision Agent",
                age=self._relative_time(transcript.created_at, now),
                priority="Medium",
                reason="Parse confidence is below the auto-certify threshold and needs staff review.",
            )

        return WorkflowListItem(
            id=f"WF-{str(transcript.id)[:8]}",
            student=self._student_name(bundle.student, bundle.demographics),
            studentId=self._student_identifier(bundle.student, bundle.demographics, transcript.id),
            institution=self._institution_name(bundle.demographics),
            status="Connector ready",
            owner="Banner Connector",
            age=self._relative_time(transcript.created_at, now),
            priority="Low",
            reason="High-confidence transcript is ready for downstream release.",
        )

    def _student_name(self, student: Student | None, demographics: TranscriptDemographics | None) -> str:
        if student:
            parts = [student.first_name or "", student.last_name or ""]
            name = " ".join(part for part in parts if part.strip()).strip()
            if name:
                return name
        if demographics:
            parts = [demographics.student_first_name or "", demographics.student_last_name or ""]
            name = " ".join(part for part in parts if part.strip()).strip()
            if name:
                return name
        return "Unknown Student"

    def _student_identifier(self, student: Student | None, demographics: TranscriptDemographics | None, fallback) -> str:
        if student and student.external_student_id:
            return student.external_student_id
        if demographics and demographics.student_external_id:
            return demographics.student_external_id
        return f"STU-{str(fallback).replace('-', '')[:8].upper()}"

    def _institution_name(self, demographics: TranscriptDemographics | None) -> str:
        if demographics and demographics.institution_name and demographics.institution_name.strip():
            return demographics.institution_name.strip()
        return "Unknown institution"

    def _owner_from_queue(self, queue_name: str | None) -> str:
        if not queue_name:
            return "Unassigned"
        normalized = queue_name.lower()
        if "trust" in normalized:
            return "Trust Agent"
        if "connector" in normalized:
            return "Banner Connector"
        return "Decision Agent"

    def _relative_time(self, occurred_at: datetime | None, now: datetime) -> str:
        if not occurred_at:
            return "Unknown"
        delta = now - occurred_at
        minutes = int(delta.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes} min"
        hours = int(minutes // 60)
        if hours < 24:
            return f"{hours} hr"
        days = int(hours // 24)
        return f"{days} day"

    def _title_case(self, value: str | None) -> str:
        if not value:
            return ""
        return value.replace("_", " ").replace("-", " ").title()
