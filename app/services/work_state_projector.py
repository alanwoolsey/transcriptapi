from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Student, StudentWorkState
from app.db.session import get_session_factory


class WorkStateProjector:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def ensure_tenant_projection(self, tenant_id: UUID) -> None:
        session_factory = self.session_factory()
        with session_factory() as session:
            projected_count = session.execute(
                select(func.count()).select_from(StudentWorkState).where(StudentWorkState.tenant_id == tenant_id)
            ).scalar_one()
        if projected_count:
            return
        self.rebuild_tenant_projection(tenant_id)

    def get_projection_status(self, tenant_id: UUID) -> dict[str, object]:
        session_factory = self.session_factory()
        with session_factory() as session:
            projected_students = session.execute(
                select(func.count()).select_from(StudentWorkState).where(StudentWorkState.tenant_id == tenant_id)
            ).scalar_one()
            total_students = session.execute(
                select(func.count()).select_from(Student).where(Student.tenant_id == tenant_id)
            ).scalar_one()
            last_projected_at = session.execute(
                select(func.max(StudentWorkState.projected_at)).where(StudentWorkState.tenant_id == tenant_id)
            ).scalar_one()
            next_student = session.execute(
                select(Student.id)
                .outerjoin(
                    StudentWorkState,
                    (StudentWorkState.tenant_id == Student.tenant_id) & (StudentWorkState.student_id == Student.id),
                )
                .where(Student.tenant_id == tenant_id, StudentWorkState.id.is_(None))
                .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc(), Student.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            remaining_students = max(0, int(total_students or 0) - int(projected_students or 0))
        return {
            "projectedStudents": int(projected_students or 0),
            "totalStudents": int(total_students or 0),
            "ready": bool(total_students == projected_students and total_students is not None),
            "lastProjectedAt": last_projected_at,
            "remainingStudents": remaining_students,
            "nextCursor": (str(next_student) if next_student is not None else None),
        }

    def rebuild_tenant_projection(self, tenant_id: UUID) -> int:
        from app.services.admissions_ops_service import AdmissionsOpsService

        admissions_ops = AdmissionsOpsService(session_factory=self.session_factory)
        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                session.execute(delete(StudentWorkState).where(StudentWorkState.tenant_id == tenant_id))
                students = session.execute(
                    select(Student)
                    .where(Student.tenant_id == tenant_id)
                    .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc())
                ).scalars().all()
                for student in students:
                    context = admissions_ops._ensure_student_state_for_student(session, tenant_id, student)
                    item = admissions_ops._build_work_item(session, tenant_id, context)
                    state = StudentWorkState(
                        tenant_id=tenant_id,
                        student_id=student.id,
                        student_identifier=item.studentId,
                        student_name=item.studentName,
                        population=item.population,
                        stage=item.stage,
                        completion_percent=item.completionPercent,
                        priority=item.priority,
                        priority_score=item.priorityScore,
                        section=item.section,
                        owner_user_id=UUID(item.owner.id) if item.owner.id else None,
                        owner_name=item.owner.name,
                        reason_code=item.reasonToAct.code,
                        reason_label=item.reasonToAct.label,
                        suggested_action_code=item.suggestedAction.code,
                        suggested_action_label=item.suggestedAction.label,
                        readiness_json=item.readiness or {},
                        blocking_items_json=[entry.model_dump(mode="json") for entry in item.blockingItems],
                        checklist_summary_json=item.checklistSummary.model_dump(mode="json"),
                        fit_score=item.fitScore,
                        deposit_likelihood=item.depositLikelihood,
                        program=item.program,
                        institution_goal=item.institutionGoal,
                        risk=item.risk,
                        last_activity_at=self._parse_iso_datetime(item.updatedAt),
                        projected_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    session.add(state)
                return len(students)

    def reset_tenant_projection(self, tenant_id: UUID) -> None:
        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                session.execute(delete(StudentWorkState).where(StudentWorkState.tenant_id == tenant_id))

    def rebuild_tenant_projection_chunk(
        self,
        tenant_id: UUID,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, object]:
        from app.services.admissions_ops_service import AdmissionsOpsService

        admissions_ops = AdmissionsOpsService(session_factory=self.session_factory)
        session_factory = self.session_factory()
        with session_factory() as session:
            with session.begin():
                stmt = (
                    select(Student)
                    .outerjoin(
                        StudentWorkState,
                        (StudentWorkState.tenant_id == Student.tenant_id) & (StudentWorkState.student_id == Student.id),
                    )
                    .where(Student.tenant_id == tenant_id, StudentWorkState.id.is_(None))
                    .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc(), Student.id.asc())
                    .limit(limit)
                )
                if cursor:
                    try:
                        cursor_id = UUID(cursor)
                    except ValueError:
                        cursor_id = None
                    if cursor_id is not None:
                        stmt = (
                            select(Student)
                            .outerjoin(
                                StudentWorkState,
                                (StudentWorkState.tenant_id == Student.tenant_id) & (StudentWorkState.student_id == Student.id),
                            )
                            .where(
                                Student.tenant_id == tenant_id,
                                StudentWorkState.id.is_(None),
                                Student.id >= cursor_id,
                            )
                            .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc(), Student.id.asc())
                            .limit(limit)
                        )
                students = session.execute(stmt).scalars().all()
                for student in students:
                    self.refresh_student_projection(session, tenant_id=tenant_id, student_id=student.id)
                next_student = session.execute(
                    select(Student.id)
                    .outerjoin(
                        StudentWorkState,
                        (StudentWorkState.tenant_id == Student.tenant_id) & (StudentWorkState.student_id == Student.id),
                    )
                    .where(Student.tenant_id == tenant_id, StudentWorkState.id.is_(None))
                    .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc(), Student.id.asc())
                    .limit(1)
                ).scalar_one_or_none()
                remaining_students = session.execute(
                    select(func.count())
                    .select_from(Student)
                    .outerjoin(
                        StudentWorkState,
                        (StudentWorkState.tenant_id == Student.tenant_id) & (StudentWorkState.student_id == Student.id),
                    )
                    .where(Student.tenant_id == tenant_id, StudentWorkState.id.is_(None))
                ).scalar_one()
                return {
                    "processedStudents": len(students),
                    "nextCursor": (str(next_student) if next_student is not None else None),
                    "remainingStudents": int(remaining_students or 0),
                }

    def refresh_student_projection(self, session: Session, *, tenant_id: UUID, student_id: UUID) -> None:
        from app.services.admissions_ops_service import AdmissionsOpsService

        admissions_ops = AdmissionsOpsService(session_factory=self.session_factory)
        student = session.execute(
            select(Student)
            .where(Student.tenant_id == tenant_id, Student.id == student_id)
            .limit(1)
        ).scalar_one_or_none()
        if student is None:
            session.execute(
                delete(StudentWorkState).where(
                    StudentWorkState.tenant_id == tenant_id,
                    StudentWorkState.student_id == student_id,
                )
            )
            return
        context = admissions_ops._ensure_student_state_for_student(session, tenant_id, student)
        item = admissions_ops._build_work_item(session, tenant_id, context)
        state = session.execute(
            select(StudentWorkState).where(
                StudentWorkState.tenant_id == tenant_id,
                StudentWorkState.student_id == student_id,
            ).limit(1)
        ).scalar_one_or_none()
        if state is None:
            state = StudentWorkState(tenant_id=tenant_id, student_id=student_id)
            session.add(state)
            session.flush()
        state.student_identifier = item.studentId
        state.student_name = item.studentName
        state.population = item.population
        state.stage = item.stage
        state.completion_percent = item.completionPercent
        state.priority = item.priority
        state.priority_score = item.priorityScore
        state.section = item.section
        state.owner_user_id = UUID(item.owner.id) if item.owner.id else None
        state.owner_name = item.owner.name
        state.reason_code = item.reasonToAct.code
        state.reason_label = item.reasonToAct.label
        state.suggested_action_code = item.suggestedAction.code
        state.suggested_action_label = item.suggestedAction.label
        state.readiness_json = item.readiness or {}
        state.blocking_items_json = [entry.model_dump(mode="json") for entry in item.blockingItems]
        state.checklist_summary_json = item.checklistSummary.model_dump(mode="json")
        state.fit_score = item.fitScore
        state.deposit_likelihood = item.depositLikelihood
        state.program = item.program
        state.institution_goal = item.institutionGoal
        state.risk = item.risk
        state.last_activity_at = self._parse_iso_datetime(item.updatedAt)
        state.projected_at = datetime.now(timezone.utc)
        state.updated_at = datetime.now(timezone.utc)

    def refresh_transcript_projection(self, session: Session, *, tenant_id: UUID, student_id: UUID | None) -> None:
        if student_id is None:
            return
        self.refresh_student_projection(session, tenant_id=tenant_id, student_id=student_id)

    def _parse_iso_datetime(self, value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
