from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    DecisionPacket,
    DecisionPacketEvent,
    DecisionPacketNote,
    DocumentUpload,
    Student,
    TenantUserMembership,
    Transcript,
    TranscriptDemographics,
    TranscriptParseRun,
    TranscriptStudentMatch,
    TrustFlag,
)
from app.db.session import get_session_factory
from app.models.decision_models import (
    CreateDecisionRequest,
    DecisionAssignRequest,
    DecisionAssignResponse,
    DecisionAssignedUser,
    DecisionDetailResponse,
    DecisionEvidence,
    DecisionNoteCreateRequest,
    DecisionNoteItem,
    DecisionProgramSummary,
    DecisionRecommendation,
    DecisionStatusUpdateRequest,
    DecisionStatusUpdateResponse,
    DecisionStudentSummary,
    DecisionTimelineEvent,
    DecisionTrustSignal,
    DecisionTrustSummary,
    DecisionWorkbenchItem,
)
from app.services.student_resolution import StudentResolutionService


VALID_DECISION_STATUSES = {
    "Draft",
    "Ready for review",
    "Needs evidence",
    "Approved",
    "Released",
}
DEFAULT_QUEUE_NAME = "Admissions Review"


class DecisionNotFoundError(Exception):
    pass


class DecisionValidationError(Exception):
    pass


@dataclass
class _DecisionBundle:
    transcript: Transcript
    demographics: TranscriptDemographics | None
    parse_run: TranscriptParseRun | None
    upload: DocumentUpload | None
    match: TranscriptStudentMatch | None
    student: Student | None


