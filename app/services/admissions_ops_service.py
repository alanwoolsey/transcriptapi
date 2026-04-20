from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    AuditEvent,
    ChecklistTemplate,
    ChecklistTemplateItem,
    DecisionPacket,
    DocumentChecklistLink,
    DocumentUpload,
    DuplicateCandidate,
    Institution,
    Program,
    Student,
    StudentChecklist,
    StudentChecklistItem,
    StudentDecisionReadiness,
    StudentPriorityScore,
    StudentSignal,
    Transcript,
    TranscriptDemographics,
    TranscriptProcessingFailure,
    TrustFlag,
)
from app.db.session import get_session_factory
from app.models.ops_models import (
    ChecklistItemResponse,
    DocumentExceptionItem,
    DocumentExceptionsResponse,
    LinkChecklistItemRequest,
    StudentChecklistResponse,
    StudentReadinessResponse,
    WorkBlockingItem,
    WorkChecklistSummary,
    WorkItemOwner,
    WorkItemReason,
    WorkItemResponse,
    WorkItemsResponse,
    WorkSummaryCounts,
    WorkSummaryResponse,
)


class AdmissionsOpsNotFoundError(Exception):
    pass


class AdmissionsOpsValidationError(Exception):
    pass


@dataclass
class _ChecklistContext:
    student: Student
    checklist: StudentChecklist
    items: list[StudentChecklistItem]
    readiness: StudentDecisionReadiness
    priority: StudentPriorityScore


