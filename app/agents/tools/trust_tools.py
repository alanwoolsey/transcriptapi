from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db.models import DocumentUpload, Student, Transcript, TranscriptDemographics, TrustFlag
from app.db.session import get_session_factory


class TrustContextTool:
    identity_tool_name = "lookup_identity_match"
    trust_flags_tool_name = "list_trust_flags"
    document_history_tool_name = "list_document_history"

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def lookup_identity_match(self, *, tenant_id: str, transcript_id: str) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        transcript_uuid = UUID(transcript_id)
        session_factory = self.session_factory()
        with session_factory() as session:
            row = session.execute(
                select(Transcript, Student, TranscriptDemographics)
                .outerjoin(Student, Student.id == Transcript.student_id)
                .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
                .where(Transcript.tenant_id == tenant_uuid, Transcript.id == transcript_uuid)
                .limit(1)
            ).one_or_none()
            if row is None:
                return {"status": "not_found", "transcriptId": transcript_id}
            transcript, student, demographics = row
            return {
                "status": "matched" if student is not None else "unmatched",
                "transcriptId": str(transcript.id),
                "documentId": str(transcript.document_upload_id),
                "studentId": str(student.id) if student is not None else None,
                "studentExternalId": student.external_student_id if student is not None else None,
                "studentName": self._student_name(student, demographics),
                "transcriptStudentName": self._demographic_name(demographics),
                "transcriptStudentExternalId": demographics.student_external_id if demographics is not None else None,
                "matchedAt": self._iso(transcript.matched_at),
                "matchedBy": transcript.matched_by,
            }

    def list_trust_flags(self, *, tenant_id: str, transcript_id: str) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        transcript_uuid = UUID(transcript_id)
        session_factory = self.session_factory()
        with session_factory() as session:
            flags = session.execute(
                select(TrustFlag)
                .where(TrustFlag.tenant_id == tenant_uuid, TrustFlag.transcript_id == transcript_uuid)
                .order_by(TrustFlag.detected_at.desc(), TrustFlag.created_at.desc())
            ).scalars().all()
            return {
                "transcriptId": transcript_id,
                "flagCount": len(flags),
                "activeFlagCount": sum(1 for flag in flags if (flag.status or "").lower() not in {"resolved", "closed"}),
                "flags": [
                    {
                        "id": str(flag.id),
                        "flagType": flag.flag_type,
                        "severity": flag.severity,
                        "status": flag.status,
                        "reason": flag.reason,
                        "detectedBy": flag.detected_by,
                        "detectedAt": self._iso(flag.detected_at),
                        "resolvedAt": self._iso(flag.resolved_at),
                    }
                    for flag in flags
                ],
            }

    def list_document_history(self, *, tenant_id: str, student_id: str | None = None, transcript_id: str | None = None) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        student_uuid = UUID(student_id) if student_id else None
        transcript_uuid = UUID(transcript_id) if transcript_id else None
        session_factory = self.session_factory()
        with session_factory() as session:
            if student_uuid is None and transcript_uuid is not None:
                transcript = session.execute(
                    select(Transcript)
                    .where(Transcript.tenant_id == tenant_uuid, Transcript.id == transcript_uuid)
                    .limit(1)
                ).scalar_one_or_none()
                student_uuid = transcript.student_id if transcript is not None else None
            if student_uuid is None:
                return {"studentId": None, "documentCount": 0, "documents": []}
            rows = session.execute(
                select(Transcript, DocumentUpload)
                .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
                .where(Transcript.tenant_id == tenant_uuid, Transcript.student_id == student_uuid)
                .order_by(Transcript.created_at.desc())
            ).all()
            return {
                "studentId": str(student_uuid),
                "documentCount": len(rows),
                "documents": [
                    {
                        "transcriptId": str(transcript.id),
                        "documentId": str(document.id),
                        "filename": document.original_filename,
                        "documentType": transcript.document_type,
                        "transcriptStatus": transcript.status,
                        "documentStatus": document.upload_status,
                        "parserConfidence": self._float(transcript.parser_confidence),
                        "isFraudulent": bool(transcript.is_fraudulent),
                        "createdAt": self._iso(transcript.created_at),
                    }
                    for transcript, document in rows
                ],
            }

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def lookup_identity_match(tenant_id: str, transcript_id: str) -> dict[str, Any]:
            """Load current transcript-to-student identity match context."""
            return self.lookup_identity_match(tenant_id=tenant_id, transcript_id=transcript_id)

        @tool
        def list_trust_flags(tenant_id: str, transcript_id: str) -> dict[str, Any]:
            """List trust flags for a transcript."""
            return self.list_trust_flags(tenant_id=tenant_id, transcript_id=transcript_id)

        @tool
        def list_document_history(tenant_id: str, student_id: str | None = None, transcript_id: str | None = None) -> dict[str, Any]:
            """List prior transcript documents for the matched student."""
            return self.list_document_history(tenant_id=tenant_id, student_id=student_id, transcript_id=transcript_id)

        return [lookup_identity_match, list_trust_flags, list_document_history]

    def _student_name(self, student: Student | None, demographics: TranscriptDemographics | None) -> str | None:
        if student is not None:
            parts = [student.preferred_name or student.first_name, student.last_name]
            name = " ".join(part for part in parts if part)
            if name:
                return name
        return self._demographic_name(demographics)

    def _demographic_name(self, demographics: TranscriptDemographics | None) -> str | None:
        if demographics is None:
            return None
        parts = [demographics.student_first_name, demographics.student_last_name]
        return " ".join(part for part in parts if part) or None

    def _iso(self, value) -> str | None:
        if value is None:
            return None
        return value.isoformat().replace("+00:00", "Z")

    def _float(self, value) -> float | None:
        if value is None:
            return None
        return float(value)