class DecisionService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory
        self.student_resolution = StudentResolutionService()

    def list_decisions(self, tenant_id: UUID) -> list[DecisionWorkbenchItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            packets = session.execute(
                select(DecisionPacket)
                .where(DecisionPacket.tenant_id == tenant_id)
                .order_by(DecisionPacket.created_at.desc())
            ).scalars().all()
            packet_backed_transcript_ids = {
                packet.transcript_id
                for packet in packets
                if packet.transcript_id is not None
            }

            items: list[DecisionWorkbenchItem] = [self._packet_to_item(packet) for packet in packets]
            bundles = self._load_list_bundles(session, tenant_id)
            grouped: dict[str, list[_DecisionBundle]] = defaultdict(list)
            for bundle in bundles:
                if bundle.transcript.id in packet_backed_transcript_ids:
                    continue
                grouped[self._decision_key(bundle)].append(bundle)

            for _, records in grouped.items():
                latest = records[0]
                items.append(self._bundle_to_item(latest))
            return items

    def create_decision(
        self,
        db: Session,
        tenant_id: UUID,
        user_id: UUID,
        payload: CreateDecisionRequest,
    ) -> DecisionWorkbenchItem:
        packet = DecisionPacket(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            queue_name=DEFAULT_QUEUE_NAME,
            status="Draft",
            student_name=payload.student,
            program_name=payload.program,
            fit_score=payload.fit,
            credit_estimate=payload.creditEstimate,
            readiness=payload.readiness,
            reason=payload.reason,
        )
        db.add(packet)
        db.flush()
        self._add_event(
            db,
            tenant_id=tenant_id,
            decision_packet_id=packet.id,
            actor_user_id=user_id,
            event_type="packet_created",
            label="Decision packet created",
            detail=f"Packet opened for {payload.student}.",
        )
        db.commit()
        db.refresh(packet)
        return self._packet_to_item(packet)

    def get_decision_detail(self, tenant_id: UUID, decision_id: UUID) -> DecisionDetailResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            packet = self._get_packet(session, tenant_id, decision_id)
            if packet is not None:
                return self._build_detail_from_packet(session, packet)

            bundle = self._load_bundle_by_transcript_id(session, tenant_id, decision_id)
            if bundle is None:
                raise DecisionNotFoundError("Decision packet not found.")
            return self._build_detail_from_bundle(session, bundle)

    def update_status(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        decision_id: UUID,
        payload: DecisionStatusUpdateRequest,
    ) -> DecisionStatusUpdateResponse:
        if payload.status not in VALID_DECISION_STATUSES:
            raise DecisionValidationError("Invalid decision status.")

        packet = self._get_or_create_packet(db, tenant_id, actor_user_id, decision_id)
        previous_status = packet.status
        packet.status = payload.status
        packet.readiness = payload.status
        self._add_event(
            db,
            tenant_id=tenant_id,
            decision_packet_id=packet.id,
            actor_user_id=actor_user_id,
            event_type="status_changed",
            label=f"Moved to {payload.status}",
            detail=f"Status changed from {previous_status} to {payload.status}.",
        )
        db.commit()
        db.refresh(packet)
        return DecisionStatusUpdateResponse(
            id=str(packet.id),
            status=packet.status,
            updatedAt=self._isoformat(packet.updated_at),
        )

    def assign_decision(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        decision_id: UUID,
        payload: DecisionAssignRequest,
    ) -> DecisionAssignResponse:
        packet = self._get_or_create_packet(db, tenant_id, actor_user_id, decision_id)
        assignee_id = self._parse_uuid(payload.assignee_user_id, "assignee_user_id must be a valid UUID.")
        assignee = self._load_tenant_user(db, tenant_id, assignee_id)
        if assignee is None:
            raise DecisionValidationError("Assignee is not authorized for this tenant.")

        packet.assigned_to_user_id = assignee.id
        if payload.queue:
            packet.queue_name = payload.queue

        detail = f"Assigned to {assignee.display_name}."
        if packet.queue_name:
            detail = f"{detail} Queue: {packet.queue_name}."
        self._add_event(
            db,
            tenant_id=tenant_id,
            decision_packet_id=packet.id,
            actor_user_id=actor_user_id,
            event_type="assigned",
            label=f"Assigned to {assignee.display_name}",
            detail=detail,
        )
        db.commit()
        db.refresh(packet)
        return DecisionAssignResponse(
            id=str(packet.id),
            assignedTo=DecisionAssignedUser(id=str(assignee.id), name=assignee.display_name),
            updatedAt=self._isoformat(packet.updated_at),
        )

    def add_note(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user: AppUser,
        decision_id: UUID,
        payload: DecisionNoteCreateRequest,
    ) -> DecisionNoteItem:
        body = payload.body.strip()
        if not body:
            raise DecisionValidationError("Note body is required.")

        packet = self._get_or_create_packet(db, tenant_id, actor_user.id, decision_id)
        note = DecisionPacketNote(
            tenant_id=tenant_id,
            decision_packet_id=packet.id,
            author_user_id=actor_user.id,
            body=body,
        )
        db.add(note)
        db.flush()
        self._add_event(
            db,
            tenant_id=tenant_id,
            decision_packet_id=packet.id,
            actor_user_id=actor_user.id,
            event_type="note_added",
            label="Internal note added",
            detail=body,
        )
        db.commit()
        db.refresh(note)
        return DecisionNoteItem(
            id=str(note.id),
            body=note.body,
            authorName=actor_user.display_name,
            createdAt=self._isoformat(note.created_at),
        )

    def get_timeline(self, tenant_id: UUID, decision_id: UUID) -> list[DecisionTimelineEvent]:
        session_factory = self.session_factory()
        with session_factory() as session:
            packet = self._get_packet(session, tenant_id, decision_id)
            if packet is None:
                bundle = self._load_bundle_by_transcript_id(session, tenant_id, decision_id)
                if bundle is None:
                    raise DecisionNotFoundError("Decision packet not found.")
                return []
            return self._load_timeline(session, tenant_id, packet.id)

    def _load_list_bundles(self, session: Session, tenant_id: UUID) -> list[_DecisionBundle]:
        transcript_stmt = (
            select(Transcript, TranscriptDemographics, Student)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(Student, Student.id == Transcript.student_id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        transcript_rows = session.execute(transcript_stmt).all()
        transcript_ids = [transcript.id for transcript, _, _ in transcript_rows]
        if not transcript_ids:
            return []

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
                parse_run=None,
                upload=None,
                match=latest_match_by_transcript.get(transcript.id),
                student=student,
            )
            for transcript, demographics, student in transcript_rows
        ]

    def _heal_transcript_data(self, session: Session, tenant_id: UUID) -> None:
        stmt = (
            select(Transcript, TranscriptDemographics, TranscriptParseRun)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(TranscriptParseRun, TranscriptParseRun.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        changed = False
        for transcript, demographics, parse_run in session.execute(stmt).all():
            previous_student_id = transcript.student_id
            student = self.student_resolution.ensure_student_for_transcript(
                session=session,
                tenant_id=tenant_id,
                transcript=transcript,
                demographics=demographics,
            )
            if student is not None and transcript.student_id != previous_student_id:
                changed = True

            payload = parse_run.response_json if parse_run and parse_run.response_json else {}
            raw_courses = payload.get("courses") or []
            if transcript.status == "completed" and not raw_courses:
                transcript.status = "failed"
                transcript.notes = "No courses were extracted from transcript. Reprocess required."
                if parse_run is not None:
                    parse_run.status = "failed"
                    parse_run.error_message = transcript.notes
                changed = True

        if changed:
            session.commit()

    def _load_bundle_by_transcript_id(self, session: Session, tenant_id: UUID, transcript_id: UUID) -> _DecisionBundle | None:
        row = session.execute(
            select(Transcript, TranscriptDemographics, Student)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(Student, Student.id == Transcript.student_id)
            .where(Transcript.tenant_id == tenant_id, Transcript.id == transcript_id)
            .limit(1)
        ).one_or_none()
        if row is None:
            return None

        transcript, demographics, student = row
        parse_run = session.execute(
            select(TranscriptParseRun)
            .where(TranscriptParseRun.tenant_id == tenant_id, TranscriptParseRun.transcript_id == transcript_id)
            .order_by(TranscriptParseRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        match = session.execute(
            select(TranscriptStudentMatch)
            .where(
                TranscriptStudentMatch.tenant_id == tenant_id,
                TranscriptStudentMatch.transcript_id == transcript_id,
            )
            .order_by(TranscriptStudentMatch.decided_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return _DecisionBundle(
            transcript=transcript,
            demographics=demographics,
            parse_run=parse_run,
            upload=None,
            match=match,
            student=student,
        )

    def _get_packet(self, session: Session, tenant_id: UUID, decision_id: UUID) -> DecisionPacket | None:
        return session.execute(
            select(DecisionPacket)
            .where(DecisionPacket.tenant_id == tenant_id, DecisionPacket.id == decision_id)
            .limit(1)
        ).scalar_one_or_none()

    def _get_or_create_packet(self, db: Session, tenant_id: UUID, actor_user_id: UUID, decision_id: UUID) -> DecisionPacket:
        packet = self._get_packet(db, tenant_id, decision_id)
        if packet is not None:
            return packet

        bundle = self._load_bundle_by_transcript_id(db, tenant_id, decision_id)
        if bundle is None:
            raise DecisionNotFoundError("Decision packet not found.")

        packet = DecisionPacket(
            id=bundle.transcript.id,
            tenant_id=tenant_id,
            student_id=bundle.transcript.student_id,
            transcript_id=bundle.transcript.id,
            created_by_user_id=actor_user_id,
            queue_name=DEFAULT_QUEUE_NAME,
            status="Draft",
            student_name=self._student_name(bundle),
            program_name=self._program_name(bundle),
            fit_score=self._fit_score(bundle),
            credit_estimate=self._credit_estimate(bundle),
            readiness=self._readiness(bundle),
            reason=self._reason(bundle),
            created_at=bundle.transcript.created_at,
            updated_at=bundle.transcript.created_at,
        )
        db.add(packet)
        db.flush()
        self._add_event(
            db,
            tenant_id=tenant_id,
            decision_packet_id=packet.id,
            actor_user_id=actor_user_id,
            event_type="packet_created",
            label="Decision packet created",
            detail=f"Packet opened for {packet.student_name}.",
            event_at=bundle.transcript.created_at,
        )
        return packet

    def _load_tenant_user(self, session: Session, tenant_id: UUID, user_id: UUID) -> AppUser | None:
        return session.execute(
            select(AppUser)
            .join(TenantUserMembership, TenantUserMembership.user_id == AppUser.id)
            .where(
                AppUser.id == user_id,
                AppUser.tenant_id == tenant_id,
                AppUser.is_active.is_(True),
                TenantUserMembership.tenant_id == tenant_id,
                TenantUserMembership.status == "active",
            )
            .limit(1)
        ).scalar_one_or_none()

    def _build_detail_from_packet(self, session: Session, packet: DecisionPacket) -> DecisionDetailResponse:
        bundle = self._load_bundle_by_transcript_id(session, packet.tenant_id, packet.transcript_id) if packet.transcript_id else None
        student = bundle.student if bundle else (session.get(Student, packet.student_id) if packet.student_id else None)
        assigned_to = session.get(AppUser, packet.assigned_to_user_id) if packet.assigned_to_user_id else None
        notes = self._load_notes(session, packet.tenant_id, packet.id)
        timeline = self._load_timeline(session, packet.tenant_id, packet.id)
        trust = self._build_trust_summary(session, packet.tenant_id, packet.transcript_id, packet.student_id)
        evidence = self._build_evidence(bundle)
        return DecisionDetailResponse(
            id=str(packet.id),
            status=packet.status,
            readiness=packet.readiness,
            assignedTo=DecisionAssignedUser(id=str(assigned_to.id), name=assigned_to.display_name) if assigned_to else None,
            queue=packet.queue_name,
            createdAt=self._isoformat(packet.created_at),
            updatedAt=self._isoformat(packet.updated_at),
            student=self._build_student_summary(student, packet.student_name),
            program=DecisionProgramSummary(name=packet.program_name),
            recommendation=DecisionRecommendation(
                fit=packet.fit_score,
                creditEstimate=packet.credit_estimate,
                reason=packet.reason,
            ),
            evidence=evidence,
            trust=trust,
            notes=notes,
            timelinePreview=timeline[:5],
        )

    def _build_detail_from_bundle(self, session: Session, bundle: _DecisionBundle) -> DecisionDetailResponse:
        trust = self._build_trust_summary(session, bundle.transcript.tenant_id, bundle.transcript.id, bundle.transcript.student_id)
        return DecisionDetailResponse(
            id=str(bundle.transcript.id),
            status="Draft",
            readiness=self._readiness(bundle),
            assignedTo=None,
            queue=DEFAULT_QUEUE_NAME,
            createdAt=self._isoformat(bundle.transcript.created_at),
            updatedAt=self._isoformat(bundle.transcript.updated_at or bundle.transcript.created_at),
            student=self._build_student_summary(bundle.student, self._student_name(bundle)),
            program=DecisionProgramSummary(name=self._program_name(bundle)),
            recommendation=DecisionRecommendation(
                fit=self._fit_score(bundle),
                creditEstimate=self._credit_estimate(bundle),
                reason=self._reason(bundle),
            ),
            evidence=self._build_evidence(bundle),
            trust=trust,
            notes=[],
            timelinePreview=[],
        )

    def _build_student_summary(self, student: Student | None, fallback_name: str) -> DecisionStudentSummary:
        if student is None:
            return DecisionStudentSummary(name=fallback_name)
        name_parts = [part for part in [student.preferred_name or student.first_name, student.last_name] if part and part.strip()]
        student_name = " ".join(name_parts) if name_parts else fallback_name
        return DecisionStudentSummary(
            id=str(student.id),
            name=student_name,
            email=student.email,
            externalId=student.external_student_id,
        )

    def _build_evidence(self, bundle: _DecisionBundle | None) -> DecisionEvidence:
        if bundle is None:
            return DecisionEvidence(documentCount=0)
        return DecisionEvidence(
            institution=bundle.demographics.institution_name if bundle.demographics else None,
            gpa=self._to_float(bundle.demographics.cumulative_gpa if bundle.demographics else None, None),
            creditsEarned=self._to_float(bundle.demographics.total_credits_earned if bundle.demographics else None, None),
            parserConfidence=self._to_float(bundle.parse_run.confidence_score if bundle.parse_run else bundle.transcript.parser_confidence, None),
            documentCount=1,
        )

    def _build_trust_summary(
        self,
        session: Session,
        tenant_id: UUID,
        transcript_id: UUID | None,
        student_id: UUID | None,
    ) -> DecisionTrustSummary:
        stmt = select(TrustFlag).where(TrustFlag.tenant_id == tenant_id)
        if transcript_id is not None:
            stmt = stmt.where(TrustFlag.transcript_id == transcript_id)
        elif student_id is not None:
            stmt = stmt.where(TrustFlag.student_id == student_id)
        else:
            return DecisionTrustSummary(status="Clear", signals=[])

        flags = session.execute(stmt.order_by(TrustFlag.detected_at.desc())).scalars().all()
        if not flags:
            return DecisionTrustSummary(status="Clear", signals=[])

        signals = [
            DecisionTrustSignal(
                id=str(flag.id),
                severity=flag.severity.title(),
                signal=flag.flag_type.replace("_", " ").title(),
                evidence=flag.reason,
                status=flag.status.replace("_", " ").title(),
            )
            for flag in flags
        ]
        active_flags = [flag for flag in flags if flag.status.lower() not in {"resolved", "closed"}]
        overall_status = "Review" if active_flags else "Clear"
        return DecisionTrustSummary(status=overall_status, signals=signals)

    def _load_notes(self, session: Session, tenant_id: UUID, packet_id: UUID) -> list[DecisionNoteItem]:
        rows = session.execute(
            select(DecisionPacketNote, AppUser)
            .join(AppUser, AppUser.id == DecisionPacketNote.author_user_id)
            .where(
                DecisionPacketNote.tenant_id == tenant_id,
                DecisionPacketNote.decision_packet_id == packet_id,
            )
            .order_by(DecisionPacketNote.created_at.desc())
        ).all()
        return [
            DecisionNoteItem(
                id=str(note.id),
                body=note.body,
                authorName=user.display_name,
                createdAt=self._isoformat(note.created_at),
            )
            for note, user in rows
        ]

    def _load_timeline(self, session: Session, tenant_id: UUID, packet_id: UUID) -> list[DecisionTimelineEvent]:
        rows = session.execute(
            select(DecisionPacketEvent, AppUser)
            .outerjoin(AppUser, AppUser.id == DecisionPacketEvent.actor_user_id)
            .where(
                DecisionPacketEvent.tenant_id == tenant_id,
                DecisionPacketEvent.decision_packet_id == packet_id,
            )
            .order_by(DecisionPacketEvent.event_at.desc())
        ).all()
        return [
            DecisionTimelineEvent(
                id=str(event.id),
                type=event.event_type,
                label=event.label,
                detail=event.detail,
                actorName=user.display_name if user else None,
                at=self._isoformat(event.event_at),
            )
            for event, user in rows
        ]

    def _add_event(
        self,
        session: Session,
        tenant_id: UUID,
        decision_packet_id: UUID,
        actor_user_id: UUID | None,
        event_type: str,
        label: str,
        detail: str | None,
        event_at: datetime | None = None,
    ) -> None:
        session.add(
            DecisionPacketEvent(
                tenant_id=tenant_id,
                decision_packet_id=decision_packet_id,
                actor_user_id=actor_user_id,
                event_type=event_type,
                label=label,
                detail=detail,
                event_at=event_at or datetime.now(timezone.utc),
            )
        )

    def _packet_to_item(self, packet: DecisionPacket) -> DecisionWorkbenchItem:
        return DecisionWorkbenchItem(
            id=str(packet.id),
            student=packet.student_name,
            program=packet.program_name,
            fit=packet.fit_score,
            creditEstimate=packet.credit_estimate,
            readiness=packet.readiness,
            reason=packet.reason,
            status=packet.status,
            queue=packet.queue_name,
            updatedAt=self._isoformat(packet.updated_at),
        )

    def _bundle_to_item(self, bundle: _DecisionBundle) -> DecisionWorkbenchItem:
        return DecisionWorkbenchItem(
            id=str(bundle.transcript.id),
            student=self._student_name(bundle),
            program=self._program_name(bundle),
            fit=self._fit_score(bundle),
            creditEstimate=self._credit_estimate(bundle),
            readiness=self._readiness(bundle),
            reason=self._reason(bundle),
            status="Draft",
            queue=DEFAULT_QUEUE_NAME,
            updatedAt=self._isoformat(bundle.transcript.updated_at or bundle.transcript.created_at),
        )

    def _decision_key(self, bundle: _DecisionBundle) -> str:
        if bundle.transcript.student_id:
            return str(bundle.transcript.student_id)
        if bundle.demographics and bundle.demographics.student_external_id:
            return bundle.demographics.student_external_id
        if bundle.demographics:
            parts = [
                bundle.demographics.student_first_name or "",
                bundle.demographics.student_last_name or "",
                bundle.demographics.institution_name or "",
            ]
            key = "-".join(part.strip().lower().replace(" ", "-") for part in parts if part and part.strip())
            if key:
                return key
        return str(bundle.transcript.id)

    def _student_name(self, bundle: _DecisionBundle) -> str:
        if bundle.student is not None:
            name_parts = [part for part in [bundle.student.preferred_name or bundle.student.first_name, bundle.student.last_name] if part and part.strip()]
            if name_parts:
                return " ".join(name_parts)
        first = bundle.demographics.student_first_name if bundle.demographics else None
        last = bundle.demographics.student_last_name if bundle.demographics else None
        parts = [part for part in [first, last] if part and part.strip()]
        if parts:
            return " ".join(parts)
        if bundle.demographics and bundle.demographics.student_external_id:
            return bundle.demographics.student_external_id
        return str(bundle.transcript.id)

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

    def _isoformat(self, value: datetime | None) -> str:
        if value is None:
            return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _to_float(self, value: Decimal | float | int | None, fallback: float | None = 0.0) -> float | None:
        if value is None:
            return fallback
        try:
            return float(value)
        except Exception:
            return fallback

    def _parse_uuid(self, value: str, message: str) -> UUID:
        try:
            return UUID(value)
        except ValueError as exc:
            raise DecisionValidationError(message) from exc
