from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.db.models import (
    AppUser,
    AuditEvent,
    CommunicationEvent,
    CommunicationMessage,
    DecisionPacket,
    DecisionPacketEvent,
    DocumentUpload,
    Institution,
    Program,
    Prospect,
    ProspectSourceReference,
    Student,
    StudentAddress,
    StudentAgentState,
    StudentChecklistItem as DbStudentChecklistItem,
    StudentContactMethod,
    StudentDecisionReadiness,
    StudentEnrollmentMilestone,
    StudentIdentifier,
    StudentInteraction,
    StudentNote,
    StudentRelationship,
    StudentSource,
    StudentTask,
    StudentYieldScore,
    StudentWorkState,
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
    StudentApplicationSummary,
    StudentChecklistItem,
    StudentCreateRequest,
    StudentFafsaSummary,
    StudentFinancialAidSummary,
    StudentInteractionRecord,
    StudentOwnerSummary,
    StudentProgramSummary,
    StudentRecommendation,
    StudentReadinessSummary,
    StudentScholarshipOffer,
    StudentScholarshipOption,
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
from app.services.pipeline_status import canonical_pipeline_status
from app.services.student_resolution import StudentResolutionService


@dataclass
class _TranscriptBundle:
    transcript: Transcript
    upload: DocumentUpload
    demographics: TranscriptDemographics | None
    parse_run: TranscriptParseRun | None


class Student360Service:
    VALID_INTERACTION_TYPES = {
        "call",
        "text",
        "email",
        "meeting",
        "family_conversation",
        "campus_visit",
        "webinar",
        "note",
        "communication",
        "handoff",
        "post_admit",
        "recruitment_event",
    }
    VALID_INTERACTION_OUTCOMES = {
        "reached_student",
        "left_message",
        "no_response",
        "needs_follow_up",
        "not_interested",
        "ready_to_apply",
        "ready_to_deposit",
    }

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

    def create_student(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        payload: StudentCreateRequest,
        authorization: Any | None = None,
    ) -> Student360Record:
        now = datetime.now(timezone.utc)
        external_id = self._safe_optional_str(payload.studentId or payload.id)
        first_name, last_name = self._student_name_parts(payload)
        if not first_name and not last_name:
            raise ValueError("Student first name or last name is required.")

        email = self._normalize_optional_email(payload.email)
        phone = self._safe_optional_str(payload.phone)
        population = self._normalize_population(payload.population or payload.studentType or "prospect")
        source = self._normalize_key(payload.source or "manual_entry")
        source_category = self._safe_optional_str(payload.sourceCategory) or "direct"
        stage = self._normalize_key(payload.stage or "prospect")
        program_name = self._safe_optional_str(payload.programInterest or payload.degreeProgram or payload.program)
        institution_name = self._safe_optional_str(payload.institutionGoal)

        student = self._find_existing_student_for_create(db, tenant_id, external_id, email, phone)
        if student is None:
            student = Student(
                tenant_id=tenant_id,
                external_student_id=external_id,
                first_name=first_name,
                last_name=last_name,
                preferred_name=first_name,
                email=email,
                phone=phone,
                current_stage=stage,
                risk_level="low",
                latest_activity_at=now,
            )
            db.add(student)

        institution = self._ensure_student_institution(db, tenant_id, institution_name)
        program_row = self._ensure_student_program(db, tenant_id, program_name, institution)

        student.external_student_id = external_id or student.external_student_id
        student.first_name = first_name or student.first_name
        student.last_name = last_name or student.last_name
        student.preferred_name = first_name or student.preferred_name
        student.email = email or student.email
        student.phone = phone or student.phone
        student.city = self._safe_optional_str(payload.city) or student.city
        student.state = self._safe_optional_str(payload.state) or student.state
        student.country = self._safe_optional_str(payload.country) or student.country
        student.target_program_id = program_row.id if program_row else student.target_program_id
        student.target_institution_id = institution.id if institution else student.target_institution_id
        student.current_stage = stage
        student.risk_level = student.risk_level or "low"
        student.summary = student.summary or f"{self._join_name(first_name, last_name, fallback='Student')} added from {self._title_case(source)}."
        student.latest_activity_at = now
        student.updated_at = now
        db.flush()

        if external_id:
            self._ensure_student_identifier(db, tenant_id, student.id, external_id, source)
        self._ensure_student_source(
            db,
            tenant_id=tenant_id,
            student_id=student.id,
            source=source,
            source_category=source_category,
            payload=payload,
            now=now,
        )
        if email:
            self._upsert_student_prospect(
                db,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                student=student,
                payload=payload,
                email=email,
                phone=phone,
                population=population,
                source=source,
                source_category=source_category,
                stage=stage,
                now=now,
            )

        self._write_student_audit(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            student_id=student.id,
            action="student_created",
            metadata={"externalStudentId": student.external_student_id, "source": source, "stage": stage},
            occurred_at=now,
        )

        from app.services.admissions_ops_service import AdmissionsOpsService

        AdmissionsOpsService(session_factory=self.session_factory)._ensure_student_state_for_student(db, tenant_id, student)
        db.commit()

        record = self.get_student(tenant_id, student.external_student_id or str(student.id), authorization=authorization)
        if record is None:
            raise ValueError("Student was created but could not be loaded.")
        return record

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

    def create_student_interaction(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        student_id: str,
        payload: Any,
    ) -> dict[str, StudentInteractionRecord]:
        student = self._resolve_student_row(db, tenant_id, student_id)
        if student is None:
            raise LookupError("Student not found.")

        interaction_type = (payload.type or "").strip().lower()
        if interaction_type not in self.VALID_INTERACTION_TYPES:
            raise ValueError("Invalid interaction type.")
        outcome = (payload.outcome or "").strip().lower() if payload.outcome else None
        if outcome and outcome not in self.VALID_INTERACTION_OUTCOMES:
            raise ValueError("Invalid interaction outcome.")

        occurred_at = self._parse_client_datetime(payload.occurredAt) if payload.occurredAt else datetime.now(timezone.utc)
        next_follow_up_at = self._parse_client_datetime(payload.nextFollowUpAt) if payload.nextFollowUpAt else None
        title = (payload.title or "").strip() or self._title_case(interaction_type)
        note = (payload.note or "").strip() or None
        description = (payload.description or "").strip() or note
        next_action = (payload.nextAction or "").strip() or None
        actor_name = (payload.actor or "").strip() or self._actor_name_for_user(db, actor_user_id) or "User"
        source = (payload.source or "").strip() or "student_360"
        now = datetime.now(timezone.utc)

        interaction = StudentInteraction(
            tenant_id=tenant_id,
            student_id=student.id,
            type=interaction_type,
            outcome=outcome,
            title=title,
            note=note,
            description=description,
            next_action=next_action,
            next_follow_up_at=next_follow_up_at,
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            source=source,
            created_at=now,
            updated_at=now,
        )
        db.add(interaction)
        db.flush()

        state_updates: dict[str, str | None] = {
            "contactOutcome": outcome,
            "lastActivity": "Just now",
        }
        if interaction_type != "note":
            state_updates["lastContactedAt"] = self._format_timestamp(occurred_at)
        if next_follow_up_at is not None:
            state_updates["nextFollowUpAt"] = self._format_timestamp(next_follow_up_at)
        if next_action is not None:
            state_updates["nextAction"] = next_action
        self._update_student_counselor_state(
            db,
            tenant_id=tenant_id,
            student=student,
            occurred_at=occurred_at,
            updated_at=now,
            state_updates=state_updates,
        )

        metadata = {
            "type": interaction_type,
            "outcome": outcome,
            "nextAction": next_action,
            "nextFollowUpAt": state_updates.get("nextFollowUpAt"),
            "interactionId": str(interaction.id),
        }
        self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_interaction_created", metadata=metadata, occurred_at=occurred_at)
        if next_action is not None:
            self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_next_action_updated", metadata=metadata, occurred_at=occurred_at)
        if next_follow_up_at is not None:
            self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_next_follow_up_updated", metadata=metadata, occurred_at=occurred_at)
        if interaction_type != "note":
            self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_contact_logged", metadata=metadata, occurred_at=occurred_at)

        db.commit()
        return {"interaction": self._serialize_interaction(interaction)}

    def list_student_interactions(self, tenant_id: UUID, student_id: str) -> dict[str, list[StudentInteractionRecord]]:
        session_factory = self.session_factory()
        with session_factory() as session:
            student = self._resolve_student_row(session, tenant_id, student_id)
            if student is None:
                raise LookupError("Student not found.")
            interactions = session.execute(
                select(StudentInteraction)
                .where(StudentInteraction.tenant_id == tenant_id, StudentInteraction.student_id == student.id)
                .order_by(StudentInteraction.occurred_at.desc(), StudentInteraction.created_at.desc())
            ).scalars().all()
            return {"items": [self._serialize_interaction(interaction) for interaction in interactions]}

    def log_student_communication(self, db: Session, tenant_id: UUID, actor_user_id: UUID, student_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        interaction_payload = type(
            "CommunicationPayload",
            (),
            {
                "type": "communication",
                "outcome": payload.get("outcome") or "needs_follow_up",
                "title": payload.get("templateLabel") or payload.get("templateKey") or payload.get("subject") or "Communication",
                "note": payload.get("message"),
                "description": payload.get("message"),
                "nextAction": payload.get("nextAction"),
                "nextFollowUpAt": payload.get("nextFollowUpAt"),
                "occurredAt": payload.get("occurredAt"),
                "actor": payload.get("actor"),
                "source": payload.get("source") or "student_360",
            },
        )()
        created = self.create_student_interaction(db, tenant_id, actor_user_id, student_id, interaction_payload)["interaction"]
        return {
            "communication": {
                **created.model_dump(mode="json"),
                "channel": payload.get("channel") or "other",
                "templateKey": payload.get("templateKey"),
                "templateLabel": payload.get("templateLabel"),
                "subject": payload.get("subject"),
                "message": payload.get("message"),
                "status": payload.get("status") or "logged",
                "providerMetadata": payload.get("providerMetadata") or {},
            }
        }

    def send_student_communication(self, db: Session, tenant_id: UUID, actor_user_id: UUID, student_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        student = self._resolve_student_row(db, tenant_id, student_id)
        if student is None:
            raise LookupError("Student not found.")

        channel = str(payload.get("channel") or "").strip().lower()
        provider = str(payload.get("provider") or "").strip().lower()
        if channel != "text" or provider != "twilio":
            raise ValueError("Only Twilio text sending is supported by this endpoint.")

        message = self._safe_optional_str(payload.get("message") or payload.get("body"))
        if not message:
            raise ValueError("Message is required.")

        to_phone = self._safe_optional_str(payload.get("to") or payload.get("recipientPhone") or student.phone)
        if not to_phone:
            raise ValueError("Student phone number is required before sending a text.")
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            raise ValueError("Twilio is not configured.")
        if not settings.twilio_messaging_service_sid and not settings.twilio_from_number:
            raise ValueError("Twilio sender is not configured.")

        now = datetime.now(timezone.utc)
        twilio_payload: dict[str, str] = {
            "To": to_phone,
            "Body": message,
        }
        if settings.twilio_messaging_service_sid:
            twilio_payload["MessagingServiceSid"] = settings.twilio_messaging_service_sid
        else:
            twilio_payload["From"] = settings.twilio_from_number or ""

        twilio_url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
        try:
            with httpx.Client(timeout=settings.twilio_request_timeout_seconds) as client:
                response = client.post(
                    twilio_url,
                    data=twilio_payload,
                    auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                )
            twilio_response = response.json() if response.content else {}
        except httpx.HTTPError as exc:
            raise ValueError(f"Twilio send failed: {exc}") from exc

        if response.status_code >= 400:
            detail = twilio_response.get("message") if isinstance(twilio_response, dict) else None
            raise ValueError(detail or f"Twilio send failed with status {response.status_code}.")

        provider_message_id = twilio_response.get("sid") if isinstance(twilio_response, dict) else None
        status = twilio_response.get("status") if isinstance(twilio_response, dict) else "sent"
        communication_message = CommunicationMessage(
            tenant_id=tenant_id,
            student_id=student.id,
            application_id=None,
            template_id=None,
            channel="text",
            direction="outbound",
            subject=payload.get("subject"),
            body=message,
            status=status or "sent",
            provider_message_id=provider_message_id,
            sent_at=now,
            metadata_json={
                "provider": "twilio",
                "to": to_phone,
                "templateKey": payload.get("templateKey"),
                "templateLabel": payload.get("templateLabel"),
                "twilio": twilio_response if isinstance(twilio_response, dict) else {},
            },
        )
        db.add(communication_message)
        db.flush()
        db.add(
            CommunicationEvent(
                tenant_id=tenant_id,
                message_id=communication_message.id,
                event_type=status or "sent",
                payload_json=twilio_response if isinstance(twilio_response, dict) else {},
                occurred_at=now,
            )
        )

        interaction_payload = type(
            "CommunicationPayload",
            (),
            {
                "type": "communication",
                "outcome": status or "sent",
                "title": payload.get("templateLabel") or payload.get("subject") or "Text outreach",
                "note": message,
                "description": message,
                "nextAction": payload.get("nextAction"),
                "nextFollowUpAt": payload.get("nextFollowUpAt"),
                "occurredAt": payload.get("occurredAt") or now.isoformat(),
                "actor": payload.get("actor"),
                "source": payload.get("source") or "student_360_outreach",
            },
        )()
        created = self.create_student_interaction(db, tenant_id, actor_user_id, student_id, interaction_payload)["interaction"]
        return {
            "communication": {
                **created.model_dump(mode="json"),
                "channel": "text",
                "provider": "twilio",
                "providerMessageId": provider_message_id,
                "messageSid": provider_message_id,
                "to": to_phone,
                "subject": payload.get("subject"),
                "message": message,
                "status": status or "sent",
                "templateKey": payload.get("templateKey"),
                "templateLabel": payload.get("templateLabel"),
            }
        }

    def get_post_admit_readiness(self, tenant_id: UUID, student_id: str) -> dict[str, Any]:
        session_factory = self.session_factory()
        with session_factory() as session:
            student = self._resolve_student_row(session, tenant_id, student_id)
            if student is None:
                raise LookupError("Student not found.")
            return {
                "studentId": student.external_student_id or str(student.id),
                "milestones": self._serialize_post_admit_milestones(session, tenant_id, student.id),
            }

    def update_post_admit_milestone(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        student_id: str,
        milestone_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        student = self._resolve_student_row(db, tenant_id, student_id)
        if student is None:
            raise LookupError("Student not found.")
        allowed = {code for code, _label, _owner in self._post_admit_milestone_defs()}
        if milestone_id not in allowed:
            raise ValueError("Invalid milestone id.")
        label = next(label for code, label, _owner in self._post_admit_milestone_defs() if code == milestone_id)
        milestone = db.execute(
            select(StudentEnrollmentMilestone)
            .where(
                StudentEnrollmentMilestone.tenant_id == tenant_id,
                StudentEnrollmentMilestone.student_id == student.id,
                StudentEnrollmentMilestone.milestone_code == milestone_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if milestone is None:
            milestone = StudentEnrollmentMilestone(
                tenant_id=tenant_id,
                student_id=student.id,
                milestone_code=milestone_id,
                milestone_label=payload.get("label") or label,
                status="not_started",
                metadata_json={},
            )
            db.add(milestone)
            db.flush()
        if payload.get("status"):
            milestone.status = str(payload["status"]).lower().replace(" ", "_")
        milestone.milestone_label = payload.get("label") or milestone.milestone_label
        metadata = dict(milestone.metadata_json or {})
        for key in ("owner", "dueAt", "blocker"):
            if key in payload:
                metadata[key] = payload.get(key)
        milestone.metadata_json = metadata
        milestone.updated_at = datetime.now(timezone.utc)
        if milestone.status in {"complete", "completed"}:
            milestone.achieved_at = milestone.achieved_at or milestone.updated_at
        self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_post_admit_milestone_updated", metadata={"milestoneId": milestone_id, "status": milestone.status})
        db.commit()
        return {"milestone": self._serialize_post_admit_milestones(db, tenant_id, student.id)[0] if False else self._milestone_record(milestone)}

    def create_student_handoff(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        student_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        student = self._resolve_student_row(db, tenant_id, student_id)
        if student is None:
            raise LookupError("Student not found.")
        now = datetime.now(timezone.utc)
        due_at = self._parse_client_datetime(payload["dueAt"]) if payload.get("dueAt") else None
        owner_id = self._uuid_or_none(payload.get("ownerId"))
        task = StudentTask(
            tenant_id=tenant_id,
            student_id=student.id,
            task_type=f"handoff:{payload.get('targetTeam') or 'Student Services'}",
            label=payload.get("summary") or payload.get("blocker") or "Cross-office handoff",
            status=payload.get("status") or "Open",
            assigned_to_user_id=owner_id,
            due_at=due_at,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.flush()
        metadata = {
            "targetTeam": payload.get("targetTeam") or "Student Services",
            "owner": payload.get("owner"),
            "ownerId": payload.get("ownerId"),
            "priority": payload.get("priority") or "Normal",
            "blocker": payload.get("blocker"),
            "summary": task.label,
            "createdBy": self._actor_name_for_user(db, actor_user_id) or str(actor_user_id),
        }
        self._merge_handoff_metadata(db, tenant_id, student.id, str(task.id), metadata)
        self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_handoff_created", metadata={"handoffId": str(task.id), **metadata})
        db.commit()
        task._metadata_json = metadata
        return {"handoff": self._serialize_handoff_task(task, self._load_actor_map(db, tenant_id))}

    def update_handoff_status(self, db: Session, tenant_id: UUID, actor_user_id: UUID, handoff_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        handoff_uuid = self._uuid_or_none(handoff_id)
        if handoff_uuid is None:
            raise LookupError("Handoff not found.")
        task = db.execute(
            select(StudentTask).where(StudentTask.tenant_id == tenant_id, StudentTask.id == handoff_uuid, StudentTask.task_type.ilike("%handoff%")).limit(1)
        ).scalar_one_or_none()
        if task is None:
            raise LookupError("Handoff not found.")
        previous_status = task.status
        task.status = payload.get("status") or task.status
        task.updated_at = datetime.now(timezone.utc)
        if task.status.lower() in {"complete", "completed"}:
            task.completed_at = task.completed_at or task.updated_at
        metadata = {}
        if payload.get("ownerId") or payload.get("owner") or payload.get("priority") or payload.get("blocker"):
            metadata = {k: payload.get(k) for k in ("owner", "ownerId", "priority", "blocker") if payload.get(k) is not None}
            self._merge_handoff_metadata(db, tenant_id, task.student_id, str(task.id), metadata)
        action = "student_handoff_completed" if task.completed_at else "student_handoff_status_changed"
        self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=task.student_id, action=action, metadata={"handoffId": str(task.id), "previousStatus": previous_status, "status": task.status, **metadata})
        db.commit()
        task._metadata_json = self._handoff_metadata(db, tenant_id, task.student_id).get(str(task.id), {})
        return {"handoff": self._serialize_handoff_task(task, self._load_actor_map(db, tenant_id))}

    def list_handoffs(self, tenant_id: UUID, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        session_factory = self.session_factory()
        with session_factory() as session:
            tasks = session.execute(
                select(StudentTask)
                .where(StudentTask.tenant_id == tenant_id, StudentTask.task_type.ilike("%handoff%"))
                .order_by(StudentTask.updated_at.desc())
                .offset(offset)
                .limit(limit)
            ).scalars().all()
            actors = self._load_actor_map(session, tenant_id)
            for task in tasks:
                task._metadata_json = self._handoff_metadata(session, tenant_id, task.student_id).get(str(task.id), {})
            return {"items": [self._serialize_handoff_task(task, actors) for task in tasks], "total": len(tasks), "limit": limit, "offset": offset}

    def update_student_interaction(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        student_id: str,
        interaction_id: str,
        payload: Any,
    ) -> dict[str, StudentInteractionRecord]:
        student = self._resolve_student_row(db, tenant_id, student_id)
        if student is None:
            raise LookupError("Student not found.")
        try:
            resolved_interaction_id = UUID(interaction_id)
        except ValueError as exc:
            raise LookupError("Interaction not found.") from exc
        interaction = db.execute(
            select(StudentInteraction)
            .where(
                StudentInteraction.tenant_id == tenant_id,
                StudentInteraction.student_id == student.id,
                StudentInteraction.id == resolved_interaction_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if interaction is None:
            raise LookupError("Interaction not found.")

        fields_set = getattr(payload, "model_fields_set", set()) or set()
        if "type" in fields_set and payload.type is not None:
            interaction_type = payload.type.strip().lower()
            if interaction_type not in self.VALID_INTERACTION_TYPES:
                raise ValueError("Invalid interaction type.")
            interaction.type = interaction_type
        if "outcome" in fields_set:
            outcome = payload.outcome.strip().lower() if payload.outcome else None
            if outcome and outcome not in self.VALID_INTERACTION_OUTCOMES:
                raise ValueError("Invalid interaction outcome.")
            interaction.outcome = outcome
        if "title" in fields_set and payload.title is not None:
            interaction.title = payload.title.strip() or self._title_case(interaction.type)
        if "note" in fields_set:
            interaction.note = payload.note.strip() if payload.note else None
        if "description" in fields_set:
            interaction.description = payload.description.strip() if payload.description else None
        if "nextAction" in fields_set:
            interaction.next_action = payload.nextAction.strip() if payload.nextAction else None
        if "nextFollowUpAt" in fields_set:
            interaction.next_follow_up_at = self._parse_client_datetime(payload.nextFollowUpAt) if payload.nextFollowUpAt else None
        if "occurredAt" in fields_set and payload.occurredAt:
            interaction.occurred_at = self._parse_client_datetime(payload.occurredAt)
        if "actor" in fields_set:
            interaction.actor_name = payload.actor.strip() if payload.actor else None
        if "source" in fields_set and payload.source is not None:
            interaction.source = payload.source.strip() or "student_360"
        interaction.updated_at = datetime.now(timezone.utc)

        state_updates: dict[str, str | None] = {
            "contactOutcome": interaction.outcome,
            "lastActivity": "Just now",
        }
        if interaction.type != "note":
            state_updates["lastContactedAt"] = self._format_timestamp(interaction.occurred_at)
        if interaction.next_follow_up_at is not None:
            state_updates["nextFollowUpAt"] = self._format_timestamp(interaction.next_follow_up_at)
        if interaction.next_action is not None:
            state_updates["nextAction"] = interaction.next_action
        self._update_student_counselor_state(
            db,
            tenant_id=tenant_id,
            student=student,
            occurred_at=interaction.occurred_at,
            updated_at=interaction.updated_at,
            state_updates=state_updates,
        )

        metadata = {
            "type": interaction.type,
            "outcome": interaction.outcome,
            "nextAction": interaction.next_action,
            "nextFollowUpAt": state_updates.get("nextFollowUpAt"),
            "interactionId": str(interaction.id),
        }
        self._write_student_audit(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            student_id=student.id,
            action="student_interaction_updated",
            metadata=metadata,
            occurred_at=interaction.updated_at,
        )
        db.commit()
        return {"interaction": self._serialize_interaction(interaction)}

    def update_student_program(self, db: Session, tenant_id: UUID, actor_user_id: UUID, student_id: str, program_name: str | None) -> dict[str, str]:
        program_value = (program_name or "").strip()
        if not program_value:
            raise ValueError("Program is required.")
        student = self._resolve_student_row(db, tenant_id, student_id)
        if student is None:
            raise LookupError("Student not found.")

        program = db.execute(
            select(Program)
            .where(Program.tenant_id == tenant_id, Program.name == program_value)
            .order_by(Program.created_at.asc())
            .limit(1)
        ).scalar_one_or_none()
        if program is None:
            program = Program(tenant_id=tenant_id, institution_id=student.target_institution_id, name=program_value, is_active=True)
            db.add(program)
            db.flush()

        previous_program_id = student.target_program_id
        student.target_program_id = program.id
        student.updated_at = datetime.now(timezone.utc)
        student.latest_activity_at = student.updated_at

        prospect = db.execute(
            select(Prospect)
            .where(Prospect.tenant_id == tenant_id, Prospect.student_id == student.id)
            .order_by(Prospect.updated_at.desc(), Prospect.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if prospect is not None:
            prospect.program_interest = program_value
            prospect.updated_at = student.updated_at

        projected = db.execute(
            select(StudentWorkState)
            .where(StudentWorkState.tenant_id == tenant_id, StudentWorkState.student_id == student.id)
            .limit(1)
        ).scalar_one_or_none()
        if projected is not None:
            projected.program = program_value
            projected.last_activity_at = student.latest_activity_at
            projected.updated_at = student.updated_at

        self._write_student_audit(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            student_id=student.id,
            action="student_program_updated",
            metadata={
                "previous_program_id": str(previous_program_id) if previous_program_id else None,
                "program_id": str(program.id),
                "program": program_value,
            },
        )
        db.commit()
        return {
            "id": student.external_student_id or str(student.id),
            "program": program_value,
            "degreeProgram": program_value,
            "stage": canonical_pipeline_status(student.current_stage),
        }

    def update_student(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        student_id: str,
        payload: Any,
        authorization: Any | None = None,
    ) -> Student360Record:
        student = self._resolve_student_row(db, tenant_id, student_id)
        if student is None:
            raise LookupError("Student not found.")

        now = datetime.now(timezone.utc)
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload or {})
        previous = {
            "email": student.email,
            "phone": student.phone,
            "city": student.city,
            "state": student.state,
            "preferred_name": student.preferred_name,
            "target_program_id": str(student.target_program_id) if student.target_program_id else None,
        }

        full_name = self._safe_optional_str(data.get("name"))
        if full_name:
            parts = full_name.split()
            student.first_name = parts[0]
            student.last_name = " ".join(parts[1:]) or student.last_name
        if "preferredName" in data:
            student.preferred_name = self._safe_optional_str(data.get("preferredName"))
        if "email" in data:
            student.email = self._safe_optional_str(data.get("email"))
        if "phone" in data:
            student.phone = self._safe_optional_str(data.get("phone"))
        if "city" in data:
            student.city = self._safe_optional_str(data.get("city"))
        if "state" in data:
            student.state = self._safe_optional_str(data.get("state"))

        program_value = self._safe_optional_str(data.get("degreeProgram") or data.get("program") or data.get("programInterest"))
        if program_value:
            program = db.execute(
                select(Program)
                .where(Program.tenant_id == tenant_id, Program.name == program_value)
                .order_by(Program.created_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            if program is None:
                program = Program(tenant_id=tenant_id, institution_id=student.target_institution_id, name=program_value, is_active=True)
                db.add(program)
                db.flush()
            student.target_program_id = program.id

        prospect = db.execute(
            select(Prospect)
            .where(Prospect.tenant_id == tenant_id, Prospect.student_id == student.id)
            .order_by(Prospect.updated_at.desc(), Prospect.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if prospect is not None:
            prospect.email = student.email or prospect.email
            prospect.phone = student.phone or prospect.phone
            if program_value:
                prospect.program_interest = program_value
            if "population" in data and self._safe_optional_str(data.get("population")):
                prospect.population = self._safe_optional_str(data.get("population")) or prospect.population
            if "source" in data and self._safe_optional_str(data.get("source")):
                prospect.source = self._safe_optional_str(data.get("source")) or prospect.source
            if any(key in data for key in ("smsOptIn", "textingOk", "textConsent")):
                prospect.consent_captured = bool(data.get("smsOptIn") or data.get("textingOk") or data.get("textConsent"))
            prospect.updated_at = now

        sms_opt_in = bool(data.get("smsOptIn") or data.get("textingOk") or data.get("textConsent"))
        if "phone" in data and student.phone:
            contact = db.execute(
                select(StudentContactMethod)
                .where(
                    StudentContactMethod.tenant_id == tenant_id,
                    StudentContactMethod.student_id == student.id,
                    StudentContactMethod.contact_type == "phone",
                    StudentContactMethod.is_primary.is_(True),
                )
                .limit(1)
            ).scalar_one_or_none()
            if contact is None:
                contact = StudentContactMethod(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    contact_type="phone",
                    value=student.phone,
                    is_primary=True,
                    allows_sms=sms_opt_in,
                    allows_email=False,
                    source="student_360_update",
                )
                db.add(contact)
            else:
                contact.value = student.phone
                contact.allows_sms = sms_opt_in
                contact.updated_at = now
        elif any(key in data for key in ("smsOptIn", "textingOk", "textConsent")):
            contact = db.execute(
                select(StudentContactMethod)
                .where(
                    StudentContactMethod.tenant_id == tenant_id,
                    StudentContactMethod.student_id == student.id,
                    StudentContactMethod.contact_type == "phone",
                    StudentContactMethod.is_primary.is_(True),
                )
                .limit(1)
            ).scalar_one_or_none()
            if contact is not None:
                contact.allows_sms = sms_opt_in
                contact.updated_at = now

        if any(key in data for key in ("addressLine1", "addressLine2", "city", "state", "postalCode")):
            address = db.execute(
                select(StudentAddress)
                .where(
                    StudentAddress.tenant_id == tenant_id,
                    StudentAddress.student_id == student.id,
                    StudentAddress.is_primary.is_(True),
                )
                .limit(1)
            ).scalar_one_or_none()
            if address is None:
                address = StudentAddress(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    address_type="mailing",
                    is_primary=True,
                    source="student_360_update",
                )
                db.add(address)
            address.line1 = self._safe_optional_str(data.get("addressLine1")) if "addressLine1" in data else address.line1
            address.line2 = self._safe_optional_str(data.get("addressLine2")) if "addressLine2" in data else address.line2
            address.city = student.city if "city" in data else address.city
            address.state = student.state if "state" in data else address.state
            address.postal_code = self._safe_optional_str(data.get("postalCode")) if "postalCode" in data else address.postal_code
            address.country = address.country or "US"
            address.updated_at = now

        if any(key in data for key in ("parentName", "parentRelationship", "parentEmail", "parentPhone")):
            parent_name = self._safe_optional_str(data.get("parentName"))
            relationship = self._safe_optional_str(data.get("parentRelationship")) or "Parent/guardian"
            relationship_row = db.execute(
                select(StudentRelationship)
                .where(StudentRelationship.tenant_id == tenant_id, StudentRelationship.student_id == student.id)
                .order_by(StudentRelationship.updated_at.desc(), StudentRelationship.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if relationship_row is None and parent_name:
                relationship_row = StudentRelationship(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    related_person_name=parent_name,
                    relationship_type=relationship,
                )
                db.add(relationship_row)
            if relationship_row is not None:
                if parent_name:
                    relationship_row.related_person_name = parent_name
                relationship_row.relationship_type = relationship
                relationship_row.email = self._safe_optional_str(data.get("parentEmail")) if "parentEmail" in data else relationship_row.email
                relationship_row.phone = self._safe_optional_str(data.get("parentPhone")) if "parentPhone" in data else relationship_row.phone
                relationship_row.updated_at = now

        if "notes" in data and self._safe_optional_str(data.get("notes")):
            db.add(
                StudentNote(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    transcript_id=None,
                    author_user_id=actor_user_id,
                    note_type="student_profile",
                    body=self._safe_optional_str(data.get("notes")) or "",
                    is_internal=True,
                    created_at=now,
                    updated_at=now,
                )
            )

        student.updated_at = now
        student.latest_activity_at = now

        self._write_student_audit(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            student_id=student.id,
            action="student_profile_updated",
            metadata={
                "previous": previous,
                "updatedFields": sorted(data.keys()),
            },
        )
        db.commit()
        return self.get_student(tenant_id=tenant_id, student_id=str(student.id), authorization=authorization)

    def record_next_action(self, db: Session, tenant_id: UUID, actor_user_id: UUID, student_id: str, payload: Any) -> dict[str, str | None]:
        action_type = (payload.actionType or "").strip().lower()
        if action_type not in {"contacted", "follow_up", "request_document", "route_handoff"}:
            raise ValueError("Invalid actionType.")
        student = self._resolve_student_row(db, tenant_id, student_id)
        if student is None:
            raise LookupError("Student not found.")

        now = datetime.now(timezone.utc)
        last_contacted_at = self._parse_client_datetime(payload.lastContactedAt) if payload.lastContactedAt else None
        next_follow_up_at = self._parse_client_datetime(payload.nextFollowUpAt) if payload.nextFollowUpAt else None
        occurred_at = last_contacted_at or now
        next_action = (payload.nextAction or "").strip() or None
        contact_outcome = (payload.contactOutcome or "").strip() or None
        owner_id = getattr(payload, "ownerId", None)
        last_activity = (payload.lastActivity or "").strip() or "Just now"

        existing_state = db.execute(
            select(StudentAgentState)
            .where(StudentAgentState.tenant_id == tenant_id, StudentAgentState.student_id == student.id)
            .limit(1)
        ).scalar_one_or_none()
        if existing_state is None:
            existing_state = StudentAgentState(tenant_id=tenant_id, student_id=student.id)
            db.add(existing_state)
            db.flush()
        state_json = dict(existing_state.state_json or {})
        state_json.update(
            {
                "actionType": action_type,
                "nextAction": next_action,
                "nextFollowUpAt": self._format_timestamp(next_follow_up_at) if next_follow_up_at else None,
                "lastContactedAt": self._format_timestamp(last_contacted_at) if last_contacted_at else state_json.get("lastContactedAt"),
                "contactOutcome": contact_outcome,
                "ownerId": owner_id,
                "lastActivity": last_activity,
            }
        )
        existing_state.state_json = state_json
        existing_state.updated_at = now
        owner_uuid = self._uuid_or_none(owner_id)
        owner = db.get(AppUser, owner_uuid) if owner_uuid else None
        if owner is not None and owner.tenant_id == tenant_id:
            student.advisor_user_id = owner.id

        if payload.note and payload.note.strip():
            db.add(
                StudentNote(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    transcript_id=None,
                    author_user_id=actor_user_id,
                    note_type=action_type,
                    body=payload.note.strip(),
                    is_internal=False,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
            )

        if next_action or next_follow_up_at:
            db.add(
                StudentTask(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    transcript_id=None,
                    task_type=f"counselor_{action_type}",
                    label=next_action or self._title_case(action_type),
                    status="open",
                    assigned_to_user_id=actor_user_id,
                    due_at=next_follow_up_at,
                    completed_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )

        student.latest_activity_at = occurred_at
        student.updated_at = now
        projected = db.execute(
            select(StudentWorkState)
            .where(StudentWorkState.tenant_id == tenant_id, StudentWorkState.student_id == student.id)
            .limit(1)
        ).scalar_one_or_none()
        if projected is not None:
            projected.last_activity_at = occurred_at
            if owner is not None:
                projected.owner_user_id = owner.id
                projected.owner_name = owner.display_name
            projected.updated_at = now
        self._write_student_audit(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            student_id=student.id,
            action="counselor_next_action_recorded",
            metadata={
                "actionType": action_type,
                "note": payload.note,
                "nextAction": next_action,
                "contactOutcome": contact_outcome,
                "ownerId": owner_id,
                "lastContactedAt": state_json.get("lastContactedAt"),
                "nextFollowUpAt": state_json.get("nextFollowUpAt"),
                "lastActivity": last_activity,
            },
        )
        if next_action is not None:
            self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_next_action_updated", metadata={"nextAction": next_action}, occurred_at=occurred_at)
        if next_follow_up_at is not None:
            self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_next_follow_up_updated", metadata={"nextFollowUpAt": state_json.get("nextFollowUpAt")}, occurred_at=occurred_at)
        if last_contacted_at is not None:
            self._write_student_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, student_id=student.id, action="student_contact_logged", metadata={"contactOutcome": contact_outcome, "lastContactedAt": state_json.get("lastContactedAt")}, occurred_at=occurred_at)
        db.commit()
        return {
            "id": student.external_student_id or str(student.id),
            "nextAction": next_action,
            "nextFollowUpAt": state_json.get("nextFollowUpAt"),
            "lastContactedAt": state_json.get("lastContactedAt"),
            "contactOutcome": contact_outcome,
            "lastActivity": last_activity,
        }

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

        state_by_student = self._load_counselor_state(
            session,
            tenant_id,
            [student.id for student, *_ in rows],
        )
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
            counselor_state = state_by_student.get(student.id, {})
            recruitment = self._recruitment_state(counselor_state)
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
                    degreeProgram=program_summary.name,
                    population=prospect.population if prospect else self._student_type(student.accepted_credits),
                    studentType=prospect.population if prospect else self._student_type(student.accepted_credits),
                    source=prospect.source if prospect else "transcript_first",
                    sourceCategory=prospect.source_category if prospect else "direct",
                    campaign=prospect.campaign if prospect else None,
                    termInterest=prospect.term_interest if prospect else None,
                    institutionGoal=institution_goal,
                    stage=canonical_pipeline_status(prospect.lifecycle_stage if prospect else student.current_stage),
                    risk=self._title_case(student.risk_level or "low"),
                    owner=owner_summary,
                    assignedOwner=owner_summary,
                    ownerId=owner_summary.id,
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
                    nextAction=counselor_state.get("nextAction") or next_best_action,
                    lastContactedAt=counselor_state.get("lastContactedAt"),
                    nextFollowUpAt=counselor_state.get("nextFollowUpAt"),
                    contactOutcome=counselor_state.get("contactOutcome"),
                    territory=recruitment.get("territory"),
                    sourceSchool=recruitment.get("sourceSchool"),
                    partnerSchool=recruitment.get("partnerSchool"),
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

    def _find_existing_student_for_create(
        self,
        session: Session,
        tenant_id: UUID,
        external_id: str | None,
        email: str | None,
        phone: str | None,
    ) -> Student | None:
        if external_id:
            student = self._resolve_student_row(session, tenant_id, external_id)
            if student is not None:
                return student
            identifier_student_id = session.execute(
                select(StudentIdentifier.student_id)
                .where(
                    StudentIdentifier.tenant_id == tenant_id,
                    StudentIdentifier.identifier_value == external_id,
                )
                .limit(1)
            ).scalar_one_or_none()
            if identifier_student_id is not None:
                return session.get(Student, identifier_student_id)
        predicates = []
        if email:
            predicates.append(func.lower(Student.email) == email.lower())
        if phone:
            predicates.append(Student.phone == phone)
        if not predicates:
            return None
        return session.execute(select(Student).where(Student.tenant_id == tenant_id, or_(*predicates)).limit(1)).scalar_one_or_none()

    def _ensure_student_identifier(self, session: Session, tenant_id: UUID, student_id: UUID, external_id: str, source: str) -> None:
        existing = session.execute(
            select(StudentIdentifier)
            .where(
                StudentIdentifier.tenant_id == tenant_id,
                StudentIdentifier.identifier_type == "external_source_id",
                StudentIdentifier.identifier_value == external_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                StudentIdentifier(
                    tenant_id=tenant_id,
                    student_id=student_id,
                    identifier_type="external_source_id",
                    identifier_value=external_id,
                    source=source,
                    is_verified=False,
                )
            )
        elif existing.student_id != student_id:
            existing.student_id = student_id

    def _ensure_student_source(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        student_id: UUID,
        source: str,
        source_category: str,
        payload: StudentCreateRequest,
        now: datetime,
    ) -> None:
        existing = session.execute(
            select(StudentSource)
            .where(
                StudentSource.tenant_id == tenant_id,
                StudentSource.student_id == student_id,
                StudentSource.source_name == source,
            )
            .limit(1)
        ).scalar_one_or_none()
        raw_source = payload.model_dump(mode="json", exclude_none=True)
        if existing is None:
            has_source = session.execute(
                select(StudentSource.id)
                .where(StudentSource.tenant_id == tenant_id, StudentSource.student_id == student_id)
                .limit(1)
            ).scalar_one_or_none()
            session.add(
                StudentSource(
                    tenant_id=tenant_id,
                    student_id=student_id,
                    source_name=source,
                    source_type=source,
                    source_detail=source_category,
                    source_batch_id=None,
                    primary_source=has_source is None,
                    raw_source_json=raw_source,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
        else:
            existing.source_detail = source_category
            existing.raw_source_json = raw_source
            existing.last_seen_at = now

    def _upsert_student_prospect(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        student: Student,
        payload: StudentCreateRequest,
        email: str,
        phone: str | None,
        population: str,
        source: str,
        source_category: str,
        stage: str,
        now: datetime,
    ) -> None:
        prospect = session.execute(
            select(Prospect)
            .where(
                Prospect.tenant_id == tenant_id,
                or_(
                    Prospect.student_id == student.id,
                    func.lower(Prospect.email) == email.lower(),
                ),
            )
            .order_by(Prospect.updated_at.desc(), Prospect.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if prospect is None:
            prospect = Prospect(
                tenant_id=tenant_id,
                first_name=student.first_name or "Student",
                last_name=student.last_name or "",
                email=email,
                population=population,
                lifecycle_stage=stage,
                status="new",
                owner_user_id=student.advisor_user_id or actor_user_id,
                source=source,
                source_category=source_category,
                consent_captured=False,
                created_at=now,
                updated_at=now,
            )
            session.add(prospect)
            session.flush()
        prospect.student_id = student.id
        prospect.first_name = student.first_name or prospect.first_name
        prospect.last_name = student.last_name or prospect.last_name
        prospect.email = email
        prospect.phone = phone
        prospect.population = population
        prospect.program_interest = self._safe_optional_str(payload.programInterest or payload.degreeProgram or payload.program)
        prospect.term_interest = self._safe_optional_str(payload.termInterest)
        prospect.source = source
        prospect.source_category = source_category
        prospect.campaign = self._safe_optional_str(payload.campaign)
        prospect.lifecycle_stage = stage
        prospect.status = "new" if prospect.status in {None, ""} else prospect.status
        prospect.updated_at = now

        source_ref = session.execute(
            select(ProspectSourceReference)
            .where(
                ProspectSourceReference.tenant_id == tenant_id,
                ProspectSourceReference.prospect_id == prospect.id,
                ProspectSourceReference.external_reference_id == student.external_student_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if student.external_student_id and source_ref is None:
            session.add(
                ProspectSourceReference(
                    tenant_id=tenant_id,
                    prospect_id=prospect.id,
                    source=source,
                    source_category=source_category,
                    campaign=prospect.campaign,
                    external_reference_id=student.external_student_id,
                    metadata_json={"createdByUserId": str(actor_user_id)},
                    captured_at=now,
                )
            )

    def _ensure_student_institution(self, session: Session, tenant_id: UUID, name: str | None) -> Institution | None:
        if not name:
            return None
        existing = session.execute(
            select(Institution)
            .where(Institution.tenant_id == tenant_id, func.lower(Institution.name) == name.lower())
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        institution = Institution(tenant_id=tenant_id, name=name, state=name if len(name) == 2 else None, country="US")
        session.add(institution)
        session.flush()
        return institution

    def _ensure_student_program(self, session: Session, tenant_id: UUID, name: str | None, institution: Institution | None) -> Program | None:
        if not name:
            return None
        existing = session.execute(
            select(Program)
            .where(Program.tenant_id == tenant_id, func.lower(Program.name) == name.lower())
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        program = Program(
            tenant_id=tenant_id,
            institution_id=institution.id if institution else None,
            name=name,
            program_code=None,
            degree_type=None,
            is_active=True,
        )
        session.add(program)
        session.flush()
        return program

    def _student_name_parts(self, payload: StudentCreateRequest) -> tuple[str | None, str | None]:
        first_name = self._safe_optional_str(payload.firstName)
        last_name = self._safe_optional_str(payload.lastName)
        if (first_name or last_name) or not payload.name:
            return first_name, last_name
        parts = payload.name.strip().split()
        if len(parts) == 1:
            return parts[0], None
        return " ".join(parts[:-1]), parts[-1]

    def _normalize_optional_email(self, value: str | None) -> str | None:
        email = self._safe_optional_str(value)
        if email is None:
            return None
        normalized = email.lower()
        if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("A valid email is required.")
        return normalized

    def _normalize_population(self, value: str | None) -> str:
        normalized = self._normalize_key(value or "prospect")
        return normalized or "prospect"

    def _normalize_key(self, value: str | None) -> str:
        return (value or "").strip().lower().replace("-", "_").replace(" ", "_")

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

        interactions = session.execute(
            select(StudentInteraction)
            .where(StudentInteraction.tenant_id == tenant_id, StudentInteraction.student_id == student.id)
            .order_by(StudentInteraction.occurred_at.desc(), StudentInteraction.created_at.desc())
        ).scalars().all()
        for interaction in interactions:
            events.append(
                self._timeline_event(
                    event_id=interaction.id,
                    event_type="interaction",
                    title=interaction.title,
                    description=interaction.description or interaction.note,
                    occurred_at=interaction.occurred_at,
                    actor=interaction.actor_name,
                    source=interaction.source,
                    status=self._title_case(interaction.outcome),
                    entity_type="student_interaction",
                    entity_id=interaction.id,
                )
            )

        notes = session.execute(
            select(StudentNote).where(StudentNote.tenant_id == tenant_id, StudentNote.student_id == student.id).order_by(StudentNote.created_at.desc())
        ).scalars().all()
        for note in notes:
            is_counselor_note = note.note_type in {"contacted", "follow_up", "request_document", "route_handoff"}
            events.append(
                self._timeline_event(
                    event_id=note.id,
                    event_type="interaction",
                    title="Contact logged" if is_counselor_note else f"{self._title_case(note.note_type)} note added",
                    description=note.body if not note.is_internal else "Internal note added.",
                    occurred_at=note.created_at,
                    actor=self._actor_for_user(actors, note.author_user_id),
                    source="counselor_workbench" if is_counselor_note else "interaction",
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
        counselor_state = self._load_counselor_state(session, tenant_id, [student.id]).get(student.id, {})
        recruitment = self._recruitment_state(counselor_state)
        interactions = [
            self._serialize_interaction(interaction).model_dump(mode="json")
            for interaction in session.execute(
                select(StudentInteraction)
                .where(StudentInteraction.tenant_id == tenant_id, StudentInteraction.student_id == student.id)
                .order_by(StudentInteraction.occurred_at.desc(), StudentInteraction.created_at.desc())
            ).scalars().all()
        ]
        handoffs = self._serialize_student_handoffs(session, tenant_id, student.id)
        post_admit_milestones = self._serialize_post_admit_milestones(session, tenant_id, student.id)
        readiness = self._load_readiness_summary(session, tenant_id, student.id) or self._readiness_summary_from_stage(student.current_stage, student.risk_level)
        program_summary = StudentProgramSummary(id=(str(program.id) if program else None), name=(program.name if program else prospect.program_interest if prospect else "Transcript intake"))
        student_type = prospect.population if prospect else self._student_type(student.accepted_credits)
        application = self._build_application_summary(
            student=student,
            prospect=prospect,
            student_type=student_type,
            counselor_state=counselor_state,
        )
        scholarship_offers = self._build_scholarship_offers(counselor_state)
        scholarship_options = self._build_scholarship_options(
            state=counselor_state,
            student=student,
            transcripts=transcripts,
            prospect=prospect,
            program_name=program_summary.name,
        )
        financial_aid = self._build_financial_aid_summary(
            state=counselor_state,
            milestones=post_admit_milestones,
            scholarship_offers=scholarship_offers,
        )
        primary_phone_contact = db.execute(
            select(StudentContactMethod)
            .where(
                StudentContactMethod.tenant_id == tenant_id,
                StudentContactMethod.student_id == student.id,
                StudentContactMethod.contact_type == "phone",
                StudentContactMethod.is_primary.is_(True),
            )
            .order_by(StudentContactMethod.updated_at.desc(), StudentContactMethod.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        primary_address = db.execute(
            select(StudentAddress)
            .where(StudentAddress.tenant_id == tenant_id, StudentAddress.student_id == student.id, StudentAddress.is_primary.is_(True))
            .order_by(StudentAddress.updated_at.desc(), StudentAddress.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        parent_guardian = db.execute(
            select(StudentRelationship)
            .where(StudentRelationship.tenant_id == tenant_id, StudentRelationship.student_id == student.id)
            .order_by(StudentRelationship.updated_at.desc(), StudentRelationship.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        latest_profile_note = db.execute(
            select(StudentNote)
            .where(StudentNote.tenant_id == tenant_id, StudentNote.student_id == student.id, StudentNote.note_type == "student_profile")
            .order_by(StudentNote.updated_at.desc(), StudentNote.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        sms_opt_in = bool(primary_phone_contact.allows_sms) if primary_phone_contact is not None else False
        display_phone = student.phone or (primary_phone_contact.value if primary_phone_contact is not None else None)
        return Student360Record(
            id=str(student.id),
            studentId=student.external_student_id or str(student.id),
            name=self._join_name(student.first_name, student.last_name, fallback="Unknown Student"),
            preferredName=student.preferred_name or student.first_name or "Student",
            email=student.email,
            phone=display_phone,
            smsOptIn=sms_opt_in,
            textingOk=sms_opt_in,
            textConsent=sms_opt_in,
            addressLine1=primary_address.line1 if primary_address is not None else None,
            addressLine2=primary_address.line2 if primary_address is not None else None,
            state=primary_address.state if primary_address is not None else student.state,
            postalCode=primary_address.postal_code if primary_address is not None else None,
            parentName=parent_guardian.related_person_name if parent_guardian is not None else None,
            parentRelationship=parent_guardian.relationship_type if parent_guardian is not None else None,
            parentEmail=parent_guardian.email if parent_guardian is not None else None,
            parentPhone=parent_guardian.phone if parent_guardian is not None else None,
            notes=latest_profile_note.body if latest_profile_note is not None else None,
            program=program_summary,
            degreeProgram=program_summary.name,
            population=student_type,
            studentType=student_type,
            source=prospect.source if prospect else "transcript_first",
            sourceCategory=prospect.source_category if prospect else "direct",
            campaign=prospect.campaign if prospect else None,
            termInterest=prospect.term_interest if prospect else None,
            institutionGoal=institution_goal,
            stage=canonical_pipeline_status(prospect.lifecycle_stage if prospect else student.current_stage),
            risk=self._title_case(student.risk_level or "low"),
            fitScore=self._estimate_fit_score(student.latest_cumulative_gpa, transcripts),
            depositLikelihood=self._estimate_deposit_likelihood(student.risk_level, student.latest_cumulative_gpa, transcripts),
            summary=student.summary or self._default_summary(transcripts, student.risk_level),
            gpa=self._to_float(student.latest_cumulative_gpa),
            creditsAccepted=self._to_float(student.accepted_credits, 0),
            transcriptsCount=len(transcripts),
            owner=owner_summary,
            assignedOwner=owner_summary,
            ownerId=owner_summary.id,
            advisor=owner_summary.name,
            readiness=readiness,
            tags=self._build_tags(program_summary.name, student.risk_level, student.current_stage),
            nextBestAction=recommendation.nextBestAction,
            nextAction=counselor_state.get("nextAction") or recommendation.nextBestAction,
            lastContactedAt=counselor_state.get("lastContactedAt"),
            nextFollowUpAt=counselor_state.get("nextFollowUpAt"),
            contactOutcome=counselor_state.get("contactOutcome"),
            interactions=interactions,
            handoffs=handoffs,
            postAdmitMilestones=post_admit_milestones,
            territory=recruitment.get("territory"),
            sourceSchool=recruitment.get("sourceSchool"),
            partnerSchool=recruitment.get("partnerSchool"),
            city=self._format_location(student.city, student.state, student.country),
            lastActivity=self._format_timestamp(student.latest_activity_at or student.updated_at),
            checklist=self._build_checklist(transcripts, student.risk_level),
            transcripts=transcripts,
            termGpa=self._build_term_gpa(transcripts),
            recommendation=recommendation,
            application=application,
            financialAid=financial_aid,
            scholarshipOptions=scholarship_options,
            scholarshipOffers=scholarship_offers,
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
            application=StudentApplicationSummary(
                id=student_id,
                status=stage,
                type="Transfer application" if self._derive_credits_from_bundles(bundles) > 0 else "First-year application",
                studentType="Transfer" if self._derive_credits_from_bundles(bundles) > 0 else "First Year",
                nextStep=recommendation.nextBestAction,
            ),
            financialAid=StudentFinancialAidSummary(usingFinancialAid=None, fafsa=StudentFafsaSummary()),
            scholarshipOptions=[],
            scholarshipOffers=[],
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
            external_document = self._external_document_from_parse_run(bundle.parse_run)
            raw_courses = payload.get("courses") or []
            raw_document = dict(payload) if payload else {}
            if external_document:
                raw_document.update({
                    "crtfyDocumentId": external_document.get("document_id"),
                    "documentStorageProvider": external_document.get("provider") or "crtfy_documents",
                    "documentStorageDepartment": external_document.get("department") or "General",
                    "documentContentUrl": external_document.get("content_url"),
                    "content_url": external_document.get("content_url"),
                    "documentStorage": {
                        "provider": external_document.get("provider") or "crtfy_documents",
                        "documentId": external_document.get("document_id"),
                        "tenantId": external_document.get("tenant_id"),
                        "contentUrl": external_document.get("content_url"),
                        "department": external_document.get("department") or "General",
                    },
                })
            records.append(
                StudentTranscriptRecord(
                    id=str(bundle.transcript.id),
                    source=bundle.upload.original_filename,
                    documentId=external_document.get("document_id") or str(bundle.upload.id),
                    documentUploadId=str(bundle.upload.id),
                    crtfyDocumentId=external_document.get("document_id"),
                    documentStorageProvider=external_document.get("provider") or ("crtfy_documents" if external_document else None),
                    documentStorageDepartment=external_document.get("department") or ("General" if external_document else None),
                    documentContentUrl=external_document.get("content_url"),
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
                    rawDocument=raw_document or None,
                )
            )
        return records

    def _external_document_from_parse_run(self, parse_run: TranscriptParseRun | None) -> dict[str, Any]:
        if parse_run is None:
            return {}
        request_json = parse_run.request_json or {}
        external_document = request_json.get("external_document") or {}
        if not isinstance(external_document, dict):
            return {}
        return external_document

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

    def _serialize_interaction(self, interaction: StudentInteraction) -> StudentInteractionRecord:
        return StudentInteractionRecord(
            id=str(interaction.id),
            studentId=str(interaction.student_id),
            type=interaction.type,
            outcome=interaction.outcome,
            title=interaction.title,
            note=interaction.note,
            description=interaction.description,
            nextAction=interaction.next_action,
            nextFollowUpAt=self._format_timestamp(interaction.next_follow_up_at) if interaction.next_follow_up_at else None,
            occurredAt=self._format_timestamp(interaction.occurred_at),
            actor=interaction.actor_name,
            source=interaction.source,
        )

    def _serialize_student_handoffs(self, session: Session, tenant_id: UUID, student_id: UUID) -> list[dict[str, Any]]:
        tasks = session.execute(
            select(StudentTask)
            .where(
                StudentTask.tenant_id == tenant_id,
                StudentTask.student_id == student_id,
                StudentTask.task_type.ilike("%handoff%"),
            )
            .order_by(StudentTask.updated_at.desc())
        ).scalars().all()
        actors = self._load_actor_map(session, tenant_id)
        metadata_by_id = self._handoff_metadata(session, tenant_id, student_id)
        for task in tasks:
            task._metadata_json = metadata_by_id.get(str(task.id), {})
        return [self._serialize_handoff_task(task, actors) for task in tasks]

    def _serialize_handoff_task(self, task: StudentTask, actors: dict[UUID, AppUser] | None = None) -> dict[str, Any]:
        owner = actors.get(task.assigned_to_user_id) if actors and task.assigned_to_user_id else None
        metadata = {}
        if hasattr(task, "_metadata_json"):
            metadata = getattr(task, "_metadata_json") or {}
        return {
            "id": str(task.id),
            "studentId": str(task.student_id),
            "targetTeam": metadata.get("targetTeam") or metadata.get("office") or self._title_case(task.task_type.replace("handoff", "").strip("_ ")) or "Student Services",
            "owner": metadata.get("owner") or (owner.display_name if owner else "Unassigned"),
            "ownerId": metadata.get("ownerId") or (str(task.assigned_to_user_id) if task.assigned_to_user_id else None),
            "priority": metadata.get("priority") or "Normal",
            "status": self._title_case(task.status),
            "dueAt": self._format_timestamp(task.due_at) if task.due_at else None,
            "blocker": metadata.get("blocker"),
            "summary": task.label,
            "createdAt": self._format_timestamp(task.created_at),
            "createdBy": metadata.get("createdBy"),
            "updatedAt": self._format_timestamp(task.updated_at),
        }

    def _handoff_metadata(self, session: Session, tenant_id: UUID, student_id: UUID) -> dict[str, dict[str, Any]]:
        state = session.execute(
            select(StudentAgentState)
            .where(StudentAgentState.tenant_id == tenant_id, StudentAgentState.student_id == student_id)
            .limit(1)
        ).scalar_one_or_none()
        if state is None:
            return {}
        return dict((state.state_json or {}).get("handoffMetadata") or {})

    def _merge_handoff_metadata(self, session: Session, tenant_id: UUID, student_id: UUID, handoff_id: str, metadata: dict[str, Any]) -> None:
        state = session.execute(
            select(StudentAgentState)
            .where(StudentAgentState.tenant_id == tenant_id, StudentAgentState.student_id == student_id)
            .limit(1)
        ).scalar_one_or_none()
        if state is None:
            state = StudentAgentState(tenant_id=tenant_id, student_id=student_id, state_json={})
            session.add(state)
            session.flush()
        state_json = dict(state.state_json or {})
        handoff_metadata = dict(state_json.get("handoffMetadata") or {})
        current = dict(handoff_metadata.get(handoff_id) or {})
        current.update({key: value for key, value in metadata.items() if value is not None})
        handoff_metadata[handoff_id] = current
        state_json["handoffMetadata"] = handoff_metadata
        state.state_json = state_json
        state.updated_at = datetime.now(timezone.utc)

    def _serialize_post_admit_milestones(self, session: Session, tenant_id: UUID, student_id: UUID) -> list[dict[str, Any]]:
        existing = session.execute(
            select(StudentEnrollmentMilestone)
            .where(StudentEnrollmentMilestone.tenant_id == tenant_id, StudentEnrollmentMilestone.student_id == student_id)
            .order_by(StudentEnrollmentMilestone.updated_at.desc())
        ).scalars().all()
        by_code = {row.milestone_code: row for row in existing}
        records: list[dict[str, Any]] = []
        for code, label, owner in self._post_admit_milestone_defs():
            row = by_code.get(code)
            metadata = dict(row.metadata_json or {}) if row else {}
            records.append(
                {
                    "id": code,
                    "label": row.milestone_label if row else label,
                    "status": self._frontend_milestone_status(row.status if row else "not_started"),
                    "owner": metadata.get("owner") or owner,
                    "dueAt": metadata.get("dueAt"),
                    "blocker": metadata.get("blocker"),
                    "updatedAt": self._format_timestamp(row.updated_at) if row else None,
                    "integration": metadata.get("integration") or self._milestone_integration_placeholder(code),
                }
            )
        return records

    def _milestone_record(self, milestone: StudentEnrollmentMilestone) -> dict[str, Any]:
        metadata = dict(milestone.metadata_json or {})
        return {
            "id": milestone.milestone_code,
            "label": milestone.milestone_label,
            "status": self._frontend_milestone_status(milestone.status),
            "owner": metadata.get("owner"),
            "dueAt": metadata.get("dueAt"),
            "blocker": metadata.get("blocker"),
            "updatedAt": self._format_timestamp(milestone.updated_at),
            "integration": metadata.get("integration") or self._milestone_integration_placeholder(milestone.milestone_code),
        }

    def _post_admit_milestone_defs(self) -> list[tuple[str, str, str]]:
        return [
            ("financial_aid_package", "Financial aid package", "Financial Aid"),
            ("scholarship_status", "Scholarship status", "Financial Aid"),
            ("deposit_commitment", "Deposit commitment", "Admissions"),
            ("housing_application", "Housing application", "Housing"),
            ("orientation", "Orientation", "Orientation"),
            ("advising_appointment", "Advising appointment", "Advising"),
            ("registration_status", "Registration status", "Registrar"),
            ("bursar_account", "Bursar account", "Bursar"),
            ("international_docs", "International documents", "International Office"),
            ("veteran_benefits", "Veteran benefits", "Veteran Services"),
            ("accessibility_handoff", "Accessibility handoff", "Accessibility Services"),
        ]

    def _frontend_milestone_status(self, value: str | None) -> str:
        normalized = (value or "not_started").lower().replace("-", "_").replace(" ", "_")
        mapping = {
            "not_started": "Not started",
            "open": "Not started",
            "in_progress": "In progress",
            "blocked": "Blocked",
            "complete": "Complete",
            "completed": "Complete",
            "waived": "Waived",
        }
        return mapping.get(normalized, self._title_case(value))

    def _milestone_integration_placeholder(self, code: str) -> dict[str, Any] | None:
        placeholders = {
            "registration_status": {"system": "SIS", "status": "not_connected"},
            "financial_aid_package": {"system": "Financial Aid", "status": "not_connected"},
            "housing_application": {"system": "Housing", "status": "not_connected"},
            "orientation": {"system": "Orientation", "status": "not_connected"},
            "bursar_account": {"system": "Bursar", "status": "not_connected"},
        }
        return placeholders.get(code)

    def _build_application_summary(
        self,
        *,
        student: Student,
        prospect: Prospect | None,
        student_type: str | None,
        counselor_state: dict[str, Any],
    ) -> StudentApplicationSummary:
        raw = self._state_dict(counselor_state, "application", "applicationSummary")
        status = raw.get("status") or canonical_pipeline_status(prospect.lifecycle_stage if prospect else student.current_stage)
        submitted_at = raw.get("submittedAt") or raw.get("submitted_at")
        if submitted_at is None and prospect and self._is_submitted_application_status(prospect.status, prospect.lifecycle_stage):
            submitted_at = prospect.updated_at
        return StudentApplicationSummary(
            id=self._safe_optional_str(raw.get("id") or student.external_student_id or str(student.id)),
            status=self._safe_optional_str(status),
            type=self._safe_optional_str(raw.get("type") or self._application_type_label(student_type)),
            entryTerm=self._safe_optional_str(raw.get("entryTerm") or raw.get("entry_term") or (prospect.term_interest if prospect else None)),
            campus=self._safe_optional_str(raw.get("campus")),
            delivery=self._safe_optional_str(raw.get("delivery")),
            startedAt=self._iso_state_datetime(raw.get("startedAt") or raw.get("started_at") or (prospect.created_at if prospect else student.created_at)),
            submittedAt=self._iso_state_datetime(submitted_at),
            residency=self._safe_optional_str(raw.get("residency")),
            studentType=self._safe_optional_str(raw.get("studentType") or raw.get("student_type") or self._title_case(student_type)),
            nextStep=self._safe_optional_str(raw.get("nextStep") or raw.get("next_step") or counselor_state.get("nextAction")),
        )

    def _build_financial_aid_summary(
        self,
        *,
        state: dict[str, Any],
        milestones: list[dict[str, Any]],
        scholarship_offers: list[StudentScholarshipOffer],
    ) -> StudentFinancialAidSummary:
        raw = self._state_dict(state, "financialAid", "financial_aid")
        fafsa_raw = self._state_dict(raw, "fafsa")
        financial_milestone = self._milestone_by_id(milestones, "financial_aid_package")
        scholarship_milestone = self._milestone_by_id(milestones, "scholarship_status")
        scholarship_amount = self._coerce_amount(raw.get("scholarshipAmount") or raw.get("scholarship_amount"))
        if scholarship_amount is None:
            scholarship_amount = self._sum_offer_amounts(scholarship_offers)
        using_aid = raw.get("usingFinancialAid", raw.get("using_financial_aid"))
        if using_aid is None:
            using_aid = bool(fafsa_raw or raw.get("estimatedAid") or raw.get("estimated_aid") or scholarship_amount)
        return StudentFinancialAidSummary(
            usingFinancialAid=bool(using_aid),
            status=self._safe_optional_str(raw.get("status") or (financial_milestone or {}).get("status")),
            fafsa=StudentFafsaSummary(
                status=self._safe_optional_str(fafsa_raw.get("status")),
                receivedAt=self._iso_state_datetime(fafsa_raw.get("receivedAt") or fafsa_raw.get("received_at")),
                aidYear=self._safe_optional_str(fafsa_raw.get("aidYear") or fafsa_raw.get("aid_year")),
                sai=self._safe_optional_str(fafsa_raw.get("sai")),
                dependencyStatus=self._safe_optional_str(fafsa_raw.get("dependencyStatus") or fafsa_raw.get("dependency_status")),
                verificationStatus=self._safe_optional_str(fafsa_raw.get("verificationStatus") or fafsa_raw.get("verification_status")),
            ),
            packageStatus=self._safe_optional_str(raw.get("packageStatus") or raw.get("package_status") or (financial_milestone or {}).get("status")),
            estimatedAid=self._coerce_amount(raw.get("estimatedAid") or raw.get("estimated_aid")),
            scholarshipStatus=self._safe_optional_str(raw.get("scholarshipStatus") or raw.get("scholarship_status") or (scholarship_milestone or {}).get("status")),
            scholarshipAmount=scholarship_amount,
            nextStep=self._safe_optional_str(raw.get("nextStep") or raw.get("next_step")),
        )

    def _build_scholarship_options(
        self,
        *,
        state: dict[str, Any],
        student: Student,
        transcripts: list[StudentTranscriptRecord],
        prospect: Prospect | None,
        program_name: str,
    ) -> list[StudentScholarshipOption]:
        raw_options = self._state_list(state, "scholarshipOptions", "scholarship_options")
        options = [self._scholarship_option_from_raw(item, index) for index, item in enumerate(raw_options)]
        options = [item for item in options if item is not None]
        if options:
            return options
        gpa = self._to_float(student.latest_cumulative_gpa)
        if gpa < 3.5:
            return []
        evidence = [f"Transcript GPA is {gpa:.2f}."]
        if program_name and program_name != "Transcript intake":
            evidence.append(f"Program interest is {program_name}.")
        elif prospect and prospect.program_interest:
            evidence.append(f"Program interest is {prospect.program_interest}.")
        elif transcripts:
            evidence.append("Transcript evidence is available for review.")
        return [
            StudentScholarshipOption(
                id="academic-merit",
                name="Academic Merit Scholarship",
                amount=None,
                owner="Admissions",
                description="For applicants with strong academic performance.",
                action="Generate merit estimate",
                matchScore=min(95, max(80, int(round(gpa * 24)))),
                status="Strong match",
                evidence=evidence,
                missing=[],
            )
        ]

    def _build_scholarship_offers(self, state: dict[str, Any]) -> list[StudentScholarshipOffer]:
        raw_offers = self._state_list(state, "scholarshipOffers", "scholarship_offers")
        offers = [self._scholarship_offer_from_raw(item, index) for index, item in enumerate(raw_offers)]
        return [item for item in offers if item is not None]

    def _scholarship_option_from_raw(self, item: Any, index: int) -> StudentScholarshipOption | None:
        if not isinstance(item, dict):
            return None
        name = self._safe_optional_str(item.get("name"))
        if not name:
            return None
        return StudentScholarshipOption(
            id=self._safe_optional_str(item.get("id")) or f"scholarship-option-{index + 1}",
            name=name,
            amount=self._coerce_amount(item.get("amount")),
            owner=self._safe_optional_str(item.get("owner")),
            description=self._safe_optional_str(item.get("description")),
            action=self._safe_optional_str(item.get("action")),
            matchScore=self._coerce_int(item.get("matchScore") or item.get("match_score")),
            status=self._safe_optional_str(item.get("status")),
            evidence=self._string_list(item.get("evidence")),
            missing=self._string_list(item.get("missing")),
        )

    def _scholarship_offer_from_raw(self, item: Any, index: int) -> StudentScholarshipOffer | None:
        if not isinstance(item, dict):
            return None
        name = self._safe_optional_str(item.get("name"))
        if not name:
            return None
        return StudentScholarshipOffer(
            id=self._safe_optional_str(item.get("id")) or f"scholarship-offer-{index + 1}",
            name=name,
            sourceType=self._scholarship_source_type(item.get("sourceType") or item.get("source_type")),
            provider=self._safe_optional_str(item.get("provider")),
            amount=self._coerce_amount(item.get("amount")),
            status=self._safe_optional_str(item.get("status")),
            offeredAt=self._iso_state_datetime(item.get("offeredAt") or item.get("offered_at")),
            renewable=self._coerce_bool(item.get("renewable")),
            requirements=self._safe_optional_str(item.get("requirements")),
            notes=self._safe_optional_str(item.get("notes")),
        )

    def _state_dict(self, state: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            value = state.get(key)
            if isinstance(value, dict):
                return dict(value)
        return {}

    def _state_list(self, state: dict[str, Any], *keys: str) -> list[Any]:
        for key in keys:
            value = state.get(key)
            if isinstance(value, list):
                return value
        return []

    def _milestone_by_id(self, milestones: list[dict[str, Any]], milestone_id: str) -> dict[str, Any] | None:
        return next((item for item in milestones if item.get("id") == milestone_id), None)

    def _sum_offer_amounts(self, offers: list[StudentScholarshipOffer]) -> float | int | None:
        amounts = [offer.amount for offer in offers if offer.amount is not None and (offer.status or "").lower() not in {"declined", "rejected"}]
        if not amounts:
            return None
        total = sum(float(amount) for amount in amounts)
        return int(total) if total.is_integer() else round(total, 2)

    def _scholarship_source_type(self, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "external":
            return "External"
        return "Institutional"

    def _coerce_amount(self, value: Any) -> float | int | None:
        if value is None or value == "":
            return None
        try:
            numeric = float(str(value).replace("$", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return None
        return int(numeric) if numeric.is_integer() else round(numeric, 2)

    def _coerce_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None

    def _coerce_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
        return None

    def _safe_optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _iso_state_datetime(self, value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return self._safe_optional_str(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _is_submitted_application_status(self, status: str | None, lifecycle_stage: str | None) -> bool:
        values = f"{status or ''} {lifecycle_stage or ''}".lower()
        return any(token in values for token in ("submitted", "complete", "admitted", "deposited", "registered"))

    def _application_type_label(self, student_type: str | None) -> str:
        normalized = self._title_case(student_type)
        return f"{normalized} application" if normalized else "Application"

    def _recruitment_state(self, state: dict[str, Any]) -> dict[str, Any]:
        recruitment = dict(state.get("recruitment") or {})
        return {
            "territory": recruitment.get("territory") or state.get("territory"),
            "sourceSchool": recruitment.get("sourceSchool") or state.get("sourceSchool"),
            "partnerSchool": recruitment.get("partnerSchool") or state.get("partnerSchool"),
        }

    def _update_student_counselor_state(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        student: Student,
        occurred_at: datetime,
        updated_at: datetime,
        state_updates: dict[str, str | None],
    ) -> None:
        state = session.execute(
            select(StudentAgentState)
            .where(StudentAgentState.tenant_id == tenant_id, StudentAgentState.student_id == student.id)
            .limit(1)
        ).scalar_one_or_none()
        if state is None:
            state = StudentAgentState(tenant_id=tenant_id, student_id=student.id)
            session.add(state)
            session.flush()
        state_json = dict(state.state_json or {})
        for key, value in state_updates.items():
            if value is not None:
                state_json[key] = value
        state.state_json = state_json
        state.updated_at = updated_at

        student.latest_activity_at = occurred_at
        student.updated_at = updated_at

        projected = session.execute(
            select(StudentWorkState)
            .where(StudentWorkState.tenant_id == tenant_id, StudentWorkState.student_id == student.id)
            .limit(1)
        ).scalar_one_or_none()
        if projected is not None:
            projected.last_activity_at = occurred_at
            projected.updated_at = updated_at

    def _actor_name_for_user(self, session: Session, actor_user_id: UUID | None) -> str | None:
        if actor_user_id is None:
            return None
        user = session.get(AppUser, actor_user_id)
        return user.display_name if user else None

    def _load_counselor_state(self, session: Session, tenant_id: UUID, student_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
        if not student_ids:
            return {}
        rows = session.execute(
            select(StudentAgentState).where(
                StudentAgentState.tenant_id == tenant_id,
                StudentAgentState.student_id.in_(student_ids),
            )
        ).scalars().all()
        return {row.student_id: dict(row.state_json or {}) for row in rows}

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
        actor: StudentTimelineActor | str | None,
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
        return dict(course)

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

    def _parse_client_datetime(self, value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Datetime values must be valid ISO 8601 strings.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _uuid_or_none(self, value: str | UUID | None) -> UUID | None:
        if isinstance(value, UUID):
            return value
        if not value:
            return None
        try:
            return UUID(str(value))
        except ValueError:
            return None

    def _write_student_audit(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        student_id: UUID,
        action: str,
        metadata: dict[str, Any],
        occurred_at: datetime | None = None,
    ) -> None:
        session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                entity_type="student",
                entity_id=student_id,
                category="CounselorWorkbench",
                action=action,
                success=True,
                error_message=None,
                payload_json={
                    "tenantId": str(tenant_id),
                    "studentId": str(student_id),
                    "student_id": str(student_id),
                    "actorUserId": str(actor_user_id),
                    "metadata": metadata,
                    **metadata,
                },
                correlation_id=None,
                source="counselor_workbench",
                occurred_at=occurred_at or datetime.now(timezone.utc),
            )
        )

    def _format_clock(self, value: datetime | None) -> str:
        if not value:
            return "Now"
        return value.astimezone(timezone.utc).strftime("%I:%M %p").lstrip("0")
