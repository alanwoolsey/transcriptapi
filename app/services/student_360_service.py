from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    AppUser,
    AuditEvent,
    DecisionPacket,
    DecisionPacketEvent,
    DocumentUpload,
    Institution,
    Program,
    Prospect,
    ProspectSourceReference,
    Student,
    StudentChecklistItem as DbStudentChecklistItem,
    StudentDecisionReadiness,
    StudentEnrollmentMilestone,
    StudentNote,
    StudentTask,
    StudentYieldScore,
    Transcript,
    TranscriptDemographics,
    TranscriptParseRun,
    TrustFlag,
)
from app.db.session import get_session_factory
from app.models.student_models import (
    Student360ListRecord,
    Student360ListResponse,
    Student360Record,
    StudentChecklistItem,
    StudentOwnerSummary,
    StudentProgramSummary,
    StudentRecommendation,
    StudentReadinessSummary,
    StudentTermGpa,
    StudentTimelineActor,
    StudentTimelineEntity,
    StudentTimelineEvent,
    StudentTimelineResponse,
    StudentTimelineStep,
    StudentTranscriptCourse,
    StudentTranscriptRecord,
)
from app.services.rbac_service import (
    SENSITIVITY_ACADEMIC_RECORD,
    SENSITIVITY_TRANSCRIPT_IMAGES,
    SENSITIVITY_TRUST_FRAUD_FLAGS,
)
from app.services.student_resolution import StudentResolutionService


@dataclass
class _TranscriptBundle:
    transcript: Transcript
    upload: DocumentUpload
    demographics: TranscriptDemographics | None
    parse_run: TranscriptParseRun | None


