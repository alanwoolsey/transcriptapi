from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DocumentUpload, Transcript, TranscriptDemographics, TranscriptParseRun, TranscriptStudentMatch
from app.db.session import get_session_factory
from app.models.decision_models import DecisionWorkbenchItem


@dataclass
class _DecisionBundle:
    transcript: Transcript
    demographics: TranscriptDemographics | None
    parse_run: TranscriptParseRun | None
    upload: DocumentUpload
    match: TranscriptStudentMatch | None


class DecisionService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def list_decisions(self, tenant_id: UUID) -> list[DecisionWorkbenchItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            bundles = self._load_bundles(session, tenant_id)
            grouped: dict[str, list[_DecisionBundle]] = defaultdict(list)
            for bundle in bundles:
                grouped[self._decision_key(bundle)].append(bundle)

            items: list[DecisionWorkbenchItem] = []
            for _, records in grouped.items():
                latest = records[0]
                items.append(
                    DecisionWorkbenchItem(
                        id=str(latest.transcript.id),
                        student=self._student_name(latest),
                        program=self._program_name(latest),
                        fit=self._fit_score(latest),
                        creditEstimate=self._credit_estimate(latest),
                        readiness=self._readiness(latest),
                        reason=self._reason(latest),
                    )
                )
            return items

    def _load_bundles(self, session: Session, tenant_id: UUID) -> list[_DecisionBundle]:
        transcript_stmt = (
            select(Transcript, TranscriptDemographics, DocumentUpload)
            .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        transcript_rows = session.execute(transcript_stmt).all()
        transcript_ids = [transcript.id for transcript, _, _ in transcript_rows]
        if not transcript_ids:
            return []

        parse_runs = session.execute(
            select(TranscriptParseRun)
            .where(TranscriptParseRun.tenant_id == tenant_id, TranscriptParseRun.transcript_id.in_(transcript_ids))
            .order_by(TranscriptParseRun.started_at.desc())
        ).scalars().all()
        latest_parse_run_by_transcript: dict[UUID, TranscriptParseRun] = {}
        for parse_run in parse_runs:
            latest_parse_run_by_transcript.setdefault(parse_run.transcript_id, parse_run)

        matches = session.execute(
            select(TranscriptStudentMatch)
            .where(
                TranscriptStudentMatch.tenant_id == tenant_id,
                TranscriptStudentMatch.transcript_id.in_(transcript_ids),
            )
            .order_by(TranscriptStudentMatch.decided_at.desc())
        ).scalars().all()
        latest_match_by_transcript: dict[UUID, TranscriptStudentMatch] = {}
        for match in matches:
            latest_match_by_transcript.setdefault(match.transcript_id, match)

        return [
            _DecisionBundle(
                transcript=transcript,
                demographics=demographics,
                parse_run=latest_parse_run_by_transcript.get(transcript.id),
                upload=upload,
                match=latest_match_by_transcript.get(transcript.id),
            )
            for transcript, demographics, upload in transcript_rows
        ]

    def _decision_key(self, bundle: _DecisionBundle) -> str:
        if bundle.transcript.student_id:
            return str(bundle.transcript.student_id)
        if bundle.demographics and bundle.demographics.student_external_id:
            return bundle.demographics.student_external_id
        if bundle.demographics:
            parts = [bundle.demographics.student_first_name or "", bundle.demographics.student_last_name or "", bundle.demographics.institution_name or ""]
            key = "-".join(part.strip().lower().replace(" ", "-") for part in parts if part and part.strip())
            if key:
                return key
        return str(bundle.transcript.id)

    def _student_name(self, bundle: _DecisionBundle) -> str:
        first = bundle.demographics.student_first_name if bundle.demographics else None
        last = bundle.demographics.student_last_name if bundle.demographics else None
        parts = [part for part in [first, last] if part and part.strip()]
        return " ".join(parts) if parts else "Unknown Student"

    def _program_name(self, bundle: _DecisionBundle) -> str:
        institution = bundle.demographics.institution_name if bundle.demographics and bundle.demographics.institution_name else None
        if bundle.transcript.document_type:
            return f"{bundle.transcript.document_type.replace('_', ' ').title()} Review"
        return institution or "Transcript Review"

    def _fit_score(self, bundle: _DecisionBundle) -> int:
        if bundle.transcript.is_fraudulent:
            return 25
        if bundle.match and bundle.match.match_score is not None:
            return max(0, min(100, int(float(bundle.match.match_score))))
        gpa = self._to_float(bundle.demographics.cumulative_gpa if bundle.demographics else None)
        confidence = self._to_float(bundle.transcript.parser_confidence)
        if gpa >= 3.5:
            return 94
        if gpa >= 3.0:
            return 84
        if gpa >= 2.5:
            return 74
        if confidence >= 0.9:
            return 82
        if confidence >= 0.75:
            return 68
        return 55

    def _credit_estimate(self, bundle: _DecisionBundle) -> int:
        return int(round(self._to_float(bundle.demographics.total_credits_earned if bundle.demographics else None, 0.0)))

    def _readiness(self, bundle: _DecisionBundle) -> str:
        if bundle.transcript.is_fraudulent:
            return "Trust hold"
        if bundle.transcript.status in {"processing", "failed"}:
            return "Need evidence"
        confidence = self._to_float(bundle.transcript.parser_confidence)
        if confidence >= 0.9:
            return "Auto-certify"
        return "Human review"

    def _reason(self, bundle: _DecisionBundle) -> str:
        if bundle.transcript.is_fraudulent:
            return "Trust or provenance signals require manual review before a decision can be released."
        if bundle.transcript.status == "processing":
            return "Transcript processing is still running."
        if bundle.transcript.status == "failed":
            return bundle.transcript.notes or "Transcript parsing failed and needs follow-up."
        confidence = self._to_float(bundle.transcript.parser_confidence)
        gpa = self._to_float(bundle.demographics.cumulative_gpa if bundle.demographics else None)
        institution = bundle.demographics.institution_name if bundle.demographics and bundle.demographics.institution_name else "the source institution"
        if confidence >= 0.9:
            return f"High-confidence transcript parse from {institution} with no active risk signals."
        if gpa >= 3.0:
            return f"Academic profile from {institution} is promising, but should be reviewed before release."
        return f"Limited confidence or incomplete academic signal from {institution}; review before certification."

    def _to_float(self, value: Decimal | float | int | None, fallback: float = 0.0) -> float:
        if value is None:
            return fallback
        try:
            return float(value)
        except Exception:
            return fallback