class AdmissionsOpsService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def get_student_checklist(self, tenant_id: UUID, student_id: str) -> StudentChecklistResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            context = self._ensure_student_state(session, tenant_id, student_id)
            session.commit()
            return self._serialize_checklist(context.student, context.checklist, context.items)

    def update_checklist_item_status(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        student_id: str,
        item_id: str,
        status: str,
    ) -> StudentChecklistResponse:
        normalized_status = status.strip().lower()
        if normalized_status not in {"missing", "received", "needs_review", "complete", "waived", "not_required"}:
            raise AdmissionsOpsValidationError("Invalid checklist item status.")

        context = self._ensure_student_state(db, tenant_id, student_id)
        item = self._find_checklist_item(context.items, item_id)
        previous_status = item.status
        now = datetime.now(timezone.utc)

        item.status = normalized_status
        item.needs_review = normalized_status == "needs_review"
        item.updated_by_user_id = actor_user_id
        item.updated_by_system = False
        item.updated_at = now
        if normalized_status in {"received", "needs_review", "complete"} and item.received_at is None:
            item.received_at = now
        if normalized_status == "complete":
            item.completed_at = now
        else:
            item.completed_at = None

        prev_readiness = context.readiness.readiness_state if context.readiness else None
        context = self._recalculate_student_state(db, tenant_id, context.student, context.checklist, context.items, actor_user_id=actor_user_id, actor_type="user")

        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            entity_type="student_checklist_item",
            entity_id=item.id,
            action="checklist_item_status_changed",
            actor_type="user",
            actor_user_id=actor_user_id,
            metadata={
                "student_id": str(context.student.id),
                "checklist_id": str(context.checklist.id),
                "item_code": item.code,
                "previous_status": previous_status,
                "status": normalized_status,
            },
        )
        if prev_readiness != context.readiness.readiness_state:
            self._write_audit_event(
                db,
                tenant_id=tenant_id,
                entity_type="student_decision_readiness",
                entity_id=context.readiness.id,
                action="readiness_state_changed",
                actor_type="user",
                actor_user_id=actor_user_id,
                metadata={
                    "student_id": str(context.student.id),
                    "previous_state": prev_readiness,
                    "readiness_state": context.readiness.readiness_state,
                },
            )
        db.commit()
        return self._serialize_checklist(context.student, context.checklist, context.items)

    def get_student_readiness(self, tenant_id: UUID, student_id: str) -> StudentReadinessResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            context = self._ensure_student_state(session, tenant_id, student_id)
            session.commit()
            return self._serialize_readiness(context.student, context.readiness)

    def get_work_summary(self, tenant_id: UUID) -> WorkSummaryResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            states = self._sync_tenant_students(session, tenant_id)
            counts = {"attention": 0, "close": 0, "ready": 0, "exceptions": 0}
            for context in states:
                section = self._section_for_student(context)
                counts[section] += 1
            session.commit()
            return WorkSummaryResponse(
                summary=WorkSummaryCounts(
                    needsAttention=counts["attention"],
                    closeToCompletion=counts["close"],
                    readyForDecision=counts["ready"],
                    exceptions=counts["exceptions"],
                )
            )

    def get_work_items(
        self,
        tenant_id: UUID,
        *,
        section: str | None = None,
        population: str | None = None,
        owner: str | None = None,
        priority: str | None = None,
        aging_bucket: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> WorkItemsResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            contexts = self._sync_tenant_students(session, tenant_id)
            work_items = [self._build_work_item(session, tenant_id, context) for context in contexts]
            filtered = [
                item for item in work_items
                if self._matches_work_filters(item, section=section, population=population, owner=owner, priority=priority, aging_bucket=aging_bucket, q=q)
            ]
            total = len(filtered)
            paged = filtered[offset: offset + limit]
            session.commit()
            return WorkItemsResponse(items=paged, page=(offset // limit) + 1, pageSize=limit, total=total)

    def link_document_to_checklist_item(
        self,
        db: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        document_id: str,
        payload: LinkChecklistItemRequest,
    ) -> StudentChecklistResponse:
        student = self._resolve_student(db, tenant_id, payload.studentId)
        if student is None:
            raise AdmissionsOpsNotFoundError("Student not found.")

        context = self._ensure_student_state(db, tenant_id, str(student.id))
        item = self._find_checklist_item(context.items, payload.checklistItemId)
        document = self._resolve_document(db, tenant_id, document_id)
        if document is None:
            raise AdmissionsOpsNotFoundError("Document not found.")

        now = datetime.now(timezone.utc)
        link = db.execute(
            select(DocumentChecklistLink).where(
                DocumentChecklistLink.tenant_id == tenant_id,
                DocumentChecklistLink.document_id == document.id,
                DocumentChecklistLink.checklist_item_id == item.id,
            )
        ).scalar_one_or_none()
        if link is None:
            link = DocumentChecklistLink(
                tenant_id=tenant_id,
                student_id=student.id,
                document_id=document.id,
                checklist_item_id=item.id,
                linked_by="user",
            )
            db.add(link)

        link.match_confidence = self._to_decimal(payload.matchConfidence)
        link.match_status = payload.matchStatus
        link.linked_at = now
        link.linked_by = "user"

        item.source_document_id = document.id
        item.source_confidence = self._to_decimal(payload.matchConfidence)
        item.received_at = item.received_at or document.uploaded_at or now
        item.updated_by_user_id = actor_user_id
        item.updated_by_system = False
        item.updated_at = now
        if payload.matchStatus == "auto_completed":
            item.status = "complete"
            item.needs_review = False
            item.completed_at = now
        elif payload.matchStatus == "needs_review":
            item.status = "needs_review"
            item.needs_review = True
            item.completed_at = None
        else:
            item.status = "received"
            item.needs_review = False
            item.completed_at = None

        prev_readiness = context.readiness.readiness_state if context.readiness else None
        context = self._recalculate_student_state(db, tenant_id, context.student, context.checklist, context.items, actor_user_id=actor_user_id, actor_type="user")
        self._write_audit_event(
            db,
            tenant_id=tenant_id,
            entity_type="document_checklist_link",
            entity_id=link.id,
            action="document_linked_to_checklist_item",
            actor_type="user",
            actor_user_id=actor_user_id,
            metadata={
                "student_id": str(student.id),
                "document_id": str(document.id),
                "checklist_item_id": str(item.id),
                "match_status": payload.matchStatus,
                "match_confidence": payload.matchConfidence,
            },
        )
        if prev_readiness != context.readiness.readiness_state:
            self._write_audit_event(
                db,
                tenant_id=tenant_id,
                entity_type="student_decision_readiness",
                entity_id=context.readiness.id,
                action="readiness_state_changed",
                actor_type="user",
                actor_user_id=actor_user_id,
                metadata={
                    "student_id": str(context.student.id),
                    "previous_state": prev_readiness,
                    "readiness_state": context.readiness.readiness_state,
                },
            )
        db.commit()
        return self._serialize_checklist(context.student, context.checklist, context.items)

    def get_document_exceptions(self, tenant_id: UUID) -> DocumentExceptionsResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            self._sync_tenant_students(session, tenant_id)
            items: list[DocumentExceptionItem] = []

            link_rows = session.execute(
                select(DocumentChecklistLink, StudentChecklistItem, Student)
                .join(StudentChecklistItem, StudentChecklistItem.id == DocumentChecklistLink.checklist_item_id)
                .join(Student, Student.id == DocumentChecklistLink.student_id)
                .where(
                    DocumentChecklistLink.tenant_id == tenant_id,
                    DocumentChecklistLink.match_status.in_(["needs_review", "unresolved"]),
                )
                .order_by(DocumentChecklistLink.linked_at.desc())
            ).all()
            for link, checklist_item, student in link_rows:
                items.append(
                    DocumentExceptionItem(
                        id=str(link.id),
                        studentId=self._student_identifier(student),
                        studentName=self._student_name(student),
                        documentId=str(link.document_id),
                        issueType="checklist_linkage",
                        label=f"{checklist_item.label} requires review",
                        status=link.match_status,
                        createdAt=self._isoformat(link.linked_at),
                    )
                )

            failure_rows = session.execute(
                select(TranscriptProcessingFailure, Student)
                .outerjoin(Transcript, Transcript.id == TranscriptProcessingFailure.transcript_id)
                .outerjoin(Student, Student.id == Transcript.student_id)
                .where(TranscriptProcessingFailure.tenant_id == tenant_id)
                .order_by(TranscriptProcessingFailure.created_at.desc())
            ).all()
            for failure, student in failure_rows:
                items.append(
                    DocumentExceptionItem(
                        id=str(failure.id),
                        studentId=self._student_identifier(student) if student else None,
                        studentName=self._student_name(student) if student else failure.filename,
                        documentId=str(failure.document_upload_id) if failure.document_upload_id else None,
                        issueType="processing_failure",
                        label=failure.failure_message,
                        status=failure.failure_code,
                        createdAt=self._isoformat(failure.created_at),
                    )
                )

            return DocumentExceptionsResponse(items=items, total=len(items))

    def _sync_tenant_students(self, session: Session, tenant_id: UUID) -> list[_ChecklistContext]:
        students = session.execute(
            select(Student).where(Student.tenant_id == tenant_id).order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc())
        ).scalars().all()
        contexts: list[_ChecklistContext] = []
        for student in students:
            contexts.append(self._ensure_student_state(session, tenant_id, str(student.id)))
        return contexts

    def _ensure_student_state(self, session: Session, tenant_id: UUID, student_id: str) -> _ChecklistContext:
        student = self._resolve_student(session, tenant_id, student_id)
        if student is None:
            raise AdmissionsOpsNotFoundError("Student not found.")

        checklist = session.execute(
            select(StudentChecklist).where(StudentChecklist.tenant_id == tenant_id, StudentChecklist.student_id == student.id).limit(1)
        ).scalar_one_or_none()
        if checklist is None:
            checklist = self._instantiate_checklist(session, tenant_id, student)
        items = session.execute(
            select(StudentChecklistItem)
            .where(StudentChecklistItem.tenant_id == tenant_id, StudentChecklistItem.student_checklist_id == checklist.id)
            .order_by(StudentChecklistItem.label.asc())
        ).scalars().all()

        self._apply_document_automation(session, tenant_id, student, items)
        return self._recalculate_student_state(session, tenant_id, student, checklist, items, actor_user_id=None, actor_type="system")

    def _instantiate_checklist(self, session: Session, tenant_id: UUID, student: Student) -> StudentChecklist:
        population = self._population_for_student(student)
        template = self._ensure_default_template(session, tenant_id, population)
        checklist = StudentChecklist(
            tenant_id=tenant_id,
            student_id=student.id,
            template_id=template.id,
            population=population,
            completion_percent=0,
            one_item_away=False,
            status="incomplete",
        )
        session.add(checklist)
        session.flush()

        template_items = session.execute(
            select(ChecklistTemplateItem)
            .where(ChecklistTemplateItem.template_id == template.id, ChecklistTemplateItem.active.is_(True))
            .order_by(ChecklistTemplateItem.sort_order.asc(), ChecklistTemplateItem.created_at.asc())
        ).scalars().all()
        now = datetime.now(timezone.utc)
        for template_item in template_items:
            session.add(
                StudentChecklistItem(
                    student_checklist_id=checklist.id,
                    tenant_id=tenant_id,
                    student_id=student.id,
                    template_item_id=template_item.id,
                    code=template_item.code,
                    label=template_item.label,
                    required=template_item.required,
                    status="missing",
                    needs_review=template_item.review_required_default,
                    updated_by_system=True,
                    updated_at=now,
                )
            )
        session.flush()
        return checklist

    def _ensure_default_template(self, session: Session, tenant_id: UUID, population: str) -> ChecklistTemplate:
        template = session.execute(
            select(ChecklistTemplate)
            .where(
                ChecklistTemplate.tenant_id == tenant_id,
                ChecklistTemplate.population == population,
                ChecklistTemplate.active.is_(True),
            )
            .order_by(ChecklistTemplate.version.desc(), ChecklistTemplate.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if template is not None:
            return template

        template = ChecklistTemplate(
            tenant_id=tenant_id,
            name=f"{population.title()} Admissions Checklist",
            population=population,
            active=True,
            version=1,
        )
        session.add(template)
        session.flush()

        for sort_order, item in enumerate(self._default_template_items(population), start=1):
            session.add(
                ChecklistTemplateItem(
                    template_id=template.id,
                    code=item["code"],
                    label=item["label"],
                    required=item["required"],
                    sort_order=sort_order,
                    document_type=item.get("document_type"),
                    review_required_default=item.get("review_required_default", False),
                    active=True,
                )
            )
        session.flush()
        return template

    def _apply_document_automation(self, session: Session, tenant_id: UUID, student: Student, items: list[StudentChecklistItem]) -> None:
        transcript_rows = session.execute(
            select(Transcript, DocumentUpload)
            .join(DocumentUpload, DocumentUpload.id == Transcript.document_upload_id)
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id == student.id)
            .order_by(Transcript.created_at.desc())
        ).all()
        if not transcript_rows:
            return

        latest_transcript, latest_upload = transcript_rows[0]
        confidence = self._to_float(latest_transcript.parser_confidence, None)
        now = datetime.now(timezone.utc)
        if latest_transcript.is_fraudulent:
            match_status = "needs_review"
            checklist_status = "needs_review"
        elif latest_transcript.status in {"parsed", "completed"} and confidence is not None and confidence >= 0.9:
            match_status = "auto_completed"
            checklist_status = "complete"
        elif latest_transcript.status in {"parsed", "completed"}:
            match_status = "needs_review"
            checklist_status = "needs_review"
        else:
            match_status = "unresolved"
            checklist_status = "received"

        for item in items:
            if item.code not in {"official_transcript", "college_transcript"} and "transcript" not in item.code:
                continue
            if item.status == "complete" and item.source_document_id == latest_upload.id:
                continue

            item.source_document_id = latest_upload.id
            item.source_confidence = self._to_decimal(confidence)
            item.received_at = item.received_at or latest_upload.uploaded_at or now
            item.updated_by_system = True
            item.updated_at = now
            if checklist_status == "complete":
                item.status = "complete"
                item.needs_review = False
                item.completed_at = item.completed_at or now
            elif checklist_status == "needs_review":
                item.status = "needs_review"
                item.needs_review = True
                item.completed_at = None
            else:
                item.status = "received"
                item.needs_review = False
                item.completed_at = None

            link = session.execute(
                select(DocumentChecklistLink).where(
                    DocumentChecklistLink.tenant_id == tenant_id,
                    DocumentChecklistLink.document_id == latest_upload.id,
                    DocumentChecklistLink.checklist_item_id == item.id,
                )
            ).scalar_one_or_none()
            if link is None:
                link = DocumentChecklistLink(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    document_id=latest_upload.id,
                    checklist_item_id=item.id,
                    linked_by="system",
                )
                session.add(link)
            link.match_confidence = self._to_decimal(confidence)
            link.match_status = match_status
            link.linked_at = now
            link.linked_by = "system"

    def _recalculate_student_state(
        self,
        session: Session,
        tenant_id: UUID,
        student: Student,
        checklist: StudentChecklist,
        items: list[StudentChecklistItem],
        *,
        actor_user_id: UUID | None,
        actor_type: str,
    ) -> _ChecklistContext:
        required_items = [item for item in items if item.required]
        total_required = len(required_items)
        completed_required = sum(1 for item in required_items if item.status in {"complete", "waived", "not_required"})
        missing_items = [item for item in required_items if item.status == "missing"]
        review_items = [item for item in required_items if item.status in {"needs_review", "received"}]
        incomplete_required = len(required_items) - completed_required

        checklist.completion_percent = round((completed_required / total_required) * 100) if total_required else 100
        checklist.one_item_away = incomplete_required == 1
        checklist.status = "complete" if incomplete_required == 0 else "incomplete"
        checklist.updated_at = datetime.now(timezone.utc)

        trust_blocked = self._has_trust_block(session, tenant_id, student.id)
        readiness = session.execute(
            select(StudentDecisionReadiness).where(
                StudentDecisionReadiness.tenant_id == tenant_id,
                StudentDecisionReadiness.student_id == student.id,
            )
        ).scalar_one_or_none()
        if readiness is None:
            readiness = StudentDecisionReadiness(tenant_id=tenant_id, student_id=student.id)
            session.add(readiness)

        if trust_blocked:
            readiness.readiness_state = "blocked_by_trust"
            readiness.reason_code = "trust_block"
            readiness.reason_label = "Student is blocked by active trust review."
        elif review_items:
            blocking_item = review_items[0]
            readiness.readiness_state = "blocked_by_review"
            readiness.reason_code = blocking_item.code
            readiness.reason_label = f"{blocking_item.label} requires staff review"
        elif missing_items:
            blocking_item = missing_items[0]
            readiness.readiness_state = "blocked_by_missing_item"
            readiness.reason_code = blocking_item.code
            readiness.reason_label = f"{blocking_item.label} is still missing"
        else:
            readiness.readiness_state = "ready_for_decision"
            readiness.reason_code = "ready_for_decision"
            readiness.reason_label = "Checklist is complete and ready for decision."
        readiness.blocking_item_count = len(missing_items) + len(review_items)
        readiness.trust_blocked = trust_blocked
        readiness.computed_at = datetime.now(timezone.utc)

        priority = session.execute(
            select(StudentPriorityScore).where(
                StudentPriorityScore.tenant_id == tenant_id,
                StudentPriorityScore.student_id == student.id,
            )
        ).scalar_one_or_none()
        if priority is None:
            priority = StudentPriorityScore(tenant_id=tenant_id, student_id=student.id)
            session.add(priority)
        priority_band, priority_score, reason_code = self._priority_for_student(
            checklist=checklist,
            readiness=readiness,
            fit_score=self._estimate_fit_score(student.latest_cumulative_gpa, student.accepted_credits, self._latest_transcript_confidence(session, tenant_id, student.id)),
            has_recent_doc_review=self._has_recent_doc_review(items),
            trust_blocked=trust_blocked,
        )
        priority.priority_band = priority_band
        priority.priority_score = priority_score
        priority.reason_code = reason_code
        priority.computed_at = datetime.now(timezone.utc)

        self._replace_signals(session, tenant_id, student, checklist, items, readiness, priority)
        session.flush()
        return _ChecklistContext(student=student, checklist=checklist, items=items, readiness=readiness, priority=priority)

    def _replace_signals(
        self,
        session: Session,
        tenant_id: UUID,
        student: Student,
        checklist: StudentChecklist,
        items: list[StudentChecklistItem],
        readiness: StudentDecisionReadiness,
        priority: StudentPriorityScore,
    ) -> None:
        session.execute(
            StudentSignal.__table__.delete().where(
                StudentSignal.tenant_id == tenant_id,
                StudentSignal.student_id == student.id,
            )
        )
        now = datetime.now(timezone.utc)
        signals: list[StudentSignal] = []
        blocking_items = [item for item in items if item.required and item.status in {"missing", "needs_review", "received"}]
        if checklist.one_item_away and blocking_items:
            signals.append(
                StudentSignal(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    signal_type="missing_one_item",
                    signal_label=f"One item away: {blocking_items[0].label}",
                    severity="high",
                    active=True,
                    detected_at=now,
                    source="admissions_ops",
                    metadata_json={"checklist_item_id": str(blocking_items[0].id)},
                )
            )
        if readiness.readiness_state == "ready_for_decision":
            signals.append(
                StudentSignal(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    signal_type="ready_for_decision",
                    signal_label="Student is ready for decision",
                    severity="medium",
                    active=True,
                    detected_at=now,
                    source="admissions_ops",
                    metadata_json={},
                )
            )
        if readiness.trust_blocked:
            signals.append(
                StudentSignal(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    signal_type="trust_block",
                    signal_label="Active trust block",
                    severity="high",
                    active=True,
                    detected_at=now,
                    source="admissions_ops",
                    metadata_json={},
                )
            )
        if any(item.status == "received" for item in blocking_items):
            signals.append(
                StudentSignal(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    signal_type="pending_evidence",
                    signal_label="Document evidence is pending review",
                    severity="medium",
                    active=True,
                    detected_at=now,
                    source="admissions_ops",
                    metadata_json={},
                )
            )
        if self._is_stalled(student):
            signals.append(
                StudentSignal(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    signal_type="stalled",
                    signal_label="Student workflow is stalled",
                    severity="medium",
                    active=True,
                    detected_at=now,
                    source="admissions_ops",
                    metadata_json={},
                )
            )
        if self._has_recent_doc_review(items):
            signals.append(
                StudentSignal(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    signal_type="new_document_uploaded",
                    signal_label="Recent document upload requires review",
                    severity="medium",
                    active=True,
                    detected_at=now,
                    source="admissions_ops",
                    metadata_json={},
                )
            )
        if self._has_duplicate_candidate(session, tenant_id, student.id):
            signals.append(
                StudentSignal(
                    tenant_id=tenant_id,
                    student_id=student.id,
                    signal_type="duplicate_candidate",
                    signal_label="Possible duplicate student record",
                    severity="medium",
                    active=True,
                    detected_at=now,
                    source="admissions_ops",
                    metadata_json={},
                )
            )
        session.add_all(signals)

    def _build_work_item(self, session: Session, tenant_id: UUID, context: _ChecklistContext) -> WorkItemResponse:
        student = context.student
        section = self._section_for_student(context)
        reason = self._reason_to_act(context)
        suggested_action = self._suggested_action(context)
        blocking_items = [
            WorkBlockingItem(id=str(item.id), code=item.code, label=item.label, status=item.status)
            for item in context.items
            if item.required and item.status in {"missing", "needs_review", "received"}
        ]
        required_items = [item for item in context.items if item.required]
        total_required = len(required_items)
        completed_count = sum(1 for item in required_items if item.status in {"complete", "waived", "not_required"})
        missing_count = sum(1 for item in required_items if item.status == "missing")
        review_count = sum(1 for item in required_items if item.status in {"needs_review", "received"})
        owner = self._load_owner(session, student.advisor_user_id)
        program_name = self._program_name(session, student)
        institution_goal = self._institution_goal(session, tenant_id, student)
        latest_confidence = self._latest_transcript_confidence(session, tenant_id, student.id)

        return WorkItemResponse(
            id=f"work_{student.id.hex[:12]}",
            studentId=self._student_identifier(student),
            studentName=self._student_name(student),
            population=context.checklist.population,
            stage=context.checklist.status,
            completionPercent=context.checklist.completion_percent,
            priority=context.priority.priority_band,
            priorityScore=context.priority.priority_score,
            section=section,
            owner=WorkItemOwner(id=(str(owner.id) if owner else None), name=(owner.display_name if owner else "Unassigned")),
            reasonToAct=reason,
            suggestedAction=suggested_action,
            readiness={
                "state": context.readiness.readiness_state,
                "label": self._title_case(context.readiness.readiness_state),
                "tone": self._readiness_tone(context.readiness.readiness_state),
            },
            blockingItems=blocking_items,
            checklistSummary=WorkChecklistSummary(
                totalRequired=total_required,
                completedCount=completed_count,
                missingCount=missing_count,
                needsReviewCount=review_count,
                oneItemAway=context.checklist.one_item_away,
            ),
            fitScore=self._estimate_fit_score(student.latest_cumulative_gpa, student.accepted_credits, latest_confidence),
            depositLikelihood=self._estimate_deposit_likelihood(student.risk_level, student.latest_cumulative_gpa, latest_confidence),
            program=program_name,
            institutionGoal=institution_goal,
            risk=self._title_case(student.risk_level or "low"),
            lastActivity=self._relative_time(student.latest_activity_at or student.updated_at),
            updatedAt=self._isoformat(student.latest_activity_at or student.updated_at),
        )

    def _matches_work_filters(
        self,
        item: WorkItemResponse,
        *,
        section: str | None,
        population: str | None,
        owner: str | None,
        priority: str | None,
        aging_bucket: str | None,
        q: str | None,
    ) -> bool:
        if section and item.section != section:
            return False
        if population and item.population != population:
            return False
        if owner and item.owner.id != owner and item.owner.name.lower() != owner.lower():
            return False
        if priority and item.priority != priority:
            return False
        if aging_bucket and not self._matches_aging_bucket(item.lastActivity, aging_bucket):
            return False
        if q and q.strip():
            haystack = " ".join([item.studentName, item.program, item.institutionGoal, item.reasonToAct.label]).lower()
            if q.strip().lower() not in haystack:
                return False
        return True

    def _matches_aging_bucket(self, last_activity: str, aging_bucket: str) -> bool:
        if not aging_bucket:
            return True
        lowered = last_activity.lower()
        if aging_bucket == "recent":
            return "hour" in lowered or "min" in lowered
        if aging_bucket == "stale":
            return "day" in lowered
        return True

    def _readiness_tone(self, readiness_state: str | None) -> str:
        normalized = (readiness_state or "").lower()
        if normalized == "ready_for_decision":
            return "positive"
        if normalized == "blocked_by_trust":
            return "high"
        if normalized in {"blocked_by_review", "blocked_by_missing_item"}:
            return "medium"
        return "neutral"

    def _section_for_student(self, context: _ChecklistContext) -> str:
        has_pending_evidence = any(item.required and item.status == "received" for item in context.items)
        if context.readiness.trust_blocked or has_pending_evidence:
            return "exceptions"
        if context.readiness.readiness_state == "ready_for_decision":
            return "ready"
        if context.checklist.one_item_away or (context.checklist.completion_percent >= 75 and not context.readiness.trust_blocked):
            return "close"
        return "attention"

    def _priority_for_student(
        self,
        *,
        checklist: StudentChecklist,
        readiness: StudentDecisionReadiness,
        fit_score: int,
        has_recent_doc_review: bool,
        trust_blocked: bool,
    ) -> tuple[str, int, str]:
        if trust_blocked:
            return ("urgent", 95, "trust_block")
        if checklist.one_item_away:
            return ("urgent", 90, "missing_one_item")
        if checklist.status != "complete" and fit_score >= 85 and readiness.blocking_item_count > 0:
            return ("urgent", 88, "high_value_blocker")
        if readiness.readiness_state == "ready_for_decision":
            return ("today", 80, "ready_for_decision")
        if checklist.completion_percent >= 75:
            return ("today", 75, "close_to_completion")
        if has_recent_doc_review:
            return ("today", 72, "new_document_uploaded")
        return ("soon", 55, "general_follow_up")

    def _reason_to_act(self, context: _ChecklistContext) -> WorkItemReason:
        blocking_items = [item for item in context.items if item.required and item.status in {"missing", "needs_review", "received"}]
        if context.readiness.trust_blocked:
            return WorkItemReason(code="trust_block", label="Trust hold requires intervention")
        if context.checklist.one_item_away and blocking_items:
            return WorkItemReason(code="missing_one_item", label=f"One item away: {blocking_items[0].label}")
        if context.readiness.readiness_state == "ready_for_decision":
            return WorkItemReason(code="ready_for_decision", label="Checklist complete and ready for decision")
        if blocking_items:
            first = blocking_items[0]
            code = "needs_review" if first.status in {"needs_review", "received"} else first.code
            return WorkItemReason(code=code, label=f"{first.label} is blocking progress")
        return WorkItemReason(code=context.priority.reason_code, label="Student requires follow-up")

    def _suggested_action(self, context: _ChecklistContext) -> WorkItemReason:
        blocking_items = [item for item in context.items if item.required and item.status in {"missing", "needs_review", "received"}]
        if context.readiness.trust_blocked:
            return WorkItemReason(code="review_trust", label="Review trust blockers")
        if context.readiness.readiness_state == "ready_for_decision":
            return WorkItemReason(code="move_to_decision", label="Move student to decision review")
        if blocking_items:
            item = blocking_items[0]
            if item.status in {"needs_review", "received"}:
                return WorkItemReason(code="review_document", label=f"Review {item.label.lower()}")
            return WorkItemReason(code="request_document", label=f"Request {item.label.lower()}")
        return WorkItemReason(code="follow_up", label="Follow up with student")

    def _resolve_student(self, session: Session, tenant_id: UUID, student_id: str) -> Student | None:
        stmt = select(Student).where(Student.tenant_id == tenant_id)
        try:
            resolved_student_id = UUID(student_id)
            stmt = stmt.where(Student.id == resolved_student_id)
        except ValueError:
            stmt = stmt.where(Student.external_student_id == student_id)
        return session.execute(stmt.limit(1)).scalar_one_or_none()

    def _resolve_document(self, session: Session, tenant_id: UUID, document_id: str) -> DocumentUpload | None:
        try:
            resolved_document_id = UUID(document_id)
        except ValueError:
            return None
        return session.execute(
            select(DocumentUpload).where(DocumentUpload.tenant_id == tenant_id, DocumentUpload.id == resolved_document_id).limit(1)
        ).scalar_one_or_none()

    def _find_checklist_item(self, items: list[StudentChecklistItem], item_id: str) -> StudentChecklistItem:
        try:
            resolved_item_id = UUID(item_id)
        except ValueError as exc:
            raise AdmissionsOpsValidationError("Checklist item id must be a valid UUID.") from exc
        for item in items:
            if item.id == resolved_item_id:
                return item
        raise AdmissionsOpsNotFoundError("Checklist item not found.")

    def _serialize_checklist(self, student: Student, checklist: StudentChecklist, items: list[StudentChecklistItem]) -> StudentChecklistResponse:
        sorted_items = sorted(items, key=lambda item: (item.required is False, item.label.lower()))
        return StudentChecklistResponse(
            studentId=self._student_identifier(student),
            population=checklist.population,
            completionPercent=checklist.completion_percent,
            oneItemAway=checklist.one_item_away,
            status=checklist.status,
            items=[
                ChecklistItemResponse(
                    id=str(item.id),
                    code=item.code,
                    label=item.label,
                    required=item.required,
                    status=item.status,
                    done=item.status in {"complete", "waived", "not_required"},
                    category=self._checklist_category(item.code),
                    receivedAt=self._isoformat(item.received_at),
                    completedAt=self._isoformat(item.completed_at),
                    sourceDocumentId=(str(item.source_document_id) if item.source_document_id else None),
                    sourceConfidence=self._to_float(item.source_confidence, None),
                    updatedAt=self._isoformat(item.updated_at),
                    updatedBy={"id": str(item.updated_by_user_id), "name": "User"} if item.updated_by_user_id else None,
                )
                for item in sorted_items
            ],
        )

    def _checklist_category(self, code: str) -> str:
        normalized = (code or "").lower()
        if "transcript" in normalized or "document" in normalized:
            return "documents"
        if normalized in {"fafsa", "residency_form"}:
            return "verification"
        return "application"

    def _serialize_readiness(self, student: Student, readiness: StudentDecisionReadiness) -> StudentReadinessResponse:
        return StudentReadinessResponse(
            studentId=self._student_identifier(student),
            state=readiness.readiness_state,
            label=self._title_case(readiness.readiness_state),
            reason=readiness.reason_label,
            updatedAt=self._isoformat(readiness.computed_at) or self._isoformat(datetime.now(timezone.utc)),
            readinessState=readiness.readiness_state,
            reasonCode=readiness.reason_code,
            reasonLabel=readiness.reason_label,
            blockingItemCount=readiness.blocking_item_count,
            trustBlocked=readiness.trust_blocked,
            computedAt=self._isoformat(readiness.computed_at) or self._isoformat(datetime.now(timezone.utc)),
        )

    def _write_audit_event(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        entity_type: str,
        entity_id: UUID | None,
        action: str,
        actor_type: str,
        actor_user_id: UUID | None,
        metadata: dict,
    ) -> None:
        session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                category="AdmissionsOps",
                action=action,
                success=True,
                error_message=None,
                payload_json={"actor_type": actor_type, "metadata_json": metadata},
                correlation_id=None,
                source="AdmissionsOps",
                occurred_at=datetime.now(timezone.utc),
            )
        )

    def _has_trust_block(self, session: Session, tenant_id: UUID, student_id: UUID) -> bool:
        trust_flags = session.execute(
            select(func.count())
            .select_from(TrustFlag)
            .where(
                TrustFlag.tenant_id == tenant_id,
                TrustFlag.student_id == student_id,
                TrustFlag.status.notin_(["resolved", "closed"]),
            )
        ).scalar_one()
        fraudulent_transcripts = session.execute(
            select(func.count())
            .select_from(Transcript)
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id == student_id, Transcript.is_fraudulent.is_(True))
        ).scalar_one()
        return bool(trust_flags or fraudulent_transcripts)

    def _has_duplicate_candidate(self, session: Session, tenant_id: UUID, student_id: UUID) -> bool:
        count = session.execute(
            select(func.count())
            .select_from(DuplicateCandidate)
            .where(
                DuplicateCandidate.tenant_id == tenant_id,
                DuplicateCandidate.status == "open",
                or_(
                    DuplicateCandidate.primary_student_id == student_id,
                    DuplicateCandidate.candidate_student_id == student_id,
                ),
            )
        ).scalar_one()
        return bool(count)

    def _has_recent_doc_review(self, items: list[StudentChecklistItem]) -> bool:
        now = datetime.now(timezone.utc)
        for item in items:
            if item.status in {"needs_review", "received"} and item.received_at and now - item.received_at <= timedelta(days=1):
                return True
        return False

    def _latest_transcript_confidence(self, session: Session, tenant_id: UUID, student_id: UUID) -> float | None:
        return self._to_float(
            session.execute(
                select(Transcript.parser_confidence)
                .where(Transcript.tenant_id == tenant_id, Transcript.student_id == student_id)
                .order_by(Transcript.created_at.desc())
                .limit(1)
            ).scalar_one_or_none(),
            None,
        )

    def _program_name(self, session: Session, student: Student) -> str:
        if not student.target_program_id:
            return "Transcript intake"
        program = session.get(Program, student.target_program_id)
        return program.name if program else "Transcript intake"

    def _institution_goal(self, session: Session, tenant_id: UUID, student: Student) -> str:
        if student.target_institution_id:
            institution = session.get(Institution, student.target_institution_id)
            if institution is not None:
                return institution.name
        latest = session.execute(
            select(TranscriptDemographics.institution_name)
            .join(Transcript, Transcript.id == TranscriptDemographics.transcript_id)
            .where(Transcript.tenant_id == tenant_id, Transcript.student_id == student.id)
            .order_by(Transcript.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return latest or "Unknown institution"

    def _load_owner(self, session: Session, advisor_user_id: UUID | None) -> AppUser | None:
        if advisor_user_id is None:
            return None
        return session.get(AppUser, advisor_user_id)

    def _student_name(self, student: Student | None) -> str:
        if student is None:
            return "Unknown Student"
        parts = [student.preferred_name or student.first_name or "", student.last_name or ""]
        return " ".join(part for part in parts if part.strip()).strip() or "Unknown Student"

    def _student_identifier(self, student: Student | None) -> str:
        if student is None:
            return ""
        return student.external_student_id or str(student.id)

    def _population_for_student(self, student: Student) -> str:
        accepted_credits = self._to_float(student.accepted_credits, 0.0) or 0.0
        return "transfer" if accepted_credits > 0 else "first_year"

    def _default_template_items(self, population: str) -> list[dict]:
        shared = [
            {"code": "application_form", "label": "Application form", "required": True},
            {"code": "official_transcript", "label": "Official transcript", "required": True, "document_type": "transcript"},
            {"code": "residency_form", "label": "Residency form", "required": True},
            {"code": "fafsa", "label": "FAFSA", "required": True},
        ]
        if population == "transfer":
            return shared + [
                {"code": "college_transcript", "label": "College transcript", "required": True, "document_type": "transcript"},
                {"code": "personal_statement", "label": "Personal statement", "required": False},
            ]
        return shared + [
            {"code": "recommendation_letter", "label": "Recommendation letter", "required": False},
            {"code": "test_scores", "label": "Test scores", "required": False},
        ]

    def _estimate_fit_score(self, gpa: Decimal | float | int | None, accepted_credits: Decimal | float | int | None, parser_confidence: float | None) -> int:
        gpa_value = self._to_float(gpa, 0.0) or 0.0
        if gpa_value >= 3.5:
            return 92
        if gpa_value >= 3.0:
            return 84
        if gpa_value >= 2.5:
            return 72
        credits = self._to_float(accepted_credits, 0.0) or 0.0
        if credits >= 30:
            return 78
        if parser_confidence is not None:
            return max(55, min(90, int(parser_confidence * 100)))
        return 65

    def _estimate_deposit_likelihood(self, risk_level: str | None, gpa: Decimal | float | int | None, parser_confidence: float | None) -> int:
        risk = (risk_level or "").lower()
        if risk == "high":
            return 20
        base = self._estimate_fit_score(gpa, 0, parser_confidence) - 12
        if risk == "medium":
            base -= 10
        return max(10, min(90, base))

    def _is_stalled(self, student: Student) -> bool:
        reference = student.latest_activity_at or student.updated_at or student.created_at
        return bool(reference and datetime.now(timezone.utc) - reference > timedelta(days=7))

    def _relative_time(self, value: datetime | None) -> str:
        if value is None:
            return "Unknown"
        now = datetime.now(timezone.utc)
        delta = now - value
        minutes = int(delta.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes} minutes ago"
        hours = int(minutes // 60)
        if hours < 24:
            return f"{hours} hours ago"
        days = int(hours // 24)
        return f"{days} days ago"

    def _title_case(self, value: str | None) -> str:
        if not value:
            return ""
        return value.replace("_", " ").replace("-", " ").title()

    def _isoformat(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _to_float(self, value: Decimal | float | int | None, fallback: float | None = 0.0) -> float | None:
        if value is None:
            return fallback
        try:
            return round(float(value), 4)
        except Exception:
            return fallback

    def _to_decimal(self, value: float | None) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None