class TrustCaseTool:
    create_tool_name = "create_trust_case"
    escalate_tool_name = "escalate_trust_case"
    resolve_tool_name = "resolve_trust_case"

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def create_trust_case(
        self,
        *,
        tenant_id: str,
        transcript_id: str,
        flag_type: str,
        severity: str = "medium",
        reason: str | None = None,
        detected_by: str = "agent",
    ) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        transcript_uuid = UUID(transcript_id)
        session_factory = self.session_factory()
        with session_factory() as session:
            transcript = self._get_transcript(session, tenant_uuid, transcript_uuid)
            if transcript is None:
                return {"status": "not_found", "code": "trust_case_transcript_not_found", "transcriptId": transcript_id}
            flag = TrustFlag(
                tenant_id=tenant_uuid,
                transcript_id=transcript.id,
                student_id=transcript.student_id,
                flag_type=flag_type,
                severity=severity,
                status="open",
                reason=reason or "Trust case created by agent.",
                detected_by=detected_by,
                detected_at=datetime.now(timezone.utc),
            )
            session.add(flag)
            session.commit()
            return self._case_result(
                status="open",
                code="trust_case_created",
                transcript=transcript,
                flag=flag,
                reason=flag.reason,
            )

    def escalate_trust_case(self, *, tenant_id: str, transcript_id: str, reason: str | None = None) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        transcript_uuid = UUID(transcript_id)
        session_factory = self.session_factory()
        with session_factory() as session:
            transcript = self._get_transcript(session, tenant_uuid, transcript_uuid)
            if transcript is None:
                return {"status": "not_found", "code": "trust_case_transcript_not_found", "transcriptId": transcript_id}
            transcript.is_fraudulent = True
            flags = self._open_flags(session, tenant_uuid, transcript_uuid)
            if flags:
                for flag in flags:
                    flag.status = "escalated"
                    flag.severity = "high"
                    flag.reason = reason or flag.reason or "Escalated by agent."
                flag = flags[0]
            else:
                flag = TrustFlag(
                    tenant_id=tenant_uuid,
                    transcript_id=transcript.id,
                    student_id=transcript.student_id,
                    flag_type="agent_escalation",
                    severity="high",
                    status="escalated",
                    reason=reason or "Escalated by agent.",
                    detected_by="agent",
                    detected_at=datetime.now(timezone.utc),
                )
                session.add(flag)
            session.commit()
            return self._case_result(
                status="escalated",
                code="trust_case_escalated",
                transcript=transcript,
                flag=flag,
                reason=reason or flag.reason,
            )

    def resolve_trust_case(
        self,
        *,
        tenant_id: str,
        transcript_id: str,
        resolved_by_user_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        transcript_uuid = UUID(transcript_id)
        resolver_uuid = UUID(resolved_by_user_id) if resolved_by_user_id else None
        session_factory = self.session_factory()
        with session_factory() as session:
            transcript = self._get_transcript(session, tenant_uuid, transcript_uuid)
            if transcript is None:
                return {"status": "not_found", "code": "trust_case_transcript_not_found", "transcriptId": transcript_id}
            transcript.is_fraudulent = False
            flags = self._open_flags(session, tenant_uuid, transcript_uuid)
            for flag in flags:
                flag.status = "resolved"
                flag.resolved_by_user_id = resolver_uuid
                flag.resolved_at = datetime.now(timezone.utc)
                flag.resolution_notes = note or "Resolved by agent."
            session.commit()
            return {
                "status": "resolved",
                "code": "trust_case_resolved",
                "transcriptId": str(transcript.id),
                "studentId": str(transcript.student_id) if transcript.student_id else None,
                "documentId": str(transcript.document_upload_id),
                "resolvedFlagCount": len(flags),
                "reason": note or "Resolved by agent.",
            }

    def as_strands_tools(self):
        try:
            from strands import tool
        except ImportError as exc:
            raise RuntimeError("Strands Agents is not installed.") from exc

        @tool
        def create_trust_case(
            tenant_id: str,
            transcript_id: str,
            flag_type: str,
            severity: str = "medium",
            reason: str | None = None,
            detected_by: str = "agent",
        ) -> dict[str, Any]:
            """Create an open trust case for a transcript."""
            return self.create_trust_case(
                tenant_id=tenant_id,
                transcript_id=transcript_id,
                flag_type=flag_type,
                severity=severity,
                reason=reason,
                detected_by=detected_by,
            )

        @tool
        def escalate_trust_case(tenant_id: str, transcript_id: str, reason: str | None = None) -> dict[str, Any]:
            """Escalate a trust case and block progression."""
            return self.escalate_trust_case(tenant_id=tenant_id, transcript_id=transcript_id, reason=reason)

        @tool
        def resolve_trust_case(
            tenant_id: str,
            transcript_id: str,
            resolved_by_user_id: str | None = None,
            note: str | None = None,
        ) -> dict[str, Any]:
            """Resolve open trust flags for a transcript."""
            return self.resolve_trust_case(
                tenant_id=tenant_id,
                transcript_id=transcript_id,
                resolved_by_user_id=resolved_by_user_id,
                note=note,
            )

        return [create_trust_case, escalate_trust_case, resolve_trust_case]

    def _get_transcript(self, session, tenant_id: UUID, transcript_id: UUID):
        return session.execute(
            select(Transcript)
            .where(Transcript.tenant_id == tenant_id, Transcript.id == transcript_id)
            .limit(1)
        ).scalar_one_or_none()

    def _open_flags(self, session, tenant_id: UUID, transcript_id: UUID) -> list[TrustFlag]:
        return session.execute(
            select(TrustFlag).where(
                TrustFlag.tenant_id == tenant_id,
                TrustFlag.transcript_id == transcript_id,
                TrustFlag.status.notin_(["resolved", "closed"]),
            )
        ).scalars().all()

    def _case_result(self, *, status: str, code: str, transcript, flag: TrustFlag, reason: str | None) -> dict[str, Any]:
        return {
            "status": status,
            "code": code,
            "trustFlagId": str(flag.id),
            "transcriptId": str(transcript.id),
            "studentId": str(transcript.student_id) if transcript.student_id else None,
            "documentId": str(transcript.document_upload_id),
            "flagType": flag.flag_type,
            "severity": flag.severity,
            "reason": reason,
        }