class Student360Service:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory
        self.student_resolution = StudentResolutionService()

    def list_students(
        self,
        tenant_id: UUID,
        q: str | None = None,
        *,
        stage: str | None = None,
        population: str | None = None,
        owner: str | None = None,
        source: str | None = None,
        program: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Student360ListResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            canonical_students = self._list_canonical_students(
                session,
                tenant_id,
                q,
                stage=stage,
                population=population,
                owner=owner,
                source=source,
                program=program,
            )
            if canonical_students:
                return Student360ListResponse(students=canonical_students[offset : offset + limit], total=len(canonical_students))
            transcript_students = self._list_transcript_derived_students(
                session,
                tenant_id,
                q,
                stage=stage,
                population=population,
                owner=owner,
                source=source,
                program=program,
            )
            return Student360ListResponse(students=transcript_students[offset : offset + limit], total=len(transcript_students))

    def get_student(self, tenant_id: UUID, student_id: str, authorization: Any | None = None) -> Student360Record | None:
        session_factory = self.session_factory()
        with session_factory() as session:
            canonical_student = self._get_canonical_student(session, tenant_id, student_id)
            if canonical_student is not None:
                return self._apply_sensitivity_redaction(canonical_student, authorization)

            record = self._get_transcript_derived_student(session, tenant_id, student_id)
            return self._apply_sensitivity_redaction(record, authorization) if record else None

    def get_student_timeline(self, tenant_id: UUID, student_id: str, authorization: Any | None = None) -> StudentTimelineResponse | None:
        session_factory = self.session_factory()
        with session_factory() as session:
            student = self._resolve_student_row(session, tenant_id, student_id)
            if student is None:
                derived = self._get_transcript_derived_student(session, tenant_id, student_id)
                if derived is None:
                    return None
                return StudentTimelineResponse(events=self._build_transcript_derived_timeline(session, tenant_id, student_id, authorization))
            events = self._build_canonical_timeline(session, tenant_id, student, authorization)
            return StudentTimelineResponse(events=events)

    def _list_canonical_students(
        self,
        session: Session,
        tenant_id: UUID,
        q: str | None,
        *,
        stage: str | None = None,
        population: str | None = None,
        owner: str | None = None,
        source: str | None = None,
        program: str | None = None,
    ) -> list[Student360ListRecord]:
        transcript_stats = (
            select(
                Transcript.student_id.label("student_id"),
                func.count(Transcript.id).label("transcripts_count"),
                func.max(Transcript.parser_confidence).label("max_parser_confidence"),
            )
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id.is_not(None))
            .group_by(Transcript.student_id)
            .subquery()
        )
        latest_institution_name = (
            select(TranscriptDemographics.institution_name)
            .join(Transcript, Transcript.id == TranscriptDemographics.transcript_id)
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id == Student.id)
            .order_by(Transcript.created_at.desc())
            .limit(1)
            .correlate(Student)
            .scalar_subquery()
        )
        latest_prospect_id = (
            select(Prospect.id)
            .where(Prospect.tenant_id == tenant_id, Prospect.student_id == Student.id)
            .order_by(Prospect.updated_at.desc(), Prospect.created_at.desc())
            .limit(1)
            .correlate(Student)
            .scalar_subquery()
        )
        AdvisorUser = aliased(AppUser)
        ProspectOwnerUser = aliased(AppUser)
        stmt = (
            select(
                Student,
                Program,
                Institution,
                AdvisorUser,
                Prospect,
                ProspectOwnerUser,
                transcript_stats.c.transcripts_count,
                transcript_stats.c.max_parser_confidence,
                latest_institution_name.label("latest_institution_name"),
            )
            .outerjoin(Program, Program.id == Student.target_program_id)
            .outerjoin(Institution, Institution.id == Student.target_institution_id)
            .outerjoin(AdvisorUser, AdvisorUser.id == Student.advisor_user_id)
            .outerjoin(Prospect, Prospect.id == latest_prospect_id)
            .outerjoin(ProspectOwnerUser, ProspectOwnerUser.id == Prospect.owner_user_id)
            .outerjoin(transcript_stats, transcript_stats.c.student_id == Student.id)
            .where(Student.tenant_id == tenant_id)
            .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc())
        )
        stmt = self._apply_student_filters(stmt, stage=stage, population=population, owner=owner, source=source, program=program)
        stmt = self._apply_student_search(stmt, q)
        rows = session.execute(stmt).all()
        if not rows:
            return []

        records: list[Student360ListRecord] = []
        for student, program_row, institution, advisor, prospect, prospect_owner, transcripts_count, max_parser_confidence, latest_institution in rows:
            institution_goal = institution.name if institution else self._safe_str(latest_institution, "Unknown institution")
            transcript_count = int(transcripts_count or 0)
            gpa_value = self._to_float(student.latest_cumulative_gpa)
            fit_score = self._estimate_fit_score_from_summary(gpa_value, transcript_count, max_parser_confidence)
            deposit_likelihood = self._estimate_deposit_likelihood_from_summary(
                student.risk_level,
                gpa_value,
                transcript_count,
                max_parser_confidence,
            )
            next_best_action = self._build_next_best_action(student.risk_level, student.current_stage, institution_goal)
            owner_summary = self._owner_summary(prospect_owner or advisor)
            readiness = self._readiness_summary_from_stage(student.current_stage, student.risk_level)
            program_summary = StudentProgramSummary(id=(str(program_row.id) if program_row else None), name=(program_row.name if program_row else prospect.program_interest if prospect else "Transcript intake"))
            records.append(
                Student360ListRecord(
                    id=str(student.id),
                    studentId=student.external_student_id or str(student.id),
                    name=self._join_name(student.first_name, student.last_name, fallback="Unknown Student"),
                    preferredName=student.preferred_name or student.first_name,
                    email=student.email,
                    phone=student.phone,
                    program=program_summary,
                    population=prospect.population if prospect else self._student_type(student.accepted_credits),
                    studentType=prospect.population if prospect else self._student_type(student.accepted_credits),
                    source=prospect.source if prospect else "transcript_first",
                    sourceCategory=prospect.source_category if prospect else "direct",
                    campaign=prospect.campaign if prospect else None,
                    termInterest=prospect.term_interest if prospect else None,
                    institutionGoal=institution_goal,
                    stage=prospect.lifecycle_stage if prospect else self._title_case(student.current_stage or "decision-ready"),
                    risk=self._title_case(student.risk_level or "low"),
                    owner=owner_summary,
                    assignedOwner=owner_summary,
                    advisor=owner_summary.name,
                    readiness=readiness,
                    city=self._format_location(student.city, student.state, student.country),
                    fitScore=fit_score,
                    depositLikelihood=deposit_likelihood,
                    summary=student.summary or self._default_summary_from_institution(institution_goal, student.risk_level),
                    gpa=gpa_value,
                    creditsAccepted=self._to_float(student.accepted_credits, 0),
                    transcriptsCount=transcript_count,
                    lastActivity=self._format_timestamp(student.latest_activity_at or student.updated_at),
                    tags=self._build_tags(program_summary.name, student.risk_level, student.current_stage),
                    nextBestAction=next_best_action,
                )
            )
        return records

    def _resolve_student_row(self, session: Session, tenant_id: UUID, student_id: str) -> Student | None:
        try:
            student_uuid = UUID(student_id)
            row = session.execute(select(Student).where(Student.tenant_id == tenant_id, Student.id == student_uuid)).scalar_one_or_none()
            if row is not None:
                return row
        except ValueError:
            pass
        for external_id in self._student_identifier_variants(student_id):
            row = session.execute(select(Student).where(Student.tenant_id == tenant_id, Student.external_student_id == external_id)).scalar_one_or_none()
            if row is not None:
                return row
        return None

    def _build_canonical_timeline(
        self,
        session: Session,
        tenant_id: UUID,
        student: Student,
        authorization: Any | None,
    ) -> list[StudentTimelineEvent]:
        events: list[StudentTimelineEvent] = []
        actors = self._load_actor_map(session, tenant_id)
        can_academic = self._can_access_tier(authorization, SENSITIVITY_ACADEMIC_RECORD)
        can_transcript = self._can_access_tier(authorization, SENSITIVITY_TRANSCRIPT_IMAGES) and self._can_permission(authorization, "view_sensitive_docs")
        can_trust = self._can_access_tier(authorization, SENSITIVITY_TRUST_FRAUD_FLAGS)

        prospects = session.execute(
            select(Prospect).where(Prospect.tenant_id == tenant_id, Prospect.student_id == student.id).order_by(Prospect.created_at.desc())
        ).scalars().all()
        for prospect in prospects:
            events.append(
                self._timeline_event(
                    event_id=prospect.id,
                    event_type="inquiry",
                    title="Inquiry created",
                    description=f"{prospect.first_name} {prospect.last_name} entered from {prospect.source}.",
                    occurred_at=prospect.created_at,
                    actor=None,
                    source="prospect",
                    status=prospect.status,
                    entity_type="prospect",
                    entity_id=prospect.id,
                )
            )
            if prospect.source or prospect.campaign:
                source_detail = " from ".join(part for part in [prospect.source, prospect.campaign] if part)
                events.append(
                    self._timeline_event(
                        event_id=f"{prospect.id}:source",
                        event_type="source",
                        title="Source captured",
                        description=f"Captured {source_detail}.",
                        occurred_at=prospect.created_at,
                        actor=None,
                        source="prospect",
                        status=prospect.source_category,
                        entity_type="prospect",
                        entity_id=prospect.id,
                    )
                )
            if "application" in (prospect.lifecycle_stage or "").lower() or prospect.status in {"started", "submitted"}:
                events.append(
                    self._timeline_event(
                        event_id=f"{prospect.id}:application",
                        event_type="application",
                        title="Application activity recorded",
                        description=f"Lifecycle stage is {prospect.lifecycle_stage}.",
                        occurred_at=prospect.updated_at,
                        actor=self._actor_for_user(actors, prospect.owner_user_id),
                        source="prospect",
                        status=prospect.lifecycle_stage,
                        entity_type="prospect",
                        entity_id=prospect.id,
                    )
                )
            if prospect.owner_user_id:
                actor = self._actor_for_user(actors, prospect.owner_user_id)
                events.append(
                    self._timeline_event(
                        event_id=f"{prospect.id}:owner",
                        event_type="owner",
                        title="Owner assigned",
                        description=f"Assigned to {actor.name if actor else 'owner'}.",
                        occurred_at=prospect.updated_at,
                        actor=actor,
                        source="prospect",
                        status="assigned",
                        entity_type="prospect",
                        entity_id=prospect.id,
                    )
                )
            source_refs = session.execute(
                select(ProspectSourceReference)
                .where(ProspectSourceReference.tenant_id == tenant_id, ProspectSourceReference.prospect_id == prospect.id)
                .order_by(ProspectSourceReference.captured_at.desc())
            ).scalars().all()
            for source_ref in source_refs:
                events.append(
                    self._timeline_event(
                        event_id=source_ref.id,
                        event_type="source",
                        title="Source reference captured",
                        description=f"{source_ref.source} reference captured.",
                        occurred_at=source_ref.captured_at,
                        actor=None,
                        source="source_reference",
                        status=source_ref.source_category,
                        entity_type="prospect_source_reference",
                        entity_id=source_ref.id,
                    )
                )

        events.append(
            self._timeline_event(
                event_id=f"{student.id}:created",
                event_type="stage",
                title="Student record created",
                description=f"Admissions record opened in {student.current_stage}.",
                occurred_at=student.created_at,
                actor=None,
                source="student",
                status=student.current_stage,
                entity_type="student",
                entity_id=student.id,
            )
        )

        checklist_items = session.execute(
            select(DbStudentChecklistItem)
            .where(DbStudentChecklistItem.tenant_id == tenant_id, DbStudentChecklistItem.student_id == student.id)
            .order_by(DbStudentChecklistItem.updated_at.desc())
        ).scalars().all()
        for item in checklist_items:
            actor = self._actor_for_user(actors, item.updated_by_user_id) if item.updated_by_user_id else None
            events.append(
                self._timeline_event(
                    event_id=item.id,
                    event_type="checklist",
                    title=f"{item.label} marked {self._title_case(item.status)}",
                    description=f"{actor.name if actor else 'System'} updated {item.label}.",
                    occurred_at=item.updated_at,
                    actor=actor,
                    source="checklist",
                    status=item.status,
                    entity_type="student_checklist_item",
                    entity_id=item.id,
                )
            )

        transcript_rows = session.execute(
            select(Transcript, DocumentUpload, TranscriptDemographics, TranscriptParseRun)
            .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(TranscriptParseRun, TranscriptParseRun.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id == student.id)
            .order_by(Transcript.created_at.desc())
        ).all()
        transcript_ids = [transcript.id for transcript, *_ in transcript_rows]
        for transcript, upload, demographics, parse_run in transcript_rows:
            upload_actor = self._actor_for_user(actors, upload.uploaded_by_user_id) if upload.uploaded_by_user_id else None
            events.append(
                self._timeline_event(
                    event_id=upload.id,
                    event_type="document",
                    title="Document uploaded",
                    description=f"{upload.original_filename} uploaded.",
                    occurred_at=upload.uploaded_at,
                    actor=upload_actor,
                    source="document",
                    status=upload.upload_status,
                    entity_type="document_upload",
                    entity_id=upload.id,
                )
            )
            if parse_run:
                course_count = len((parse_run.response_json or {}).get("courses") or [])
                institution = self._safe_str(demographics.institution_name if demographics else None, "Unknown institution")
                detail = f"Parsed {course_count} courses from {institution}." if can_academic and can_transcript else "Transcript evidence parsed; academic detail is restricted."
                events.append(
                    self._timeline_event(
                        event_id=parse_run.id,
                        event_type="transcript",
                        title="Transcript parsed",
                        description=detail,
                        occurred_at=parse_run.completed_at or parse_run.started_at,
                        actor=None,
                        source="transcript_pipeline",
                        status=parse_run.status,
                        entity_type="transcript_parse_run",
                        entity_id=parse_run.id,
                        sensitivity_tier="academic_record",
                    )
                )

        trust_flags = session.execute(
            select(TrustFlag)
            .where(TrustFlag.tenant_id == tenant_id, TrustFlag.student_id == student.id)
            .order_by(TrustFlag.detected_at.desc())
        ).scalars().all()
        for flag in trust_flags:
            description = flag.reason if can_trust else "Trust review status changed; rationale is restricted."
            events.append(
                self._timeline_event(
                    event_id=flag.id,
                    event_type="trust",
                    title=f"Trust flag {self._title_case(flag.status)}",
                    description=description,
                    occurred_at=flag.resolved_at or flag.detected_at,
                    actor=self._actor_for_user(actors, flag.resolved_by_user_id or flag.assigned_to_user_id),
                    source="trust",
                    status=flag.status,
                    entity_type="trust_flag",
                    entity_id=flag.id,
                    sensitivity_tier="trust_fraud_flags",
                )
            )

        readiness = session.execute(
            select(StudentDecisionReadiness).where(StudentDecisionReadiness.tenant_id == tenant_id, StudentDecisionReadiness.student_id == student.id)
        ).scalar_one_or_none()
        if readiness:
            events.append(
                self._timeline_event(
                    event_id=readiness.id,
                    event_type="readiness",
                    title=f"Readiness set to {self._title_case(readiness.readiness_state)}",
                    description=readiness.reason_label,
                    occurred_at=readiness.computed_at,
                    actor=None,
                    source="readiness",
                    status=readiness.readiness_state,
                    entity_type="student_decision_readiness",
                    entity_id=readiness.id,
                )
            )

        decision_packets = session.execute(
            select(DecisionPacket).where(DecisionPacket.tenant_id == tenant_id, DecisionPacket.student_id == student.id).order_by(DecisionPacket.created_at.desc())
        ).scalars().all()
        for packet in decision_packets:
            events.append(
                self._timeline_event(
                    event_id=packet.id,
                    event_type="decision",
                    title=f"Decision packet {self._title_case(packet.status)}",
                    description=packet.reason,
                    occurred_at=packet.updated_at or packet.created_at,
                    actor=self._actor_for_user(actors, packet.assigned_to_user_id or packet.created_by_user_id),
                    source="decision",
                    status=packet.status,
                    entity_type="decision_packet",
                    entity_id=packet.id,
                    sensitivity_tier="academic_record",
                )
            )
            packet_events = session.execute(
                select(DecisionPacketEvent).where(DecisionPacketEvent.tenant_id == tenant_id, DecisionPacketEvent.decision_packet_id == packet.id).order_by(DecisionPacketEvent.event_at.desc())
            ).scalars().all()
            for packet_event in packet_events:
                events.append(
                    self._timeline_event(
                        event_id=packet_event.id,
                        event_type="decision",
                        title=packet_event.label,
                        description=packet_event.detail,
                        occurred_at=packet_event.event_at,
                        actor=self._actor_for_user(actors, packet_event.actor_user_id),
                        source="decision",
                        status=packet_event.event_type,
                        entity_type="decision_packet_event",
                        entity_id=packet_event.id,
                        sensitivity_tier="academic_record",
                    )
                )

        milestones = session.execute(
            select(StudentEnrollmentMilestone)
            .where(StudentEnrollmentMilestone.tenant_id == tenant_id, StudentEnrollmentMilestone.student_id == student.id)
            .order_by(StudentEnrollmentMilestone.updated_at.desc())
        ).scalars().all()
        for milestone in milestones:
            event_type = "deposit" if "deposit" in milestone.milestone_code.lower() else "yield"
            events.append(
                self._timeline_event(
                    event_id=milestone.id,
                    event_type=event_type,
                    title=milestone.milestone_label,
                    description=f"Milestone status is {milestone.status}.",
                    occurred_at=milestone.achieved_at or milestone.updated_at,
                    actor=None,
                    source="enrollment",
                    status=milestone.status,
                    entity_type="student_enrollment_milestone",
                    entity_id=milestone.id,
                )
            )

        yield_score = session.execute(
            select(StudentYieldScore).where(StudentYieldScore.tenant_id == tenant_id, StudentYieldScore.student_id == student.id)
        ).scalar_one_or_none()
        if yield_score:
            events.append(
                self._timeline_event(
                    event_id=yield_score.id,
                    event_type="yield",
                    title="Yield score computed",
                    description=f"Yield score is {yield_score.score}.",
                    occurred_at=yield_score.computed_at,
                    actor=None,
                    source="yield",
                    status=yield_score.reason_code,
                    entity_type="student_yield_score",
                    entity_id=yield_score.id,
                )
            )

        notes = session.execute(
            select(StudentNote).where(StudentNote.tenant_id == tenant_id, StudentNote.student_id == student.id).order_by(StudentNote.created_at.desc())
        ).scalars().all()
        for note in notes:
            events.append(
                self._timeline_event(
                    event_id=note.id,
                    event_type="interaction",
                    title=f"{self._title_case(note.note_type)} note added",
                    description=note.body if not note.is_internal else "Internal note added.",
                    occurred_at=note.created_at,
                    actor=self._actor_for_user(actors, note.author_user_id),
                    source="interaction",
                    status=note.note_type,
                    entity_type="student_note",
                    entity_id=note.id,
                    sensitivity_tier="notes" if note.is_internal else "standard",
                )
            )

        tasks = session.execute(
            select(StudentTask).where(StudentTask.tenant_id == tenant_id, StudentTask.student_id == student.id).order_by(StudentTask.updated_at.desc())
        ).scalars().all()
        for task in tasks:
            event_type = "handoff" if "handoff" in task.task_type.lower() else "interaction"
            events.append(
                self._timeline_event(
                    event_id=task.id,
                    event_type=event_type,
                    title=task.label,
                    description=f"Task status is {task.status}.",
                    occurred_at=task.completed_at or task.updated_at,
                    actor=self._actor_for_user(actors, task.assigned_to_user_id),
                    source="task",
                    status=task.status,
                    entity_type="student_task",
                    entity_id=task.id,
                )
            )

        audit_events = session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                or_(
                    AuditEvent.entity_id == student.id,
                    AuditEvent.payload_json["student_id"].astext == str(student.id),
                    AuditEvent.entity_id.in_(transcript_ids) if transcript_ids else False,
                ),
            )
            .order_by(AuditEvent.occurred_at.desc())
            .limit(100)
        ).scalars().all()
        for audit_event in audit_events:
            event_type = self._timeline_type_from_audit(audit_event)
            description = audit_event.error_message if audit_event.error_message else self._audit_description(audit_event, can_trust=can_trust)
            events.append(
                self._timeline_event(
                    event_id=audit_event.id,
                    event_type=event_type,
                    title=self._title_case(audit_event.action),
                    description=description,
                    occurred_at=audit_event.occurred_at,
                    actor=self._actor_for_user(actors, audit_event.actor_user_id),
                    source=audit_event.source or "audit",
                    status="success" if audit_event.success else "failed",
                    entity_type=audit_event.entity_type,
                    entity_id=audit_event.entity_id,
                    sensitivity_tier="trust_fraud_flags" if event_type == "trust" else "standard",
                )
            )

        return sorted(events, key=lambda event: event.occurredAt, reverse=True)

    def _build_transcript_derived_timeline(
        self,
        session: Session,
        tenant_id: UUID,
        student_id: str,
        authorization: Any | None,
    ) -> list[StudentTimelineEvent]:
        record = self._get_transcript_derived_student(session, tenant_id, student_id)
        if record is None:
            return []
        can_academic = self._can_access_tier(authorization, SENSITIVITY_ACADEMIC_RECORD)
        can_transcript = self._can_access_tier(authorization, SENSITIVITY_TRANSCRIPT_IMAGES) and self._can_permission(authorization, "view_sensitive_docs")
        events: list[StudentTimelineEvent] = []
        for transcript in record.transcripts or []:
            events.append(
                self._timeline_event(
                    event_id=f"{transcript.id}:document",
                    event_type="document",
                    title="Document uploaded",
                    description=f"{transcript.source} uploaded.",
                    occurred_at=transcript.uploadedAt if isinstance(transcript.uploadedAt, datetime) else None,
                    actor=None,
                    source="document",
                    status=transcript.status,
                    entity_type="transcript",
                    entity_id=transcript.id,
                )
            )
            detail = f"Parsed {len(transcript.courses)} courses from {transcript.institution}." if can_academic and can_transcript else "Transcript evidence parsed; academic detail is restricted."
            events.append(
                self._timeline_event(
                    event_id=f"{transcript.id}:parse",
                    event_type="transcript",
                    title="Transcript parsed",
                    description=detail,
                    occurred_at=transcript.uploadedAt if isinstance(transcript.uploadedAt, datetime) else None,
                    actor=None,
                    source="transcript_pipeline",
                    status=transcript.status,
                    entity_type="transcript",
                    entity_id=transcript.id,
                    sensitivity_tier="academic_record",
                )
            )
        return sorted(events, key=lambda event: event.occurredAt, reverse=True)

    def _list_transcript_derived_students(
        self,
        session: Session,
        tenant_id: UUID,
        q: str | None,
        *,
        stage: str | None = None,
        population: str | None = None,
        owner: str | None = None,
        source: str | None = None,
        program: str | None = None,
    ) -> list[Student360ListRecord]:
        stmt = (
            select(Transcript, TranscriptDemographics)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        rows = session.execute(stmt).all()
        grouped: dict[str, list[tuple[Transcript, TranscriptDemographics | None]]] = defaultdict(list)
        for transcript, demographics in rows:
            key = self._derive_student_key(transcript, demographics)
            grouped[key].append((transcript, demographics))

        records: list[Student360ListRecord] = []
        for key, transcript_rows in grouped.items():
            latest_transcript, latest_demographics = transcript_rows[0]
            name = self._demographic_name(latest_demographics)
            program = "Transcript intake"
            institution_goal = self._safe_str(latest_demographics.institution_name if latest_demographics else None, "Unknown institution")
            record_risk = self._derive_risk_from_transcripts([item[0] for item in transcript_rows])
            record_stage = self._derive_stage_from_transcripts([item[0] for item in transcript_rows])
            gpa_value = self._derive_gpa_from_demographics([item[1] for item in transcript_rows])
            transcript_count = len(transcript_rows)
            fit_score = self._estimate_fit_score_from_summary(gpa_value, transcript_count, latest_transcript.parser_confidence)
            deposit_likelihood = self._estimate_deposit_likelihood_from_summary(
                record_risk,
                gpa_value,
                transcript_count,
                latest_transcript.parser_confidence,
            )
            record = Student360ListRecord(
                id=key,
                studentId=key,
                name=name,
                preferredName=name.split(" ")[0] if name else None,
                email=None,
                phone=None,
                program=StudentProgramSummary(id=None, name=program),
                population="transfer" if self._derive_credits_from_demographics([item[1] for item in transcript_rows]) > 0 else "first_year",
                studentType="transfer" if self._derive_credits_from_demographics([item[1] for item in transcript_rows]) > 0 else "first_year",
                source="transcript_first",
                sourceCategory="direct",
                institutionGoal=institution_goal,
                stage=record_stage,
                risk=record_risk,
                owner=StudentOwnerSummary(id=None, name="Unassigned"),
                assignedOwner=StudentOwnerSummary(id=None, name="Unassigned"),
                advisor="Unassigned",
                readiness=self._readiness_summary_from_stage(record_stage, record_risk),
                city=self._format_location(None, latest_demographics.institution_state if latest_demographics else None, latest_demographics.institution_country if latest_demographics else None),
                fitScore=fit_score,
                depositLikelihood=deposit_likelihood,
                summary=self._default_summary_from_institution(institution_goal, record_risk),
                gpa=gpa_value,
                creditsAccepted=self._derive_credits_from_demographics([item[1] for item in transcript_rows]),
                transcriptsCount=transcript_count,
                lastActivity=self._format_timestamp(latest_transcript.updated_at),
                tags=self._build_tags(program, record_risk, record_stage),
                nextBestAction=self._build_next_best_action(record_risk, record_stage, institution_goal),
            )
            if self._matches_list_filters(record, stage=stage, population=population, owner=owner, source=source, program=program) and self._matches_search(record, q):
                records.append(record)
        return records

    def _get_canonical_student(self, session: Session, tenant_id: UUID, student_id: str) -> Student360Record | None:
        stmt = (
            select(Student, Program, Institution, AppUser)
            .outerjoin(Program, Program.id == Student.target_program_id)
            .outerjoin(Institution, Institution.id == Student.target_institution_id)
            .outerjoin(AppUser, AppUser.id == Student.advisor_user_id)
        )
        row = None
        try:
            student_uuid = UUID(student_id)
            row = session.execute(
                stmt.where(Student.tenant_id == tenant_id, Student.id == student_uuid)
            ).one_or_none()
        except ValueError:
            pass
        if row is None:
            for external_id in self._student_identifier_variants(student_id):
                row = session.execute(
                    stmt.where(Student.tenant_id == tenant_id, Student.external_student_id == external_id)
                ).one_or_none()
                if row is not None:
                    break
        if row is None:
            return None

        student, program, institution, advisor = row
        prospect, prospect_owner = self._latest_prospect_for_student(session, tenant_id, student.id)
        transcript_map = self._load_transcripts_for_students(session, tenant_id, [student.id])
        transcripts = transcript_map.get(student.id, [])
        recommendation = self._build_recommendation(transcripts, student.risk_level, student.current_stage)
        institution_goal = institution.name if institution else self._latest_institution_name(transcripts)
        owner_summary = self._owner_summary(prospect_owner or advisor)
        readiness = self._load_readiness_summary(session, tenant_id, student.id) or self._readiness_summary_from_stage(student.current_stage, student.risk_level)
        program_summary = StudentProgramSummary(id=(str(program.id) if program else None), name=(program.name if program else prospect.program_interest if prospect else "Transcript intake"))
        return Student360Record(
            id=str(student.id),
            studentId=student.external_student_id or str(student.id),
            name=self._join_name(student.first_name, student.last_name, fallback="Unknown Student"),
            preferredName=student.preferred_name or student.first_name or "Student",
            email=student.email,
            phone=student.phone,
            program=program_summary,
            population=prospect.population if prospect else self._student_type(student.accepted_credits),
            studentType=prospect.population if prospect else self._student_type(student.accepted_credits),
            source=prospect.source if prospect else "transcript_first",
            sourceCategory=prospect.source_category if prospect else "direct",
            campaign=prospect.campaign if prospect else None,
            termInterest=prospect.term_interest if prospect else None,
            institutionGoal=institution_goal,
            stage=prospect.lifecycle_stage if prospect else self._title_case(student.current_stage or "decision-ready"),
            risk=self._title_case(student.risk_level or "low"),
            fitScore=self._estimate_fit_score(student.latest_cumulative_gpa, transcripts),
            depositLikelihood=self._estimate_deposit_likelihood(student.risk_level, student.latest_cumulative_gpa, transcripts),
            summary=student.summary or self._default_summary(transcripts, student.risk_level),
            gpa=self._to_float(student.latest_cumulative_gpa),
            creditsAccepted=self._to_float(student.accepted_credits, 0),
            transcriptsCount=len(transcripts),
            owner=owner_summary,
            assignedOwner=owner_summary,
            advisor=owner_summary.name,
            readiness=readiness,
            tags=self._build_tags(program_summary.name, student.risk_level, student.current_stage),
            nextBestAction=recommendation.nextBestAction,
            city=self._format_location(student.city, student.state, student.country),
            lastActivity=self._format_timestamp(student.latest_activity_at or student.updated_at),
            checklist=self._build_checklist(transcripts, student.risk_level),
            transcripts=transcripts,
            termGpa=self._build_term_gpa(transcripts),
            recommendation=recommendation,
        )

    def _get_transcript_derived_student(self, session: Session, tenant_id: UUID, student_id: str) -> Student360Record | None:
        stmt = (
            select(Transcript, DocumentUpload, TranscriptDemographics, TranscriptParseRun)
            .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(TranscriptParseRun, TranscriptParseRun.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id)
            .order_by(Transcript.created_at.desc())
        )
        grouped: dict[str, list[_TranscriptBundle]] = defaultdict(list)
        for transcript, upload, demographics, parse_run in session.execute(stmt).all():
            key = self._derive_student_key(transcript, demographics)
            grouped[key].append(_TranscriptBundle(transcript=transcript, upload=upload, demographics=demographics, parse_run=parse_run))

        bundles = None
        for candidate_key in self._student_identifier_variants(student_id):
            bundles = grouped.get(candidate_key)
            if bundles:
                break
        if not bundles:
            return None

        latest = bundles[0]
        name = self._demographic_name(latest.demographics)
        transcripts = self._map_transcript_records(bundles)
        risk = self._derive_risk_from_bundles(bundles)
        stage = self._derive_stage_from_bundles(bundles)
        recommendation = self._build_recommendation(transcripts, risk, stage)
        return Student360Record(
            id=student_id,
            studentId=student_id,
            name=name,
            preferredName=(latest.demographics.student_first_name if latest.demographics and latest.demographics.student_first_name else name.split(" ")[0]),
            email=None,
            phone=None,
            program=StudentProgramSummary(id=None, name="Transcript intake"),
            population="transfer" if self._derive_credits_from_bundles(bundles) > 0 else "first_year",
            studentType="transfer" if self._derive_credits_from_bundles(bundles) > 0 else "first_year",
            source="transcript_first",
            sourceCategory="direct",
            institutionGoal=self._safe_str(latest.demographics.institution_name if latest.demographics else None, "Unknown institution"),
            stage=stage,
            risk=risk,
            fitScore=self._estimate_fit_score(self._derive_gpa_from_bundles(bundles), transcripts),
            depositLikelihood=self._estimate_deposit_likelihood(risk, self._derive_gpa_from_bundles(bundles), transcripts),
            summary=self._default_summary(transcripts, risk),
            gpa=self._derive_gpa_from_bundles(bundles),
            creditsAccepted=self._derive_credits_from_bundles(bundles),
            transcriptsCount=len(bundles),
            owner=StudentOwnerSummary(id=None, name="Unassigned"),
            assignedOwner=StudentOwnerSummary(id=None, name="Unassigned"),
            advisor="Unassigned",
            readiness=self._readiness_summary_from_stage(stage, risk),
            tags=self._build_tags("Transcript intake", risk, stage),
            nextBestAction=recommendation.nextBestAction,
            city=self._format_location(
                None,
                latest.demographics.institution_state if latest.demographics else None,
                latest.demographics.institution_country if latest.demographics else None,
            ),
            lastActivity=self._format_timestamp(latest.transcript.updated_at),
            checklist=self._build_checklist(transcripts, risk),
            transcripts=transcripts,
            termGpa=self._build_term_gpa(transcripts),
            recommendation=recommendation,
        )

    def _load_transcripts_for_students(self, session: Session, tenant_id: UUID, student_ids: list[UUID]) -> dict[UUID, list[StudentTranscriptRecord]]:
        if not student_ids:
            return {}
        stmt = (
            select(Transcript, DocumentUpload, TranscriptDemographics, TranscriptParseRun)
            .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .outerjoin(TranscriptParseRun, TranscriptParseRun.transcript_id == Transcript.id)
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id.in_(student_ids))
            .order_by(Transcript.created_at.desc())
        )
        grouped: dict[UUID, list[_TranscriptBundle]] = defaultdict(list)
        for transcript, upload, demographics, parse_run in session.execute(stmt).all():
            if transcript.student_id:
                grouped[transcript.student_id].append(_TranscriptBundle(transcript, upload, demographics, parse_run))
        return {student_id: self._map_transcript_records(bundles) for student_id, bundles in grouped.items()}

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

    def _map_transcript_records(self, bundles: list[_TranscriptBundle]) -> list[StudentTranscriptRecord]:
        records: list[StudentTranscriptRecord] = []
        for bundle in bundles:
            payload = bundle.parse_run.response_json if bundle.parse_run and bundle.parse_run.response_json else {}
            raw_courses = payload.get("courses") or []
            records.append(
                StudentTranscriptRecord(
                    id=str(bundle.transcript.id),
                    source=bundle.upload.original_filename,
                    institution=self._safe_str(bundle.demographics.institution_name if bundle.demographics else None, "Unknown institution"),
                    type=self._title_case(bundle.transcript.document_type.replace("_", " ")) if bundle.transcript.document_type else "Transcript",
                    uploadedAt=bundle.upload.uploaded_at,
                    status=self._title_case(bundle.transcript.status),
                    confidence=round(self._to_float(bundle.transcript.parser_confidence) * 100, 1),
                    credits=self._to_float(bundle.demographics.total_credits_earned if bundle.demographics else None, 0),
                    pages=bundle.transcript.page_count or 1,
                    owner=bundle.parse_run.parser_name if bundle.parse_run else "transcript_pipeline",
                    notes=self._resolve_transcript_note(bundle),
                    steps=self._build_steps(bundle),
                    courses=[StudentTranscriptCourse(**self._filter_course_fields(course)) for course in raw_courses],
                    rawDocument=payload or None,
                )
            )
        return records

    def _build_steps(self, bundle: _TranscriptBundle) -> list[StudentTimelineStep]:
        created = self._format_clock(bundle.upload.uploaded_at)
        steps = [StudentTimelineStep(label="Upload received", time=created)]
        if bundle.parse_run:
            steps.append(StudentTimelineStep(label=self._title_case(bundle.parse_run.status), time=self._format_clock(bundle.parse_run.completed_at or bundle.parse_run.started_at)))
        return steps

    def _build_term_gpa(self, transcripts: list[StudentTranscriptRecord]) -> list[StudentTermGpa]:
        for transcript in transcripts:
            raw = transcript.rawDocument or {}
            term_gpas = raw.get("termGPAs") or []
            if term_gpas:
                return [
                    StudentTermGpa(
                        term=" ".join(part for part in [item.get("term"), item.get("year")] if part).strip() or f"Term {index + 1}",
                        gpa=self._to_float(item.get("simpleGPA")),
                        credits=self._to_float(item.get("simpleUnitsEarned"), 0),
                    )
                    for index, item in enumerate(term_gpas)
                ]
        return []

    def _build_checklist(self, transcripts: list[StudentTranscriptRecord], risk_level: str | None) -> list[StudentChecklistItem]:
        has_transcripts = bool(transcripts)
        high_risk = (risk_level or "").lower() == "high"
        return [
            StudentChecklistItem(label="Identity matched", done=has_transcripts),
            StudentChecklistItem(label="Document parsed", done=has_transcripts),
            StudentChecklistItem(label="Trust scan cleared", done=not high_risk),
            StudentChecklistItem(label="Decision packet built", done=has_transcripts and not high_risk),
        ]

    def _build_recommendation(self, transcripts: list[StudentTranscriptRecord], risk_level: str | None, stage: str | None) -> StudentRecommendation:
        high_risk = (risk_level or "").lower() == "high"
        if high_risk:
            return StudentRecommendation(
                summary="Do not release outcome until trust review is resolved.",
                fitNarrative="The available records indicate document or provenance issues that require manual review before release.",
                nextBestAction="Review flagged transcript evidence and request an official replacement if needed.",
            )
        institution = self._latest_institution_name(transcripts)
        return StudentRecommendation(
            summary="Latest transcript is ready for counselor review.",
            fitNarrative=f"Current transcript evidence from {institution} was parsed successfully and is available for review.",
            nextBestAction="Open the student record and review the latest transcript outcome.",
        )

    def _latest_prospect_for_student(self, session: Session, tenant_id: UUID, student_id: UUID) -> tuple[Prospect | None, AppUser | None]:
        prospect = session.execute(
            select(Prospect)
            .where(Prospect.tenant_id == tenant_id, Prospect.student_id == student_id)
            .order_by(Prospect.updated_at.desc(), Prospect.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if prospect is None or prospect.owner_user_id is None:
            return prospect, None
        owner = session.execute(select(AppUser).where(AppUser.id == prospect.owner_user_id)).scalar_one_or_none()
        return prospect, owner

    def _load_readiness_summary(self, session: Session, tenant_id: UUID, student_id: UUID) -> StudentReadinessSummary | None:
        readiness = session.execute(
            select(StudentDecisionReadiness).where(
                StudentDecisionReadiness.tenant_id == tenant_id,
                StudentDecisionReadiness.student_id == student_id,
            )
        ).scalar_one_or_none()
        if readiness is None:
            return None
        return StudentReadinessSummary(
            state=readiness.readiness_state,
            label=readiness.reason_label or self._title_case(readiness.readiness_state),
            reason=readiness.reason_label or readiness.reason_code,
            tone="high" if readiness.trust_blocked else "medium" if readiness.blocking_item_count else "low",
        )

    def _readiness_summary_from_stage(self, stage: str | None, risk_level: str | None) -> StudentReadinessSummary:
        normalized_stage = (stage or "").lower().replace("_", " ")
        risk = (risk_level or "").lower()
        if risk == "high" or "trust" in normalized_stage:
            return StudentReadinessSummary(state="blocked", label="Blocked", reason="Trust review is blocking release.", tone="high")
        if "pending" in normalized_stage or "incomplete" in normalized_stage:
            return StudentReadinessSummary(state="incomplete", label="Incomplete", reason="Required admissions items remain.", tone="medium")
        return StudentReadinessSummary(state="nearly_complete", label="Nearly complete", reason="Transcript evidence is ready for review.", tone="medium")

    def _owner_summary(self, user: AppUser | None) -> StudentOwnerSummary:
        if user is None:
            return StudentOwnerSummary(id=None, name="Unassigned")
        return StudentOwnerSummary(id=str(user.id), name=user.display_name, email=user.email)

    def _load_actor_map(self, session: Session, tenant_id: UUID) -> dict[UUID, AppUser]:
        rows = session.execute(select(AppUser).where(AppUser.tenant_id == tenant_id)).scalars().all()
        return {user.id: user for user in rows}

    def _actor_for_user(self, actors: dict[UUID, AppUser], user_id: UUID | None) -> StudentTimelineActor | None:
        if user_id is None:
            return None
        user = actors.get(user_id)
        if user is None:
            return StudentTimelineActor(id=str(user_id), name="Unknown user", type="user")
        return StudentTimelineActor(id=str(user.id), name=user.display_name, type="user")

    def _timeline_event(
        self,
        *,
        event_id: UUID | str,
        event_type: str,
        title: str,
        description: str | None,
        occurred_at: datetime | None,
        actor: StudentTimelineActor | None,
        source: str,
        status: str | None,
        entity_type: str,
        entity_id: UUID | str | None,
        sensitivity_tier: str = "standard",
    ) -> StudentTimelineEvent:
        return StudentTimelineEvent(
            id=str(event_id),
            type=event_type,
            title=title,
            description=description,
            occurredAt=self._format_timestamp(occurred_at),
            actor=actor or StudentTimelineActor(id=None, name="System", type="system"),
            source=source,
            status=status,
            entity=StudentTimelineEntity(type=entity_type, id=str(entity_id) if entity_id is not None else None),
            sensitivityTier=sensitivity_tier,
        )

    def _timeline_type_from_audit(self, audit_event: AuditEvent) -> str:
        action = (audit_event.action or "").lower()
        entity_type = (audit_event.entity_type or "").lower()
        category = (audit_event.category or "").lower()
        if "checklist" in action or "checklist" in entity_type:
            return "checklist"
        if "trust" in action or "trust" in entity_type or "trust" in category:
            return "trust"
        if "decision" in action or "decision" in entity_type:
            return "decision"
        if "handoff" in action or "handoff" in category:
            return "handoff"
        if "sync" in action or "sync" in category:
            return "sync"
        if "document" in action or "document" in entity_type:
            return "document"
        if "transcript" in action or "transcript" in entity_type:
            return "transcript"
        if "owner" in action:
            return "owner"
        if "stage" in action:
            return "stage"
        return "audit"

    def _audit_description(self, audit_event: AuditEvent, *, can_trust: bool) -> str:
        if self._timeline_type_from_audit(audit_event) == "trust" and not can_trust:
            return "Trust review activity occurred; rationale is restricted."
        payload = audit_event.payload_json or {}
        for key in ("detail", "message", "reason", "status", "readiness_state"):
            if payload.get(key):
                return str(payload[key])
        return f"{self._title_case(audit_event.action)} recorded."

    def _can_permission(self, authorization: Any | None, permission: str) -> bool:
        if authorization is None:
            return False
        if hasattr(authorization, "can"):
            try:
                return bool(authorization.can(permission))
            except Exception:
                return False
        permissions = getattr(authorization, "permissions", set()) or set()
        return permission in permissions

    def _can_access_tier(self, authorization: Any | None, tier: str) -> bool:
        if authorization is None:
            return False
        if hasattr(authorization, "can_access_tier"):
            try:
                return bool(authorization.can_access_tier(tier))
            except Exception:
                return False
        tiers = getattr(authorization, "sensitivity_tiers", set()) or set()
        return tier in tiers

    def _apply_sensitivity_redaction(self, record: Student360Record, authorization: Any | None) -> Student360Record:
        can_academic = self._can_access_tier(authorization, SENSITIVITY_ACADEMIC_RECORD)
        can_transcript = self._can_access_tier(authorization, SENSITIVITY_TRANSCRIPT_IMAGES) and self._can_permission(authorization, "view_sensitive_docs")
        if not can_academic:
            record.gpa = 0.0
            record.termGpa = []
        if not can_academic or not can_transcript:
            for transcript in record.transcripts or []:
                transcript.courses = []
                transcript.rawDocument = None
                transcript.notes = "Transcript detail is not available for your access level."
        if not self._can_access_tier(authorization, SENSITIVITY_TRUST_FRAUD_FLAGS) and record.trustSummary:
            record.trustSummary = {"status": record.trustSummary.get("status", "restricted"), "detail": "Trust detail is restricted."}
        return record

    def _default_summary(self, transcripts: list[StudentTranscriptRecord], risk_level: str | None) -> str:
        high_risk = (risk_level or "").lower() == "high"
        institution = self._latest_institution_name(transcripts)
        if high_risk:
            return f"Latest transcript from {institution} is blocked pending trust review."
        return f"Latest transcript parsed from {institution}. Outcome draft prepared for review."

    def _default_summary_from_institution(self, institution: str, risk_level: str | None) -> str:
        if (risk_level or "").lower() == "high":
            return f"Latest transcript from {institution} is blocked pending trust review."
        return f"Latest transcript parsed from {institution}. Outcome draft prepared for review."

    def _build_tags(self, program: str | None, risk_level: str | None, stage: str | None) -> list[str]:
        tags: list[str] = []
        if program and program.strip():
            tags.append(program)
        if stage and stage.strip():
            tags.append(stage)
        if risk_level and risk_level.strip():
            tags.append(f"{self._title_case(risk_level)} risk")
        return tags

    def _estimate_fit_score(self, gpa: Decimal | float | None, transcripts: list[StudentTranscriptRecord]) -> int:
        gpa_value = self._to_float(gpa)
        if gpa_value >= 3.5:
            return 92
        if gpa_value >= 3.0:
            return 84
        if gpa_value >= 2.5:
            return 72
        if transcripts:
            confidence = max((t.confidence for t in transcripts), default=70.0)
            return max(55, min(90, int(confidence)))
        return 65

    def _estimate_deposit_likelihood(self, risk_level: str | None, gpa: Decimal | float | None, transcripts: list[StudentTranscriptRecord]) -> int:
        risk = (risk_level or "").lower()
        if risk == "high":
            return 20
        base = self._estimate_fit_score(gpa, transcripts) - 18
        if risk == "medium":
            base -= 12
        return max(10, min(85, base))

    def _estimate_fit_score_from_summary(
        self,
        gpa: Decimal | float | None,
        transcripts_count: int,
        parser_confidence: Decimal | float | None,
    ) -> int:
        gpa_value = self._to_float(gpa)
        if gpa_value >= 3.5:
            return 92
        if gpa_value >= 3.0:
            return 84
        if gpa_value >= 2.5:
            return 72
        if transcripts_count > 0:
            confidence = self._to_float(parser_confidence) * 100
            fallback_confidence = confidence if confidence > 0 else 70.0
            return max(55, min(90, int(fallback_confidence)))
        return 65

    def _estimate_deposit_likelihood_from_summary(
        self,
        risk_level: str | None,
        gpa: Decimal | float | None,
        transcripts_count: int,
        parser_confidence: Decimal | float | None,
    ) -> int:
        risk = (risk_level or "").lower()
        if risk == "high":
            return 20
        base = self._estimate_fit_score_from_summary(gpa, transcripts_count, parser_confidence) - 18
        if risk == "medium":
            base -= 12
        return max(10, min(85, base))

    def _build_next_best_action(self, risk_level: str | None, stage: str | None, institution: str) -> str:
        if (risk_level or "").lower() == "high":
            return "Review flagged transcript evidence and request an official replacement if needed."
        if (stage or "").lower().replace("_", " ") in {"pending evidence", "trust hold"}:
            return f"Resolve outstanding transcript issues for {institution} before releasing an outcome."
        return "Open the student record and review the latest transcript outcome."

    def _derive_student_key(self, transcript: Transcript, demographics: TranscriptDemographics | None) -> str:
        if transcript.student_id:
            return str(transcript.student_id)
        if demographics:
            if demographics.student_external_id:
                return demographics.student_external_id
            parts = [demographics.student_first_name or "", demographics.student_last_name or "", demographics.institution_name or ""]
            key = "-".join(part.strip().lower().replace(" ", "-") for part in parts if part and part.strip())
            if key:
                return key
        return str(transcript.id)

    def _student_identifier_variants(self, student_id: str) -> list[str]:
        normalized = student_id.strip()
        variants = [normalized]
        if normalized.isdigit():
            stripped = normalized.lstrip("0") or "0"
            if stripped not in variants:
                variants.append(stripped)
        return variants

    def _derive_stage_from_bundles(self, bundles: list[_TranscriptBundle]) -> str:
        latest = bundles[0].transcript
        if latest.is_fraudulent:
            return "Trust hold"
        if latest.status in {"failed", "processing"}:
            return "Pending evidence"
        return "Decision-ready"

    def _derive_risk_from_bundles(self, bundles: list[_TranscriptBundle]) -> str:
        latest = bundles[0].transcript
        if latest.is_fraudulent:
            return "High"
        confidence = self._to_float(latest.parser_confidence)
        if confidence and confidence < 0.8:
            return "Medium"
        return "Low"

    def _derive_stage_from_transcripts(self, transcripts: list[Transcript]) -> str:
        latest = transcripts[0]
        if latest.is_fraudulent:
            return "Trust hold"
        if latest.status in {"failed", "processing"}:
            return "Pending evidence"
        return "Decision-ready"

    def _derive_risk_from_transcripts(self, transcripts: list[Transcript]) -> str:
        latest = transcripts[0]
        if latest.is_fraudulent:
            return "High"
        confidence = self._to_float(latest.parser_confidence)
        if confidence and confidence < 0.8:
            return "Medium"
        return "Low"

    def _derive_gpa_from_bundles(self, bundles: list[_TranscriptBundle]) -> float:
        for bundle in bundles:
            if bundle.demographics and bundle.demographics.cumulative_gpa is not None:
                return self._to_float(bundle.demographics.cumulative_gpa)
        return 0.0

    def _derive_credits_from_bundles(self, bundles: list[_TranscriptBundle]) -> float:
        for bundle in bundles:
            if bundle.demographics and bundle.demographics.total_credits_earned is not None:
                return self._to_float(bundle.demographics.total_credits_earned, 0)
        return 0.0

    def _derive_gpa_from_demographics(self, demographics_rows: list[TranscriptDemographics | None]) -> float:
        for demographics in demographics_rows:
            if demographics and demographics.cumulative_gpa is not None:
                return self._to_float(demographics.cumulative_gpa)
        return 0.0

    def _derive_credits_from_demographics(self, demographics_rows: list[TranscriptDemographics | None]) -> float:
        for demographics in demographics_rows:
            if demographics and demographics.total_credits_earned is not None:
                return self._to_float(demographics.total_credits_earned, 0)
        return 0.0

    def _apply_student_search(self, stmt: Select, q: str | None) -> Select:
        if not q or not q.strip():
            return stmt
        pattern = f"%{q.strip()}%"
        return stmt.where(
            or_(
                Student.first_name.ilike(pattern),
                Student.last_name.ilike(pattern),
                Student.preferred_name.ilike(pattern),
                Student.external_student_id.ilike(pattern),
                cast(Student.id, String).ilike(pattern),
                Student.email.ilike(pattern),
                Student.phone.ilike(pattern),
                Student.city.ilike(pattern),
                Student.state.ilike(pattern),
                Student.country.ilike(pattern),
                Student.current_stage.ilike(pattern),
                Student.risk_level.ilike(pattern),
                Program.name.ilike(pattern),
                Institution.name.ilike(pattern),
                Prospect.source.ilike(pattern),
                Prospect.source_category.ilike(pattern),
                Prospect.campaign.ilike(pattern),
                Prospect.program_interest.ilike(pattern),
                Prospect.lifecycle_stage.ilike(pattern),
                Prospect.prior_institution.ilike(pattern),
            )
        )

    def _apply_student_filters(
        self,
        stmt: Select,
        *,
        stage: str | None = None,
        population: str | None = None,
        owner: str | None = None,
        source: str | None = None,
        program: str | None = None,
    ) -> Select:
        if stage and stage.strip():
            pattern = f"%{stage.strip()}%"
            stmt = stmt.where(or_(Student.current_stage.ilike(pattern), Prospect.lifecycle_stage.ilike(pattern)))
        if population and population.strip():
            value = population.strip()
            stmt = stmt.where(Prospect.population.ilike(f"%{value}%"))
        if owner and owner.strip():
            try:
                owner_uuid = UUID(owner.strip())
                stmt = stmt.where(or_(Student.advisor_user_id == owner_uuid, Prospect.owner_user_id == owner_uuid))
            except ValueError:
                stmt = stmt.where(Prospect.owner_user_id.is_not(None))
        if source and source.strip():
            stmt = stmt.where(Prospect.source.ilike(f"%{source.strip()}%"))
        if program and program.strip():
            pattern = f"%{program.strip()}%"
            stmt = stmt.where(or_(Program.name.ilike(pattern), Prospect.program_interest.ilike(pattern)))
        return stmt

    def _matches_list_filters(
        self,
        record: Student360ListRecord,
        *,
        stage: str | None = None,
        population: str | None = None,
        owner: str | None = None,
        source: str | None = None,
        program: str | None = None,
    ) -> bool:
        checks = [
            (stage, record.stage),
            (population, record.population or record.studentType),
            (owner, record.owner.name if record.owner else record.advisor),
            (source, record.source),
            (program, record.program.name if isinstance(record.program, StudentProgramSummary) else record.program),
        ]
        for expected, actual in checks:
            if expected and expected.strip() and expected.strip().lower() not in (actual or "").lower():
                return False
        return True

    def _matches_search(self, record: Student360ListRecord | Student360Record, q: str | None) -> bool:
        if not q or not q.strip():
            return True
        haystack = " ".join(
            [
                record.name,
                record.program.name if isinstance(record.program, StudentProgramSummary) else record.program,
                record.studentId or "",
                record.email or "",
                record.phone or "",
                record.population or "",
                record.source or "",
                record.sourceCategory or "",
                record.campaign or "",
                record.termInterest or "",
                record.institutionGoal,
                record.advisor,
                record.risk,
                record.stage,
                record.summary,
                record.nextBestAction,
                " ".join(record.tags),
                record.id,
            ]
        ).lower()
        return q.strip().lower() in haystack

    def _latest_institution_name(self, transcripts: list[StudentTranscriptRecord]) -> str:
        return transcripts[0].institution if transcripts else "Unknown institution"

    def _filter_course_fields(self, course: dict[str, Any]) -> dict[str, Any]:
        allowed = {"courseId", "courseTitle", "term", "year", "credit", "grade", "subject", "creditAttempted"}
        return {key: value for key, value in course.items() if key in allowed}

    def _default_transcript_note(self, transcript: Transcript) -> str:
        if transcript.status == "failed":
            return "Transcript processing failed."
        return "Transcript parsed and stored."

    def _resolve_transcript_note(self, bundle: _TranscriptBundle) -> str:
        if bundle.transcript.notes:
            return bundle.transcript.notes
        if bundle.parse_run and bundle.parse_run.error_message:
            return bundle.parse_run.error_message
        return self._default_transcript_note(bundle.transcript)

    def _demographic_name(self, demographics: TranscriptDemographics | None) -> str:
        if not demographics:
            return "Student record pending"
        if demographics.student_external_id:
            fallback = demographics.student_external_id
        else:
            fallback = "Student record pending"
        return self._join_name(demographics.student_first_name, demographics.student_last_name, fallback=fallback)

    def _join_name(self, first: str | None, last: str | None, fallback: str) -> str:
        name = " ".join(part for part in [first or "", last or ""] if part.strip()).strip()
        return name or fallback

    def _student_type(self, accepted_credits: Decimal | float | int | str | None) -> str:
        return "transfer" if self._to_float(accepted_credits, 0.0) > 0 else "first_year"

    def _format_location(self, city: str | None, state: str | None, country: str | None) -> str:
        parts = [part for part in [city, state, country] if part]
        return ", ".join(parts) if parts else "Location pending"

    def _safe_str(self, value: str | None, fallback: str) -> str:
        return value.strip() if value and value.strip() else fallback

    def _to_float(self, value: Decimal | float | int | str | None, fallback: float = 0.0) -> float:
        if value is None:
            return fallback
        try:
            return round(float(value), 2)
        except Exception:
            return fallback

    def _title_case(self, value: str | None) -> str:
        if not value:
            return ""
        return value.replace("_", " ").replace("-", " ").title()

    def _format_timestamp(self, value: datetime | None) -> str:
        if not value:
            return "Unknown"
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _format_clock(self, value: datetime | None) -> str:
        if not value:
            return "Now"
        return value.astimezone(timezone.utc).strftime("%I:%M %p").lstrip("0")
