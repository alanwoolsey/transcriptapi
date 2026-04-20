from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Student, Transcript, TranscriptDemographics, TrustFlag
from app.db.session import get_session_factory
from app.models.trust_models import TrustCaseItem


class TrustService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def list_cases(self, tenant_id: UUID) -> list[TrustCaseItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            trust_cases = self._list_trust_flags(session, tenant_id)
            if trust_cases:
                return trust_cases
            return self._list_fraudulent_transcripts(session, tenant_id)

    def _list_trust_flags(self, session: Session, tenant_id: UUID) -> list[TrustCaseItem]:
        stmt = (
            select(TrustFlag, Student, TranscriptDemographics)
            .outerjoin(Student, Student.id == TrustFlag.student_id)
            .outerjoin(Transcript, Transcript.id == TrustFlag.transcript_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .where(TrustFlag.tenant_id == tenant_id)
            .order_by(TrustFlag.detected_at.desc())
        )
        items: list[TrustCaseItem] = []
        for trust_flag, student, demographics in session.execute(stmt).all():
            items.append(
                TrustCaseItem(
                    id=str(trust_flag.id),
                    studentId=(str(student.id) if student else None),
                    student=self._student_name(student, demographics),
                    documentId=str(trust_flag.transcript_id),
                    document="Official transcript",
                    severity=self._title_case(trust_flag.severity),
                    signal=self._title_case(trust_flag.flag_type),
                    evidence=trust_flag.reason,
                    status=self._title_case(trust_flag.status),
                    owner=None,
                    openedAt=self._format_time(trust_flag.detected_at),
                )
            )
        return items

    def _list_fraudulent_transcripts(self, session: Session, tenant_id: UUID) -> list[TrustCaseItem]:
        stmt = (
            select(Transcript, Student, TranscriptDemographics)
            .outerjoin(Student, Student.id == Transcript.student_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id, Transcript.is_fraudulent.is_(True))
            .order_by(Transcript.created_at.desc())
        )
        items: list[TrustCaseItem] = []
        for transcript, student, demographics in session.execute(stmt).all():
            items.append(
                TrustCaseItem(
                    id=f"TRUST-{str(transcript.id)[:8]}",
                    studentId=(str(student.id) if student else None),
                    student=self._student_name(student, demographics),
                    documentId=str(transcript.id),
                    document="Official transcript",
                    severity="High",
                    signal="Fraudulent transcript",
                    evidence=transcript.notes or "Transcript was flagged as fraudulent and requires manual review.",
                    status=self._title_case(transcript.status) or "Quarantined",
                    owner=None,
                    openedAt=self._format_time(transcript.created_at),
                )
            )
        return items

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

    def _title_case(self, value: str | None) -> str:
        if not value:
            return ""
        return value.replace("_", " ").replace("-", " ").title()

    def _format_time(self, value) -> str | None:
        if value is None:
            return None
        return value.isoformat().replace("+00:00", "Z")
