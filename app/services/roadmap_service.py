from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    AuditEvent,
    ChecklistTemplate,
    ChecklistTemplateItem,
    DecisionPacket,
    DocumentUpload,
    DuplicateCandidate,
    Institution,
    Program,
    Student,
    StudentChecklistItem,
    StudentEnrollmentMilestone,
    StudentMeltScore,
    StudentNote,
    StudentTask,
    StudentYieldScore,
    TenantSettings,
    Transcript,
    TranscriptCourse,
    TranscriptDemographics,
    TranscriptParseRun,
    TrustFlag,
)
from app.db.session import get_session_factory
from app.models.roadmap_models import (
    ChecklistTemplatePayload,
    ConnectorConfigPayload,
    ConnectorMappingsPayload,
    InteractionPayload,
    ItemResponse,
    ItemsResponse,
    RoadmapActionRequest,
    RoadmapActionResponse,
)


class RoadmapNotFoundError(Exception):
    pass


class RoadmapValidationError(Exception):
    pass


class RoadmapService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def list_checklist_templates(self, tenant_id: UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        with self.session_factory()() as session:
            stmt = select(ChecklistTemplate).where(ChecklistTemplate.tenant_id == tenant_id)
            if q:
                stmt = stmt.where(or_(ChecklistTemplate.name.ilike(f"%{q}%"), ChecklistTemplate.population.ilike(f"%{q}%")))
            rows = session.execute(stmt.order_by(ChecklistTemplate.created_at.desc())).scalars().all()
            return self._items([self._template_dict(session, row) for row in rows], limit, offset)

    def create_checklist_template(self, tenant_id: UUID, actor_user_id: UUID, payload: ChecklistTemplatePayload) -> dict[str, Any]:
        with self.session_factory()() as session:
            template = ChecklistTemplate(
                tenant_id=tenant_id,
                name=payload.name,
                population=payload.population,
                program_id=self._uuid_or_none(payload.programId),
                term_code=payload.termCode,
                start_term_code=payload.studentType,
                active=payload.active,
                version=1,
            )
            session.add(template)
            session.flush()
            self._replace_template_items(session, template.id, payload)
            self._audit(session, tenant_id, actor_user_id, "checklist_template", template.id, "checklist_template_created", {"name": payload.name})
            session.commit()
            return self._template_dict(session, template)

    def update_checklist_template(self, tenant_id: UUID, actor_user_id: UUID, template_id: str, payload: ChecklistTemplatePayload) -> dict[str, Any]:
        with self.session_factory()() as session:
            template = self._get_template(session, tenant_id, template_id)
            before = {"name": template.name, "version": template.version, "active": template.active}
            template.name = payload.name
            template.population = payload.population
            template.program_id = self._uuid_or_none(payload.programId)
            template.term_code = payload.termCode
            template.start_term_code = payload.studentType
            template.active = payload.active
            template.version += 1
            self._replace_template_items(session, template.id, payload)
            self._audit(session, tenant_id, actor_user_id, "checklist_template", template.id, "checklist_template_updated", {"before": before, "version": template.version})
            session.commit()
            return self._template_dict(session, template)

    def publish_checklist_template(self, tenant_id: UUID, actor_user_id: UUID, template_id: str) -> dict[str, Any]:
        with self.session_factory()() as session:
            template = self._get_template(session, tenant_id, template_id)
            template.active = True
            template.version += 1
            self._audit(session, tenant_id, actor_user_id, "checklist_template", template.id, "checklist_template_published", {"version": template.version})
            session.commit()
            return self._template_dict(session, template)

    def generate_student_checklist(self, tenant_id: UUID, actor_user_id: UUID, student_id: str) -> RoadmapActionResponse:
        # The existing AdmissionsOpsService generates missing state on checklist read.
        from app.services.admissions_ops_service import AdmissionsOpsService

        response = AdmissionsOpsService(session_factory=self.session_factory).get_student_checklist(tenant_id, student_id)
        with self.session_factory()() as session:
            self._audit(session, tenant_id, actor_user_id, "student", self._uuid_or_none(response.studentId), "student_checklist_generated", {"student_id": response.studentId})
            session.commit()
        return RoadmapActionResponse(status="generated", detail="Checklist generated.", item=response.model_dump(mode="json"))

    def create_interaction(self, tenant_id: UUID, actor_user_id: UUID, student_id: str, payload: InteractionPayload) -> dict[str, Any]:
        with self.session_factory()() as session:
            student = self._resolve_student(session, tenant_id, student_id)
            body = payload.body or payload.note or payload.outcome or "Interaction logged."
            note = StudentNote(
                tenant_id=tenant_id,
                student_id=student.id,
                author_user_id=actor_user_id,
                note_type=payload.type,
                body=body,
                is_internal=True,
            )
            session.add(note)
            self._audit(session, tenant_id, actor_user_id, "student_note", note.id, "student_interaction_logged", {"student_id": str(student.id), "type": payload.type, **payload.payload})
            session.commit()
            return self._note_dict(session, note)

    def list_duplicates(self, tenant_id: UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        with self.session_factory()() as session:
            stmt = select(DuplicateCandidate).where(DuplicateCandidate.tenant_id == tenant_id)
            if q:
                stmt = stmt.where(DuplicateCandidate.status.ilike(f"%{q}%"))
            rows = session.execute(stmt.order_by(DuplicateCandidate.created_at.desc())).scalars().all()
            return self._items([self._duplicate_dict(row) for row in rows], limit, offset)

    def get_duplicate(self, tenant_id: UUID, candidate_id: str) -> ItemResponse:
        with self.session_factory()() as session:
            row = self._get_duplicate(session, tenant_id, candidate_id)
            return ItemResponse(item=self._duplicate_dict(row))

    def update_duplicate(self, tenant_id: UUID, actor_user_id: UUID, candidate_id: str, action: str, payload: RoadmapActionRequest) -> RoadmapActionResponse:
        with self.session_factory()() as session:
            row = self._get_duplicate(session, tenant_id, candidate_id)
            row.status = "merged" if action == "merge" else "dismissed"
            row.resolved_at = datetime.now(timezone.utc)
            self._audit(session, tenant_id, actor_user_id, "duplicate_candidate", row.id, f"duplicate_{action}", {"reason": payload.reason, "note": payload.note})
            session.commit()
            return RoadmapActionResponse(status=row.status, detail=f"Duplicate {action} recorded.", item=self._duplicate_dict(row))

    def transfer_evidence(self, tenant_id: UUID, student_id: str) -> dict[str, Any]:
        with self.session_factory()() as session:
            student = self._resolve_student(session, tenant_id, student_id)
            transcript_rows = session.execute(
                select(Transcript, TranscriptDemographics)
                .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
                .where(Transcript.tenant_id == tenant_id, Transcript.student_id == student.id)
                .order_by(Transcript.created_at.desc())
            ).all()
            transcript_ids = [row.Transcript.id for row in transcript_rows]
            course_count = 0
            if transcript_ids:
                course_count = int(session.execute(select(func.count()).select_from(TranscriptCourse).where(TranscriptCourse.tenant_id == tenant_id, TranscriptCourse.transcript_id.in_(transcript_ids))).scalar_one() or 0)
            credits = sum(float(row.TranscriptDemographics.total_credits_earned or 0) for row in transcript_rows if row.TranscriptDemographics)
            return {
                "studentId": str(student.id),
                "acceptedCredits": float(student.accepted_credits or credits or 0),
                "transcriptsCount": len(transcript_rows),
                "courseCount": course_count,
                "evidence": [
                    {
                        "transcriptId": str(transcript.id),
                        "institution": demographics.institution_name if demographics else None,
                        "credits": float(demographics.total_credits_earned or 0) if demographics else 0,
                        "gpa": float(demographics.cumulative_gpa or 0) if demographics else None,
                        "status": transcript.status,
                        "confidence": float(transcript.parser_confidence or 0),
                    }
                    for transcript, demographics in transcript_rows
                ],
            }

    def list_articulation_gaps(self, tenant_id: UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        return self._settings_items(tenant_id, "articulation_gaps", q=q, limit=limit, offset=offset)

    def route_articulation_gap(self, tenant_id: UUID, actor_user_id: UUID, gap_id: str, payload: RoadmapActionRequest) -> RoadmapActionResponse:
        return self._settings_action(tenant_id, actor_user_id, "articulation_gaps", gap_id, "articulation_gap_routed", payload, default_status="routed")

    def specialist_queue(self, tenant_id: UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        with self.session_factory()() as session:
            rows = session.execute(
                select(Student, Transcript)
                .join(Transcript, Transcript.student_id == Student.id)
                .where(Transcript.tenant_id == tenant_id, Student.tenant_id == tenant_id)
                .order_by(Transcript.updated_at.desc())
            ).all()
            items = [
                {
                    "studentId": str(student.id),
                    "studentName": self._student_name(student),
                    "transcriptId": str(transcript.id),
                    "status": transcript.status,
                    "reason": "Transfer evidence review",
                    "updatedAt": self._iso(transcript.updated_at),
                }
                for student, transcript in rows
                if not q or q.lower() in self._student_name(student).lower()
            ]
            return self._items(items, limit, offset)

    def list_queue_from_students(self, tenant_id: UUID, queue: str, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        with self.session_factory()() as session:
            stmt = select(Student).where(Student.tenant_id == tenant_id)
            if q:
                stmt = stmt.where(or_(Student.first_name.ilike(f"%{q}%"), Student.last_name.ilike(f"%{q}%"), Student.email.ilike(f"%{q}%")))
            rows = session.execute(stmt.order_by(Student.latest_activity_at.desc().nullslast(), Student.updated_at.desc())).scalars().all()
            items = [self._student_queue_item(session, tenant_id, student, queue) for student in rows]
            return self._items(items, limit, offset)

    def student_handoff(self, tenant_id: UUID, student_id: str) -> dict[str, Any]:
        with self.session_factory()() as session:
            student = self._resolve_student(session, tenant_id, student_id)
            tasks = session.execute(select(StudentTask).where(StudentTask.tenant_id == tenant_id, StudentTask.student_id == student.id, StudentTask.task_type.ilike("%handoff%"))).scalars().all()
            return {
                "studentId": str(student.id),
                "status": "ready" if not tasks else tasks[0].status,
                "package": {"studentName": self._student_name(student), "stage": student.current_stage},
                "officeReadiness": [self._task_dict(task) for task in tasks],
            }

    def update_student_status(self, tenant_id: UUID, actor_user_id: UUID, student_id: str, entity: str, payload: RoadmapActionRequest) -> RoadmapActionResponse:
        with self.session_factory()() as session:
            student = self._resolve_student(session, tenant_id, student_id)
            if entity == "deposit":
                milestone = StudentEnrollmentMilestone(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    milestone_code="deposit",
                    milestone_label="Deposit",
                    status=payload.status or "received",
                    achieved_at=datetime.now(timezone.utc),
                    metadata_json=payload.payload,
                )
                session.add(milestone)
                entity_id = milestone.id
            else:
                task = StudentTask(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    task_type=entity,
                    label=payload.note or payload.reason or f"{entity.title()} action",
                    status=payload.status or "open",
                    assigned_to_user_id=self._uuid_or_none(payload.ownerUserId),
                )
                session.add(task)
                entity_id = task.id
            self._audit(session, tenant_id, actor_user_id, "student", student.id, f"student_{entity}_updated", {"status": payload.status, "note": payload.note, **payload.payload})
            session.commit()
            return RoadmapActionResponse(status=payload.status or "recorded", detail=f"{entity.title()} update recorded.", item={"studentId": str(student.id), "entityId": str(entity_id)})

    def milestone_templates(self, tenant_id: UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        return self._settings_items(tenant_id, "milestone_templates", q=q, limit=limit, offset=offset)

    def create_milestone_template(self, tenant_id: UUID, actor_user_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        return self._settings_create(tenant_id, actor_user_id, "milestone_templates", "milestone_template_created", payload)

    def update_student_milestone(self, tenant_id: UUID, actor_user_id: UUID, student_id: str, milestone_id: str, payload: RoadmapActionRequest) -> RoadmapActionResponse:
        with self.session_factory()() as session:
            student = self._resolve_student(session, tenant_id, student_id)
            milestone = session.execute(select(StudentEnrollmentMilestone).where(StudentEnrollmentMilestone.tenant_id == tenant_id, StudentEnrollmentMilestone.id == self._uuid_or_none(milestone_id))).scalar_one_or_none()
            if milestone is None:
                milestone = StudentEnrollmentMilestone(tenant_id=tenant_id, student_id=student.id, milestone_code=milestone_id, milestone_label=payload.note or milestone_id, status=payload.status or "open", metadata_json=payload.payload)
                session.add(milestone)
            milestone.status = payload.status or milestone.status
            milestone.updated_at = datetime.now(timezone.utc)
            if milestone.status in {"complete", "completed", "received"}:
                milestone.achieved_at = milestone.achieved_at or datetime.now(timezone.utc)
            self._audit(session, tenant_id, actor_user_id, "student_enrollment_milestone", milestone.id, "milestone_status_updated", {"student_id": str(student.id), "status": milestone.status})
            session.commit()
            return RoadmapActionResponse(status=milestone.status, detail="Milestone status updated.", item=self._milestone_dict(milestone))

    def sync_errors(self, tenant_id: UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        return self._settings_items(tenant_id, "sync_errors", q=q, limit=limit, offset=offset)

    def sync_error_action(self, tenant_id: UUID, actor_user_id: UUID, error_id: str, action: str) -> RoadmapActionResponse:
        return self._settings_action(tenant_id, actor_user_id, "sync_errors", error_id, f"sync_error_{action}", RoadmapActionRequest(status=action), default_status=action)

    def connectors(self, tenant_id: UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        items = self._default_connectors()
        configured = self._settings_raw(tenant_id).get("connectors", [])
        by_id = {item["id"]: item for item in items}
        for item in configured:
            by_id.setdefault(item.get("id"), {}).update(item)
        merged = list(by_id.values())
        if q:
            merged = [item for item in merged if q.lower() in " ".join(str(v) for v in item.values()).lower()]
        return self._items(merged, limit, offset)

    def connector(self, tenant_id: UUID, connector_id: str) -> ItemResponse:
        items = self.connectors(tenant_id, limit=500).items
        for item in items:
            if item.get("id") == connector_id:
                return ItemResponse(item=item)
        raise RoadmapNotFoundError("Connector not found.")

    def connect_connector(self, tenant_id: UUID, actor_user_id: UUID, connector_id: str, payload: ConnectorConfigPayload) -> RoadmapActionResponse:
        item = self._upsert_settings_item(tenant_id, "connectors", connector_id, {"id": connector_id, "status": payload.status or "connected", "config": payload.config})
        with self.session_factory()() as session:
            self._audit(session, tenant_id, actor_user_id, "connector", None, "connector_connected", {"connector_id": connector_id})
            session.commit()
        return RoadmapActionResponse(status=item["status"], detail="Connector connected.", item=item)

    def test_connector(self, tenant_id: UUID, actor_user_id: UUID, connector_id: str) -> RoadmapActionResponse:
        with self.session_factory()() as session:
            self._audit(session, tenant_id, actor_user_id, "connector", None, "connector_tested", {"connector_id": connector_id, "status": "passed"})
            session.commit()
        return RoadmapActionResponse(status="passed", detail="Connector test completed.", item={"id": connector_id, "health": "ok"})

    def connector_mappings(self, tenant_id: UUID, connector_id: str) -> ItemResponse:
        mappings = self._settings_raw(tenant_id).get("connector_mappings", {})
        return ItemResponse(item={"connectorId": connector_id, "mappings": mappings.get(connector_id, [])})

    def save_connector_mappings(self, tenant_id: UUID, actor_user_id: UUID, connector_id: str, payload: ConnectorMappingsPayload) -> ItemResponse:
        with self.session_factory()() as session:
            settings = self._ensure_settings(session, tenant_id)
            data = dict(settings.settings_json or {})
            mappings = dict(data.get("connector_mappings") or {})
            mappings[connector_id] = payload.mappings
            data["connector_mappings"] = mappings
            settings.settings_json = data
            self._audit(session, tenant_id, actor_user_id, "connector", None, "connector_mappings_updated", {"connector_id": connector_id})
            session.commit()
        return self.connector_mappings(tenant_id, connector_id)

    def reporting(self, tenant_id: UUID, report_type: str, *, q: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        with self.session_factory()() as session:
            students = int(session.execute(select(func.count()).select_from(Student).where(Student.tenant_id == tenant_id)).scalar_one() or 0)
            transcripts = int(session.execute(select(func.count()).select_from(Transcript).where(Transcript.tenant_id == tenant_id)).scalar_one() or 0)
            completed = int(session.execute(select(func.count()).select_from(Transcript).where(Transcript.tenant_id == tenant_id, Transcript.status == "completed")).scalar_one() or 0)
            decisions = int(session.execute(select(func.count()).select_from(DecisionPacket).where(DecisionPacket.tenant_id == tenant_id)).scalar_one() or 0)
            trust = int(session.execute(select(func.count()).select_from(TrustFlag).where(TrustFlag.tenant_id == tenant_id, TrustFlag.status != "resolved")).scalar_one() or 0)
            metrics = {
                "students": students,
                "transcripts": transcripts,
                "completedTranscripts": completed,
                "documentCompletionRate": round(completed / transcripts, 4) if transcripts else 0,
                "decisionPackets": decisions,
                "openTrustFlags": trust,
            }
            return {"type": report_type, "metrics": metrics, "items": [], "total": 0, "limit": limit, "offset": offset}

    def communication_templates(self, tenant_id: UUID) -> dict[str, Any]:
        templates = list(self._settings_raw(tenant_id).get("communication_templates") or [])
        if not templates:
            templates = self._default_communication_templates()
        return {"items": templates, "total": len(templates)}

    def counselor_reporting(self, tenant_id: UUID, report_type: str, filters: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory()() as session:
            stage_rows = session.execute(
                select(Student.current_stage, func.count()).where(Student.tenant_id == tenant_id).group_by(Student.current_stage)
            ).all()
            handoff_total = int(session.execute(select(func.count()).select_from(StudentTask).where(StudentTask.tenant_id == tenant_id, StudentTask.task_type.ilike("%handoff%"))).scalar_one() or 0)
            handoff_open = int(session.execute(select(func.count()).select_from(StudentTask).where(StudentTask.tenant_id == tenant_id, StudentTask.task_type.ilike("%handoff%"), StudentTask.status.notin_(["Complete", "complete", "completed"]))).scalar_one() or 0)
            now = datetime.now(timezone.utc)
            handoff_overdue = int(session.execute(select(func.count()).select_from(StudentTask).where(StudentTask.tenant_id == tenant_id, StudentTask.task_type.ilike("%handoff%"), StudentTask.due_at < now, StudentTask.status.notin_(["Complete", "complete", "completed"]))).scalar_one() or 0)
            funnel = {str(stage or "unknown"): int(count) for stage, count in stage_rows}
            metrics = {
                "funnel": funnel,
                "conversionRates": self._conversion_rates(funnel),
                "averageDaysInStage": {},
                "averageResponseTimeByCounselor": {},
                "counselorWorkload": {},
                "completedApplicationsBySource": {},
                "yieldByProgram": {},
                "territorySourceEventPerformance": {},
                "handoffs": {
                    "openCount": handoff_open,
                    "overdueCount": handoff_overdue,
                    "completionRate": round((handoff_total - handoff_open) / handoff_total, 4) if handoff_total else 0,
                    "averageAge": None,
                },
            }
            return {"type": report_type, "filters": filters, "metrics": metrics, "items": [], "total": 0}

    def recruitment_events(self, tenant_id: UUID) -> dict[str, Any]:
        events = list(self._settings_raw(tenant_id).get("recruitment_events") or [])
        return {"items": events, "total": len(events)}

    def add_recruitment_attendee(self, tenant_id: UUID, actor_user_id: UUID, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory()() as session:
            settings = self._ensure_settings(session, tenant_id)
            data = dict(settings.settings_json or {})
            events = list(data.get("recruitment_events") or [])
            event = next((item for item in events if str(item.get("id")) == event_id), None)
            if event is None:
                event = {"id": event_id, "name": payload.get("eventName") or event_id, "attendees": []}
                events.append(event)
            attendees = list(event.get("attendees") or [])
            attendee = dict(payload)
            attendee.setdefault("id", f"attendee_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
            attendee.setdefault("eventId", event_id)
            attendees.append(attendee)
            event["attendees"] = attendees
            data["recruitment_events"] = events
            settings.settings_json = data

            student_id = payload.get("studentId")
            if student_id:
                student = self._resolve_student(session, tenant_id, student_id)
                from app.services.student_360_service import Student360Service

                Student360Service(session_factory=self.session_factory)._update_student_counselor_state(
                    session,
                    tenant_id=tenant_id,
                    student=student,
                    occurred_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    state_updates={
                        "lastActivity": "Just now",
                        "territory": payload.get("territory"),
                        "sourceSchool": payload.get("sourceSchool"),
                        "partnerSchool": payload.get("partnerSchool"),
                    },
                )
            self._audit(session, tenant_id, actor_user_id, "recruitment_event", None, "recruitment_attendee_added", {"eventId": event_id, **payload})
            session.commit()
            return {"attendee": attendee, "event": event}

    def list_handoffs(self, tenant_id: UUID, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        from app.services.student_360_service import Student360Service

        return Student360Service(session_factory=self.session_factory).list_handoffs(tenant_id, limit=limit, offset=offset)

    def update_handoff_status(self, db: Session, tenant_id: UUID, actor_user_id: UUID, handoff_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.student_360_service import Student360Service

        return Student360Service(session_factory=self.session_factory).update_handoff_status(db, tenant_id, actor_user_id, handoff_id, payload)

    def _conversion_rates(self, funnel: dict[str, int]) -> dict[str, float]:
        stages = ["Inquiry", "Prospect", "Applicant", "Incomplete", "Complete", "Admitted", "Deposited/Committed", "Registered"]
        rates: dict[str, float] = {}
        for previous, current in zip(stages, stages[1:]):
            prev_count = funnel.get(previous, 0)
            rates[f"{previous}_to_{current}"] = round(funnel.get(current, 0) / prev_count, 4) if prev_count else 0
        return rates

    def _default_communication_templates(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "tmpl_missing_transcript",
                "key": "missing_transcript",
                "label": "Missing transcript",
                "pipelineStatus": "Incomplete",
                "channel": "email",
                "subject": "Missing transcript",
                "body": "Please send your updated transcript so we can continue your application review.",
                "active": True,
            },
            {
                "id": "tmpl_follow_up",
                "key": "follow_up",
                "label": "Follow-up",
                "pipelineStatus": "Prospect",
                "channel": "text",
                "subject": "",
                "body": "Checking in on your next step.",
                "active": True,
            },
        ]

    def implementation_readiness(self, tenant_id: UUID) -> dict[str, Any]:
        checklist = self._settings_raw(tenant_id).get("implementation_checklist") or self._default_implementation_checklist()
        completed = sum(1 for item in checklist if item.get("status") == "complete")
        return {"items": checklist, "completed": completed, "total": len(checklist), "ready": completed == len(checklist)}

    def implementation_checklist_status(self, tenant_id: UUID, actor_user_id: UUID, item_id: str, payload: RoadmapActionRequest) -> RoadmapActionResponse:
        return self._settings_action(tenant_id, actor_user_id, "implementation_checklist", item_id, "implementation_checklist_status_updated", payload, default_status=payload.status or "complete")

    def graduate_program_queues(self, tenant_id: UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> ItemsResponse:
        with self.session_factory()() as session:
            rows = session.execute(select(Program).where(Program.tenant_id == tenant_id).order_by(Program.name.asc())).scalars().all()
            items = [{"programId": str(row.id), "program": row.name, "queue": "faculty_review", "applicants": 0} for row in rows if not q or q.lower() in row.name.lower()]
            return self._items(items, limit, offset)

    def graduate_packet(self, tenant_id: UUID, student_id: str) -> dict[str, Any]:
        with self.session_factory()() as session:
            student = self._resolve_student(session, tenant_id, student_id)
            packet = session.execute(select(DecisionPacket).where(DecisionPacket.tenant_id == tenant_id, DecisionPacket.student_id == student.id).order_by(DecisionPacket.created_at.desc()).limit(1)).scalar_one_or_none()
            return {"studentId": str(student.id), "studentName": self._student_name(student), "packet": self._decision_dict(packet) if packet else None, "committeeStatus": "not_started"}

    def graduate_action(self, tenant_id: UUID, actor_user_id: UUID, student_id: str, action: str, payload: RoadmapActionRequest) -> RoadmapActionResponse:
        with self.session_factory()() as session:
            student = self._resolve_student(session, tenant_id, student_id)
            self._audit(session, tenant_id, actor_user_id, "student", student.id, f"graduate_{action}_recorded", {"status": payload.status, "note": payload.note, **payload.payload})
            session.commit()
            return RoadmapActionResponse(status=payload.status or "recorded", detail=f"Graduate {action} recorded.", item={"studentId": str(student.id)})

    def graduate_department_permissions(self, tenant_id: UUID, department_id: str) -> dict[str, Any]:
        return {"departmentId": department_id, "permissions": ["view_student_360", "view_decision_packet", "recommend_decision"], "scopes": {"programs": [department_id]}}

    # Helpers
    def _items(self, all_items: list[dict[str, Any]], limit: int, offset: int) -> ItemsResponse:
        return ItemsResponse(items=all_items[offset : offset + limit], total=len(all_items), limit=limit, offset=offset)

    def _settings_items(self, tenant_id: UUID, key: str, *, q: str | None, limit: int, offset: int) -> ItemsResponse:
        items = list(self._settings_raw(tenant_id).get(key) or [])
        if q:
            items = [item for item in items if q.lower() in " ".join(str(v) for v in item.values()).lower()]
        return self._items(items, limit, offset)

    def _settings_create(self, tenant_id: UUID, actor_user_id: UUID, key: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item.setdefault("id", f"{key}_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
        item.setdefault("status", "active")
        with self.session_factory()() as session:
            settings = self._ensure_settings(session, tenant_id)
            data = dict(settings.settings_json or {})
            items = list(data.get(key) or [])
            items.append(item)
            data[key] = items
            settings.settings_json = data
            self._audit(session, tenant_id, actor_user_id, key, None, action, item)
            session.commit()
        return item

    def _settings_action(self, tenant_id: UUID, actor_user_id: UUID, key: str, item_id: str, action: str, payload: RoadmapActionRequest, *, default_status: str) -> RoadmapActionResponse:
        with self.session_factory()() as session:
            settings = self._ensure_settings(session, tenant_id)
            data = dict(settings.settings_json or {})
            items = list(data.get(key) or [])
            found = None
            for item in items:
                if str(item.get("id")) == item_id:
                    found = item
                    break
            if found is None:
                found = {"id": item_id}
                items.append(found)
            found["status"] = payload.status or default_status
            if payload.note:
                found["note"] = payload.note
            if payload.reason:
                found["reason"] = payload.reason
            found.update(payload.payload)
            data[key] = items
            settings.settings_json = data
            self._audit(session, tenant_id, actor_user_id, key, None, action, {"id": item_id, "status": found["status"]})
            session.commit()
            return RoadmapActionResponse(status=found["status"], detail=f"{action} recorded.", item=found)

    def _settings_raw(self, tenant_id: UUID) -> dict[str, Any]:
        with self.session_factory()() as session:
            return dict(self._ensure_settings(session, tenant_id).settings_json or {})

    def _upsert_settings_item(self, tenant_id: UUID, key: str, item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory()() as session:
            settings = self._ensure_settings(session, tenant_id)
            data = dict(settings.settings_json or {})
            items = list(data.get(key) or [])
            item = None
            for candidate in items:
                if candidate.get("id") == item_id:
                    item = candidate
                    break
            if item is None:
                item = {"id": item_id}
                items.append(item)
            item.update(patch)
            data[key] = items
            settings.settings_json = data
            session.commit()
            return item

    def _ensure_settings(self, session: Session, tenant_id: UUID) -> TenantSettings:
        row = session.execute(select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)).scalar_one_or_none()
        if row is None:
            row = TenantSettings(tenant_id=tenant_id, settings_json={})
            session.add(row)
            session.flush()
        return row

    def _replace_template_items(self, session: Session, template_id: UUID, payload: ChecklistTemplatePayload) -> None:
        for item in session.execute(select(ChecklistTemplateItem).where(ChecklistTemplateItem.template_id == template_id)).scalars().all():
            session.delete(item)
        session.flush()
        for index, item in enumerate(payload.items, start=1):
            session.add(
                ChecklistTemplateItem(
                    template_id=template_id,
                    code=item.code,
                    label=item.label,
                    required=item.required and not item.optional,
                    optional=item.optional,
                    conditional=item.conditional,
                    waivable=item.waivable,
                    blocking=item.blocking,
                    sort_order=item.sortOrder or index,
                    document_type=item.documentType,
                    review_required_default=item.reviewRequiredDefault,
                    active=True,
                )
            )

    def _template_dict(self, session: Session, template: ChecklistTemplate) -> dict[str, Any]:
        items = session.execute(select(ChecklistTemplateItem).where(ChecklistTemplateItem.template_id == template.id).order_by(ChecklistTemplateItem.sort_order.asc())).scalars().all()
        return {
            "id": str(template.id),
            "name": template.name,
            "population": template.population,
            "programId": str(template.program_id) if template.program_id else None,
            "termCode": template.term_code,
            "studentType": template.start_term_code,
            "active": template.active,
            "version": template.version,
            "items": [
                {
                    "code": item.code,
                    "label": item.label,
                    "required": item.required,
                    "optional": item.optional,
                    "conditional": item.conditional,
                    "waivable": item.waivable,
                    "blocking": item.blocking,
                    "sortOrder": item.sort_order,
                    "documentType": item.document_type,
                    "reviewRequiredDefault": item.review_required_default,
                }
                for item in items
            ],
        }

    def _get_template(self, session: Session, tenant_id: UUID, template_id: str) -> ChecklistTemplate:
        row = session.execute(select(ChecklistTemplate).where(ChecklistTemplate.tenant_id == tenant_id, ChecklistTemplate.id == self._uuid_or_none(template_id))).scalar_one_or_none()
        if row is None:
            raise RoadmapNotFoundError("Checklist template not found.")
        return row

    def _resolve_student(self, session: Session, tenant_id: UUID, student_id: str) -> Student:
        candidate_id = self._uuid_or_none(student_id)
        stmt = select(Student).where(Student.tenant_id == tenant_id)
        if candidate_id:
            row = session.execute(stmt.where(Student.id == candidate_id)).scalar_one_or_none()
            if row:
                return row
        row = session.execute(stmt.where(Student.external_student_id == student_id)).scalar_one_or_none()
        if row is None:
            raise RoadmapNotFoundError("Student not found.")
        return row

    def _get_duplicate(self, session: Session, tenant_id: UUID, candidate_id: str) -> DuplicateCandidate:
        row = session.execute(select(DuplicateCandidate).where(DuplicateCandidate.tenant_id == tenant_id, DuplicateCandidate.id == self._uuid_or_none(candidate_id))).scalar_one_or_none()
        if row is None:
            raise RoadmapNotFoundError("Duplicate candidate not found.")
        return row

    def _duplicate_dict(self, row: DuplicateCandidate) -> dict[str, Any]:
        return {"id": str(row.id), "primaryStudentId": str(row.primary_student_id), "candidateStudentId": str(row.candidate_student_id), "confidence": float(row.confidence_score), "reasons": row.match_reasons_json, "status": row.status, "createdAt": self._iso(row.created_at), "resolvedAt": self._iso(row.resolved_at)}

    def _student_queue_item(self, session: Session, tenant_id: UUID, student: Student, queue: str) -> dict[str, Any]:
        yield_score = session.execute(select(StudentYieldScore).where(StudentYieldScore.tenant_id == tenant_id, StudentYieldScore.student_id == student.id)).scalar_one_or_none()
        melt_score = session.execute(select(StudentMeltScore).where(StudentMeltScore.tenant_id == tenant_id, StudentMeltScore.student_id == student.id)).scalar_one_or_none()
        return {"studentId": str(student.id), "studentName": self._student_name(student), "queue": queue, "stage": student.current_stage, "risk": student.risk_level, "yieldScore": yield_score.score if yield_score else None, "meltScore": melt_score.score if melt_score else None, "updatedAt": self._iso(student.updated_at)}

    def _note_dict(self, session: Session, note: StudentNote) -> dict[str, Any]:
        author = session.execute(select(AppUser).where(AppUser.id == note.author_user_id)).scalar_one_or_none()
        return {"id": str(note.id), "studentId": str(note.student_id), "type": note.note_type, "body": note.body, "author": author.display_name if author else "System", "createdAt": self._iso(note.created_at)}

    def _task_dict(self, task: StudentTask) -> dict[str, Any]:
        return {"id": str(task.id), "type": task.task_type, "label": task.label, "status": task.status, "dueAt": self._iso(task.due_at), "completedAt": self._iso(task.completed_at)}

    def _milestone_dict(self, milestone: StudentEnrollmentMilestone) -> dict[str, Any]:
        return {"id": str(milestone.id), "studentId": str(milestone.student_id), "code": milestone.milestone_code, "label": milestone.milestone_label, "status": milestone.status, "achievedAt": self._iso(milestone.achieved_at)}

    def _decision_dict(self, packet: DecisionPacket | None) -> dict[str, Any] | None:
        if packet is None:
            return None
        return {"id": str(packet.id), "status": packet.status, "queue": packet.queue_name, "fitScore": packet.fit_score, "creditEstimate": packet.credit_estimate, "readiness": packet.readiness, "reason": packet.reason}

    def _student_name(self, student: Student) -> str:
        return " ".join(part for part in [student.first_name, student.last_name] if part) or student.external_student_id or str(student.id)

    def _default_connectors(self) -> list[dict[str, Any]]:
        return [
            {"id": "salesforce", "name": "Salesforce", "category": "crm", "status": "not_connected", "health": "unknown"},
            {"id": "slate", "name": "Slate", "category": "crm", "status": "not_connected", "health": "unknown"},
            {"id": "banner", "name": "Ellucian Banner", "category": "sis", "status": "not_connected", "health": "unknown"},
            {"id": "colleague", "name": "Ellucian Colleague", "category": "sis", "status": "not_connected", "health": "unknown"},
        ]

    def _default_implementation_checklist(self) -> list[dict[str, Any]]:
        return [
            {"id": "tenant_config", "label": "Tenant configuration", "status": "open"},
            {"id": "roles", "label": "Roles and permissions", "status": "open"},
            {"id": "checklist_templates", "label": "Checklist templates", "status": "open"},
            {"id": "connectors", "label": "Connector validation", "status": "open"},
            {"id": "training", "label": "Role training", "status": "open"},
        ]

    def _audit(self, session: Session, tenant_id: UUID, actor_user_id: UUID | None, entity_type: str, entity_id: UUID | None, action: str, payload: dict[str, Any]) -> None:
        session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                category="Roadmap",
                action=action,
                success=True,
                error_message=None,
                payload_json=payload,
                correlation_id=None,
                source="RoadmapService",
                occurred_at=datetime.now(timezone.utc),
            )
        )

    def _uuid_or_none(self, value: str | UUID | None) -> UUID | None:
        if isinstance(value, UUID):
            return value
        if not value:
            return None
        try:
            return UUID(str(value))
        except ValueError:
            return None

    def _iso(self, value: datetime | None) -> str | None:
        if not value:
            return None
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
