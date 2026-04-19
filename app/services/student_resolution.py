from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Student, Transcript, TranscriptDemographics


class StudentResolutionService:
    def ensure_student_for_transcript(
        self,
        session: Session,
        tenant_id: UUID,
        transcript: Transcript,
        demographics: TranscriptDemographics | None,
    ) -> Student | None:
        if transcript.student_id:
            student = session.get(Student, transcript.student_id)
            if student is not None:
                self._refresh_student_rollup(student, demographics, transcript)
                return student

        if demographics is None:
            return None

        student = self._find_existing_student(session, tenant_id, demographics)
        if student is None:
            if not self._has_resolvable_identity(demographics):
                return None
            student = Student(
                tenant_id=tenant_id,
                external_student_id=demographics.student_external_id,
                first_name=demographics.student_first_name,
                middle_name=demographics.student_middle_name,
                last_name=demographics.student_last_name,
                preferred_name=demographics.student_first_name,
                date_of_birth=demographics.date_of_birth,
                email=None,
                phone=None,
                city=None,
                state=None,
                country=None,
                target_program_id=None,
                target_institution_id=None,
                advisor_user_id=None,
                current_stage="transcript intake",
                risk_level="low",
                summary="Student record created from transcript intake.",
                latest_cumulative_gpa=demographics.cumulative_gpa,
                accepted_credits=demographics.total_credits_earned,
                latest_activity_at=transcript.updated_at or transcript.created_at or datetime.now(timezone.utc),
            )
            session.add(student)
            session.flush()
        else:
            self._refresh_student_identity(student, demographics)
            self._refresh_student_rollup(student, demographics, transcript)

        transcript.student_id = student.id
        transcript.matched_at = transcript.matched_at or datetime.now(timezone.utc)
        transcript.matched_by = transcript.matched_by or "auto_student_resolution"
        return student

    def _find_existing_student(
        self,
        session: Session,
        tenant_id: UUID,
        demographics: TranscriptDemographics,
    ) -> Student | None:
        if demographics.student_external_id:
            student = session.execute(
                select(Student)
                .where(
                    Student.tenant_id == tenant_id,
                    Student.external_student_id == demographics.student_external_id,
                )
                .limit(1)
            ).scalar_one_or_none()
            if student is not None:
                return student

        if demographics.student_first_name and demographics.student_last_name and demographics.date_of_birth:
            student = session.execute(
                select(Student)
                .where(
                    Student.tenant_id == tenant_id,
                    Student.first_name == demographics.student_first_name,
                    Student.last_name == demographics.student_last_name,
                    Student.date_of_birth == demographics.date_of_birth,
                )
                .limit(1)
            ).scalar_one_or_none()
            if student is not None:
                return student

        if demographics.student_first_name and demographics.student_last_name:
            return session.execute(
                select(Student)
                .where(
                    Student.tenant_id == tenant_id,
                    Student.first_name == demographics.student_first_name,
                    Student.last_name == demographics.student_last_name,
                )
                .order_by(Student.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()

        return None

    def _has_resolvable_identity(self, demographics: TranscriptDemographics) -> bool:
        return bool(
            demographics.student_external_id
            or (demographics.student_first_name and demographics.student_last_name)
        )

    def _refresh_student_identity(self, student: Student, demographics: TranscriptDemographics) -> None:
        if demographics.student_external_id and not student.external_student_id:
            student.external_student_id = demographics.student_external_id
        if demographics.student_first_name and not student.first_name:
            student.first_name = demographics.student_first_name
        if demographics.student_middle_name and not student.middle_name:
            student.middle_name = demographics.student_middle_name
        if demographics.student_last_name and not student.last_name:
            student.last_name = demographics.student_last_name
        if demographics.student_first_name and not student.preferred_name:
            student.preferred_name = demographics.student_first_name
        if demographics.date_of_birth and not student.date_of_birth:
            student.date_of_birth = demographics.date_of_birth

    def _refresh_student_rollup(
        self,
        student: Student,
        demographics: TranscriptDemographics | None,
        transcript: Transcript,
    ) -> None:
        if demographics is not None:
            if demographics.cumulative_gpa is not None:
                student.latest_cumulative_gpa = demographics.cumulative_gpa
            if demographics.total_credits_earned is not None:
                student.accepted_credits = demographics.total_credits_earned
        student.latest_activity_at = transcript.updated_at or transcript.created_at or datetime.now(timezone.utc)
