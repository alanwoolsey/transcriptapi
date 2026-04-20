from __future__ import annotations

from datetime import datetime, timezone
import secrets
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AUTHZ_SCHEMA,
    AppUser,
    AuditEvent,
    AuthzRole,
    AuthzScopeGrant,
    AuthzSensitivityGrant,
    AuthzUserRoleAssignment,
    ChecklistTemplate,
    ChecklistTemplateItem,
    DecisionPacket,
    DocumentUpload,
    Student,
    StudentChecklist,
    StudentChecklistItem,
    StudentDecisionReadiness,
    StudentEnrollmentMilestone,
    StudentMeltScore,
    StudentPriorityScore,
    StudentYieldScore,
    TenantSettings,
    TenantUserMembership,
    Program,
    Transcript,
    TranscriptDemographics,
    TranscriptParseRun,
    TranscriptStudentMatch,
    TrustFlag,
    WorkflowCase,
)
from app.db.session import get_session_factory
from app.models.operations_models import (
    ActionResponse,
    AdminChecklistTemplateItem,
    AdminChecklistTemplatePayload,
    AdminChecklistTemplateRecord,
    AdminChecklistTemplatesResponse,
    AdminConfigPayload,
    AdminPermissionItem,
    AdminPermissionsResponse,
    AdminRoleItem,
    AdminRolesResponse,
    AdminScopeOptionsResponse,
    AdminUserCreateRequest,
    AdminUserItem,
    AdminUserReassignRequest,
    AdminUsersResponse,
    AdminUserUpdateRequest,
    DocumentQueueItem,
    DocumentsQueueResponse,
    HandoffItem,
    HandoffResponse,
    HandoffSummary,
    IncompleteQueueItem,
    IncompleteQueueResponse,
    MeltQueueItem,
    MeltQueueResponse,
    ReportingOverviewResponse,
    ReviewReadyItem,
    ReviewReadyResponse,
    SensitivityTierItem,
    SensitivityTiersResponse,
    SimpleUserRef,
    StudentMatchRef,
    YieldQueueItem,
    YieldQueueResponse,
)
from app.services.admissions_ops_service import AdmissionsOpsService
from app.services.auth_service import AuthService, CognitoAuthError
from app.services.rbac_service import (
    MEMBERSHIP_ROLE_FALLBACKS,
    RBACService,
    SENSITIVITY_ACADEMIC_RECORD,
    SENSITIVITY_BASIC_PROFILE,
    SENSITIVITY_NOTES,
    SENSITIVITY_RELEASED_DECISIONS,
    SENSITIVITY_TRANSCRIPT_IMAGES,
    SENSITIVITY_TRUST_FRAUD_FLAGS,
    STARTER_PERMISSIONS,
    STARTER_ROLES,
)


class OperationsService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory
        self.admissions_ops = AdmissionsOpsService(session_factory=self.session_factory)
        self.rbac_service = RBACService()
        self.auth_service = AuthService()

    def list_incomplete(
        self,
        tenant_id: UUID,
        *,
        view: str | None = None,
        q: str | None = None,
        owner_id: str | None = None,
        population: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> IncompleteQueueResponse:
        work = self.admissions_ops.get_work_items(
            tenant_id,
            section=None,
            population=population,
            owner=owner_id,
            priority=None,
            aging_bucket=None,
            q=q,
            limit=max(page_size * page, page_size),
            offset=0,
        )
        items: list[IncompleteQueueItem] = []
        for item in work.items:
            if item.section not in {"attention", "close"}:
                continue
            missing_items = [blocking.label for blocking in item.blockingItems if blocking.status == "missing"]
            mapped = IncompleteQueueItem(
                id=item.id,
                studentId=item.studentId,
                studentName=item.studentName,
                population=item.population,
                program=item.program,
                missingItemsCount=len(missing_items),
                missingItems=missing_items,
                completedItemsCount=item.checklistSummary.completedCount,
                totalRequired=item.checklistSummary.totalRequired,
                lastActivityAt=item.updatedAt,
                daysStalled=self._days_stalled(item.updatedAt),
                closestToComplete=item.checklistSummary.oneItemAway,
                assignedOwner=(SimpleUserRef(id=item.owner.id, name=item.owner.name) if item.owner else None),
                suggestedNextAction=item.suggestedAction.label,
                readinessState=(item.readiness or {}).get("state", "in_progress"),
                priorityScore=item.priorityScore,
            )
            if self._matches_incomplete_view(mapped, view):
                items.append(mapped)

        start = (page - 1) * page_size
        paged = items[start:start + page_size]
        return IncompleteQueueResponse(items=paged, page=page, pageSize=page_size, total=len(items))

    def list_review_ready(self, tenant_id: UUID, *, q: str | None = None) -> ReviewReadyResponse:
        work = self.admissions_ops.get_work_items(
            tenant_id,
            section="ready",
            population=None,
            owner=None,
            priority=None,
            aging_bucket=None,
            q=q,
            limit=200,
            offset=0,
        )
        items = [
            ReviewReadyItem(
                id=item.id,
                studentId=item.studentId,
                studentName=item.studentName,
                population=item.population,
                program=item.program,
                transferCredits=0,
                assignedReviewer=SimpleUserRef(id=item.owner.id, name=item.owner.name),
                daysWaiting=self._days_stalled(item.updatedAt),
                reviewSlaHours=24,
                completedItemsCount=item.checklistSummary.completedCount,
                totalRequired=item.checklistSummary.totalRequired,
            )
            for item in work.items
        ]
        return ReviewReadyResponse(items=items)

    def list_documents_queue(self, tenant_id: UUID, *, view: str | None = None) -> DocumentsQueueResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            rows = session.execute(
                select(DocumentUpload, Transcript, TranscriptDemographics, Student)
                .join(Transcript, Transcript.document_upload_id == DocumentUpload.id)
                .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
                .outerjoin(Student, Student.id == Transcript.student_id)
                .where(DocumentUpload.tenant_id == tenant_id)
                .order_by(DocumentUpload.uploaded_at.desc())
            ).all()
            items: list[DocumentQueueItem] = []
            for upload, transcript, demographics, student in rows:
                parse_run = session.execute(
                    select(TranscriptParseRun)
                    .where(TranscriptParseRun.tenant_id == tenant_id, TranscriptParseRun.transcript_id == transcript.id)
                    .order_by(TranscriptParseRun.started_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                match = session.execute(
                    select(TranscriptStudentMatch)
                    .where(TranscriptStudentMatch.tenant_id == tenant_id, TranscriptStudentMatch.transcript_id == transcript.id)
                    .order_by(TranscriptStudentMatch.decided_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                trust_flag = session.execute(
                    select(TrustFlag)
                    .where(TrustFlag.tenant_id == tenant_id, TrustFlag.transcript_id == transcript.id, TrustFlag.status.notin_(["resolved", "closed"]))
                    .order_by(TrustFlag.detected_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                status = self._document_status(upload, transcript, parse_run, match, trust_flag)
                if view and status != view:
                    continue
                items.append(
                    DocumentQueueItem(
                        id=str(upload.id),
                        documentType=self._title_case(transcript.document_type or "official_transcript"),
                        studentMatch=StudentMatchRef(
                            studentId=(str(student.id) if student else None),
                            studentName=self._student_name(student, demographics),
                        ),
                        confidence=self._to_float(transcript.parser_confidence, None),
                        uploadSource="Portal upload",
                        status=status,
                        trustFlag=bool(trust_flag or transcript.is_fraudulent),
                        receivedAt=self._iso(upload.uploaded_at),
                    )
                )
            return DocumentsQueueResponse(items=items)

    def confirm_document_match(self, tenant_id: UUID, document_id: str, student_id: str, actor_user_id: UUID | None) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            document, transcript = self._resolve_document(session, tenant_id, document_id)
            student = self._resolve_student(session, tenant_id, student_id)
            if student is None:
                return ActionResponse(success=False, status="not_found", detail="Student not found.")
            session.execute(
                select(TranscriptStudentMatch)
                .where(TranscriptStudentMatch.tenant_id == tenant_id, TranscriptStudentMatch.transcript_id == transcript.id, TranscriptStudentMatch.is_current.is_(True))
            ).scalars().all()
            for match in session.execute(
                select(TranscriptStudentMatch)
                .where(TranscriptStudentMatch.tenant_id == tenant_id, TranscriptStudentMatch.transcript_id == transcript.id, TranscriptStudentMatch.is_current.is_(True))
            ).scalars().all():
                match.is_current = False
            transcript.student_id = student.id
            transcript.matched_at = datetime.now(timezone.utc)
            transcript.matched_by = "user"
            document.upload_status = "indexed"
            session.add(
                TranscriptStudentMatch(
                    tenant_id=tenant_id,
                    transcript_id=transcript.id,
                    student_id=student.id,
                    match_status="confirmed",
                    match_score=1.0,
                    match_reason={"source": "manual_confirm"},
                    decided_by_user_id=actor_user_id,
                    decided_at=datetime.now(timezone.utc),
                    is_current=True,
                )
            )
            session.commit()
            return ActionResponse(status="confirmed", detail="Document matched to student.")

    def reject_document_match(self, tenant_id: UUID, document_id: str, actor_user_id: UUID | None) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            _, transcript = self._resolve_document(session, tenant_id, document_id)
            previous_student_id = transcript.student_id
            for match in session.execute(
                select(TranscriptStudentMatch)
                .where(TranscriptStudentMatch.tenant_id == tenant_id, TranscriptStudentMatch.transcript_id == transcript.id, TranscriptStudentMatch.is_current.is_(True))
            ).scalars().all():
                match.is_current = False

            if previous_student_id is not None:
                session.add(
                    TranscriptStudentMatch(
                        tenant_id=tenant_id,
                        transcript_id=transcript.id,
                        student_id=previous_student_id,
                        match_status="rejected",
                        match_score=0.0,
                        match_reason={"source": "manual_reject"},
                        decided_by_user_id=actor_user_id,
                        decided_at=datetime.now(timezone.utc),
                        is_current=True,
                    )
                )
            transcript.student_id = None
            transcript.matched_at = datetime.now(timezone.utc)
            transcript.matched_by = "user"
            session.commit()
            return ActionResponse(status="rejected", detail="Document match rejected.")

    def reprocess_document(self, tenant_id: UUID, document_id: str) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            document, transcript = self._resolve_document(session, tenant_id, document_id)
            parse_run = session.execute(
                select(TranscriptParseRun)
                .where(TranscriptParseRun.tenant_id == tenant_id, TranscriptParseRun.transcript_id == transcript.id)
                .order_by(TranscriptParseRun.started_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            transcript.status = "processing"
            document.upload_status = "processing"
            if parse_run is not None:
                parse_run.status = "processing"
                parse_run.error_message = None
                parse_run.completed_at = None
                parse_run.started_at = datetime.now(timezone.utc)
            session.commit()
            return ActionResponse(status="processing", detail="Document queued for reprocessing.")

    def index_document(self, tenant_id: UUID, document_id: str) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            document, _ = self._resolve_document(session, tenant_id, document_id)
            document.upload_status = "indexed"
            session.commit()
            return ActionResponse(status="indexed", detail="Document indexed.")

    def quarantine_document(self, tenant_id: UUID, document_id: str, actor_user_id: UUID | None) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            _, transcript = self._resolve_document(session, tenant_id, document_id)
            transcript.is_fraudulent = True
            session.add(
                TrustFlag(
                    tenant_id=tenant_id,
                    transcript_id=transcript.id,
                    student_id=transcript.student_id,
                    flag_type="manual_quarantine",
                    severity="high",
                    status="open",
                    reason="Document quarantined by reviewer.",
                    detected_by="user",
                    detected_at=datetime.now(timezone.utc),
                    resolved_by_user_id=actor_user_id,
                    resolved_at=None,
                    resolution_notes=None,
                )
            )
            session.commit()
            return ActionResponse(status="quarantined", detail="Document quarantined.")

    def release_document(self, tenant_id: UUID, document_id: str, actor_user_id: UUID | None) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            _, transcript = self._resolve_document(session, tenant_id, document_id)
            transcript.is_fraudulent = False
            for flag in session.execute(
                select(TrustFlag)
                .where(TrustFlag.tenant_id == tenant_id, TrustFlag.transcript_id == transcript.id, TrustFlag.status.notin_(["resolved", "closed"]))
            ).scalars().all():
                flag.status = "resolved"
                flag.resolved_by_user_id = actor_user_id
                flag.resolved_at = datetime.now(timezone.utc)
                flag.resolution_notes = "Released by reviewer."
            session.commit()
            return ActionResponse(status="released", detail="Document released.")

    def list_yield(self, tenant_id: UUID, *, view: str | None = None, q: str | None = None) -> YieldQueueResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            rows = session.execute(
                select(Student, StudentYieldScore, AppUser)
                .outerjoin(StudentYieldScore, StudentYieldScore.student_id == Student.id)
                .outerjoin(AppUser, AppUser.id == Student.advisor_user_id)
                .where(Student.tenant_id == tenant_id)
                .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc())
            ).all()
            items: list[YieldQueueItem] = []
            for student, score, advisor in rows:
                yield_score = int(score.score) if score else 0
                deposit_status = "deposited" if yield_score >= 80 else "not_deposited"
                program = self._program_name(session, student)
                next_step = self._yield_next_step(session, tenant_id, student.id)
                item = YieldQueueItem(
                    studentId=str(student.id),
                    studentName=self._student_name(student, None),
                    program=program,
                    admitDate=self._iso(student.created_at),
                    depositStatus=deposit_status,
                    yieldScore=yield_score,
                    lastActivityAt=self._iso(student.latest_activity_at or student.updated_at),
                    milestoneCompletion=self._milestone_completion(session, tenant_id, student.id),
                    assignedCounselor=(SimpleUserRef(id=str(advisor.id), name=advisor.display_name) if advisor else None),
                    nextStep=next_step,
                )
                if self._matches_yield_view(item, view, student=student, next_step=next_step) and self._matches_yield_q(item, q):
                    items.append(item)
            return YieldQueueResponse(items=items)

    def list_melt(self, tenant_id: UUID, *, view: str | None = None, q: str | None = None) -> MeltQueueResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            rows = session.execute(
                select(Student, StudentMeltScore, AppUser)
                .outerjoin(StudentMeltScore, StudentMeltScore.student_id == Student.id)
                .outerjoin(AppUser, AppUser.id == Student.advisor_user_id)
                .where(Student.tenant_id == tenant_id)
                .order_by(Student.latest_activity_at.desc().nullslast(), Student.created_at.desc())
            ).all()
            items: list[MeltQueueItem] = []
            for student, score, advisor in rows:
                missing = self._missing_milestones(session, tenant_id, student.id)
                program = self._program_name(session, student)
                item = MeltQueueItem(
                    studentId=str(student.id),
                    studentName=self._student_name(student, None),
                    program=program,
                    depositDate=self._iso(student.created_at),
                    meltRisk=int(score.score) if score else 0,
                    missingMilestones=missing,
                    lastOutreachAt=self._iso(student.latest_activity_at or student.updated_at),
                    owner=(SimpleUserRef(id=str(advisor.id), name=advisor.display_name) if advisor else None),
                )
                if self._matches_melt_view(item, view) and self._matches_melt_q(item, q):
                    items.append(item)
            return MeltQueueResponse(items=items)

    def get_handoff(self, tenant_id: UUID) -> HandoffResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            cases = session.execute(
                select(WorkflowCase, Student)
                .outerjoin(Student, Student.id == WorkflowCase.student_id)
                .where(
                    WorkflowCase.tenant_id == tenant_id,
                    or_(
                        WorkflowCase.queue_name.ilike("%connector%"),
                        WorkflowCase.queue_name.ilike("%sis%"),
                        WorkflowCase.queue_name.ilike("%financial%"),
                        WorkflowCase.queue_name.ilike("%orientation%"),
                    ),
                )
                .order_by(WorkflowCase.updated_at.desc())
            ).all()
            items: list[HandoffItem] = []
            counts = {"healthy": 0, "failed": 0, "blocked": 0}
            for workflow_case, student in cases:
                status = self._handoff_status(workflow_case.status)
                if status in counts:
                    counts[status] += 1
                items.append(
                    HandoffItem(
                        studentId=(str(student.id) if student else ""),
                        studentName=self._student_name(student, None),
                        office=self._office_from_queue(workflow_case.queue_name),
                        status=status,
                        lastAttemptAt=self._iso(workflow_case.updated_at or workflow_case.opened_at),
                        error=(workflow_case.reason if status in {"failed", "blocked"} else None),
                    )
                )
            return HandoffResponse(summary=HandoffSummary(**counts), items=items)

    def retry_handoff(self, tenant_id: UUID, student_id: str) -> ActionResponse:
        return self._handoff_action(tenant_id, student_id, "retry_requested")

    def acknowledge_handoff(self, tenant_id: UUID, student_id: str) -> ActionResponse:
        return self._handoff_action(tenant_id, student_id, "acknowledged")

    def get_reporting_overview(self, tenant_id: UUID) -> ReportingOverviewResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            total_checklists = session.execute(
                select(func.count()).select_from(StudentChecklist).where(StudentChecklist.tenant_id == tenant_id)
            ).scalar_one()
            completed_checklists = session.execute(
                select(func.count()).select_from(StudentChecklist).where(StudentChecklist.tenant_id == tenant_id, StudentChecklist.status == "complete")
            ).scalar_one()
            transcripts_total = session.execute(
                select(func.count()).select_from(Transcript).where(Transcript.tenant_id == tenant_id)
            ).scalar_one()
            indexed_total = session.execute(
                select(func.count()).select_from(DocumentUpload).where(DocumentUpload.tenant_id == tenant_id, DocumentUpload.upload_status == "indexed")
            ).scalar_one()
            decisions_total = session.execute(
                select(func.count()).select_from(DecisionPacket).where(DecisionPacket.tenant_id == tenant_id)
            ).scalar_one()
            ready_decisions = session.execute(
                select(func.count()).select_from(DecisionPacket).where(DecisionPacket.tenant_id == tenant_id, DecisionPacket.status.in_(["Approved", "Released"]))
            ).scalar_one()
            yield_total = session.execute(
                select(func.count()).select_from(StudentYieldScore).where(StudentYieldScore.tenant_id == tenant_id)
            ).scalar_one()
            deposit_total = session.execute(
                select(func.count()).select_from(StudentYieldScore).where(StudentYieldScore.tenant_id == tenant_id, StudentYieldScore.score >= 80)
            ).scalar_one()
            melt_total = session.execute(
                select(func.count()).select_from(StudentMeltScore).where(StudentMeltScore.tenant_id == tenant_id)
            ).scalar_one()
            melt_risk_total = session.execute(
                select(func.count()).select_from(StudentMeltScore).where(StudentMeltScore.tenant_id == tenant_id, StudentMeltScore.score >= 50)
            ).scalar_one()
            return ReportingOverviewResponse(
                incompleteToCompleteConversion=self._ratio(completed_checklists, total_checklists),
                averageDaysToComplete=11.4,
                averageDaysCompleteToDecision=3.2,
                autoIndexSuccessRate=self._ratio(indexed_total, transcripts_total),
                admitToDepositConversion=self._ratio(deposit_total, yield_total),
                meltRate=self._ratio(melt_risk_total, melt_total),
            )

    def get_admin_users(
        self,
        tenant_id: UUID,
        *,
        q: str | None = None,
        role: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> AdminUsersResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            self.rbac_service.sync_seed_data(session)
            rows = session.execute(
                select(AppUser, TenantUserMembership)
                .join(TenantUserMembership, TenantUserMembership.user_id == AppUser.id)
                .where(TenantUserMembership.tenant_id == tenant_id, AppUser.tenant_id == tenant_id)
                .order_by(AppUser.display_name.asc(), AppUser.created_at.asc())
            ).all()
            filtered: list[AdminUserItem] = []
            for user, membership in rows:
                item = self._serialize_admin_user(session, tenant_id, user, membership)
                if q and q.strip():
                    haystack = " ".join([item.displayName, item.email or "", item.baseRole or "", " ".join(item.roles)]).lower()
                    if q.strip().lower() not in haystack:
                        continue
                if role and role not in item.roles and role != item.baseRole:
                    continue
                if status and item.status != status:
                    continue
                filtered.append(item)
            start = (page - 1) * page_size
            return AdminUsersResponse(items=filtered[start:start + page_size], page=page, pageSize=page_size, total=len(filtered))

    def create_admin_user(self, tenant_id: UUID, actor_user_id: UUID, payload: AdminUserCreateRequest) -> AdminUserItem:
        temporary_password = self._generate_temporary_password()
        session_factory = self.session_factory()
        with session_factory() as session:
            self.rbac_service.sync_seed_data(session)
            existing = session.execute(select(AppUser).where(AppUser.email == payload.email).limit(1)).scalar_one_or_none()
            if existing is not None:
                raise ValueError("User with this email already exists.")
        try:
            self.auth_service.admin_create_user(
                email=payload.email.strip().lower(),
                display_name=payload.displayName.strip(),
                temporary_password=temporary_password,
                send_invite=payload.sendInvite,
            )
        except CognitoAuthError as exc:
            raise ValueError(exc.detail) from exc
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        with session_factory() as session:
            self.rbac_service.sync_seed_data(session)
            user = AppUser(
                tenant_id=tenant_id,
                email=payload.email.strip().lower(),
                display_name=payload.displayName.strip(),
                cognito_sub=self._fetch_cognito_sub(payload.email.strip().lower()),
                identity_provider="cognito",
                is_active=not payload.sendInvite,
            )
            session.add(user)
            session.flush()
            membership = TenantUserMembership(
                tenant_id=tenant_id,
                user_id=user.id,
                role=payload.baseRole or "read_only",
                status=("invited" if payload.sendInvite else "active"),
                is_default=True,
            )
            session.add(membership)
            self._replace_user_rbac(session, tenant_id, user.id, payload.roles, payload.sensitivityTiers, payload.scopes)
            self._write_admin_audit(
                session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="admin_user_created",
                target_user_id=user.id,
                before={},
                after={"email": user.email, "displayName": user.display_name, "status": membership.status},
            )
            if payload.sendInvite:
                self._write_admin_audit(
                    session,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    action="admin_user_invited",
                    target_user_id=user.id,
                    before={},
                    after={"email": user.email},
                )
            session.commit()
            created = self._serialize_admin_user(session, tenant_id, user, membership)
            created.tempPassword = temporary_password
            return created

    def get_admin_user(self, tenant_id: UUID, user_id: str) -> AdminUserItem | None:
        session_factory = self.session_factory()
        with session_factory() as session:
            row = self._load_admin_user_row(session, tenant_id, user_id)
            if row is None:
                return None
            user, membership = row
            return self._serialize_admin_user(session, tenant_id, user, membership)

    def update_admin_user(self, tenant_id: UUID, actor_user_id: UUID, user_id: str, payload: AdminUserUpdateRequest) -> AdminUserItem | None:
        session_factory = self.session_factory()
        with session_factory() as session:
            row = self._load_admin_user_row(session, tenant_id, user_id)
            if row is None:
                return None
            user, membership = row
            current_email = user.email or ""
            before = self._serialize_admin_user(session, tenant_id, user, membership).model_dump(mode="json")
            if payload.displayName is not None:
                user.display_name = payload.displayName.strip()
            if payload.baseRole is not None:
                membership.role = payload.baseRole
            if payload.status is not None:
                normalized_status = payload.status.strip().lower()
                membership.status = normalized_status
                user.is_active = normalized_status == "active"
            roles = payload.roles if payload.roles is not None else before["roles"]
            tiers = payload.sensitivityTiers if payload.sensitivityTiers is not None else before["sensitivityTiers"]
            scopes = payload.scopes if payload.scopes is not None else before["scopes"]
            self._replace_user_rbac(session, tenant_id, user.id, roles, tiers, scopes)
            if user.email:
                try:
                    self.auth_service.admin_update_user(
                        current_email=current_email,
                        email=user.email,
                        display_name=user.display_name,
                    )
                except CognitoAuthError as exc:
                    raise ValueError(exc.detail) from exc
                except RuntimeError as exc:
                    raise ValueError(str(exc)) from exc
            after_item = self._serialize_admin_user(session, tenant_id, user, membership)
            self._write_admin_audit(
                session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="admin_user_updated",
                target_user_id=user.id,
                before=before,
                after=after_item.model_dump(mode="json"),
            )
            session.commit()
            return after_item

    def deactivate_admin_user(self, tenant_id: UUID, actor_user_id: UUID, current_user_id: UUID, user_id: str) -> ActionResponse:
        return self._change_admin_user_status(tenant_id, actor_user_id, current_user_id, user_id, "inactive")

    def reactivate_admin_user(self, tenant_id: UUID, actor_user_id: UUID, user_id: str) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            row = self._load_admin_user_row(session, tenant_id, user_id)
            if row is None:
                return ActionResponse(success=False, status="not_found", detail="User not found.")
            user, membership = row
            before = self._serialize_admin_user(session, tenant_id, user, membership).model_dump(mode="json")
            user.is_active = True
            membership.status = "active"
            after = self._serialize_admin_user(session, tenant_id, user, membership).model_dump(mode="json")
            self._write_admin_audit(session, tenant_id, actor_user_id, "admin_user_reactivated", user.id, before, after)
            session.commit()
            return ActionResponse(status="active", detail="User reactivated.")

    def send_admin_user_invite(self, tenant_id: UUID, actor_user_id: UUID, user_id: str) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            row = self._load_admin_user_row(session, tenant_id, user_id)
            if row is None:
                return ActionResponse(success=False, status="not_found", detail="User not found.")
            user, membership = row
            if not user.email:
                return ActionResponse(success=False, status="validation_error", detail="User email is required.")
            try:
                self.auth_service.admin_resend_invite(email=user.email)
            except CognitoAuthError as exc:
                return ActionResponse(success=False, status="cognito_error", detail=exc.detail)
            except RuntimeError as exc:
                return ActionResponse(success=False, status="configuration_error", detail=str(exc))
            before = self._serialize_admin_user(session, tenant_id, user, membership).model_dump(mode="json")
            membership.status = "invited"
            user.is_active = False
            self._write_admin_audit(
                session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="admin_user_invited",
                target_user_id=user.id,
                before=before,
                after=self._serialize_admin_user(session, tenant_id, user, membership).model_dump(mode="json"),
            )
            session.commit()
            return ActionResponse(status="invited", detail="Invite sent.")

    def reset_admin_user_password(self, tenant_id: UUID, actor_user_id: UUID, user_id: str) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            row = self._load_admin_user_row(session, tenant_id, user_id)
            if row is None:
                return ActionResponse(success=False, status="not_found", detail="User not found.")
            user, membership = row
            if not user.email:
                return ActionResponse(success=False, status="validation_error", detail="User email is required.")
            try:
                self.auth_service.admin_reset_user_password(email=user.email)
            except CognitoAuthError as exc:
                return ActionResponse(success=False, status="cognito_error", detail=exc.detail)
            except RuntimeError as exc:
                return ActionResponse(success=False, status="configuration_error", detail=str(exc))
            self._write_admin_audit(
                session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="admin_user_reset_password",
                target_user_id=user.id,
                before=self._serialize_admin_user(session, tenant_id, user, membership).model_dump(mode="json"),
                after={"status": membership.status},
            )
            session.commit()
            return ActionResponse(status="password_reset_requested", detail="Password reset requested.")

    def reassign_admin_user_objects(self, tenant_id: UUID, actor_user_id: UUID, user_id: str, payload: AdminUserReassignRequest) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            source_row = self._load_admin_user_row(session, tenant_id, user_id)
            target_row = self._load_admin_user_row(session, tenant_id, payload.targetUserId)
            if source_row is None or target_row is None:
                return ActionResponse(success=False, status="not_found", detail="Source or target user not found.")
            source_user, _ = source_row
            target_user, _ = target_row
            counts: dict[str, int] = {}
            if "students" in payload.objects:
                counts["students"] = session.query(Student).filter(Student.tenant_id == tenant_id, Student.advisor_user_id == source_user.id).update({"advisor_user_id": target_user.id})
            if "work_items" in payload.objects:
                counts["work_items"] = session.query(WorkflowCase).filter(WorkflowCase.tenant_id == tenant_id, WorkflowCase.owner_user_id == source_user.id).update({"owner_user_id": target_user.id})
            if "trust_cases" in payload.objects:
                counts["trust_cases"] = session.query(TrustFlag).filter(TrustFlag.tenant_id == tenant_id, TrustFlag.resolved_by_user_id == source_user.id).update({"resolved_by_user_id": target_user.id})
            if "decision_packets" in payload.objects:
                counts["decision_packets"] = session.query(DecisionPacket).filter(DecisionPacket.tenant_id == tenant_id, DecisionPacket.assigned_to_user_id == source_user.id).update({"assigned_to_user_id": target_user.id})
            self._write_admin_audit(
                session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="admin_user_reassigned",
                target_user_id=source_user.id,
                before={"sourceUserId": str(source_user.id)},
                after={"targetUserId": str(target_user.id), "counts": counts, "objects": payload.objects},
            )
            session.commit()
            return ActionResponse(status="reassigned", detail="Ownership reassigned.")

    def get_admin_roles(self) -> AdminRolesResponse:
        items = [
            AdminRoleItem(key=key, label=str(defn["name"]), description=f"System role: {defn['name']}", active=True)
            for key, defn in STARTER_ROLES.items()
        ]
        return AdminRolesResponse(items=items)

    def get_admin_permissions(self) -> AdminPermissionsResponse:
        return AdminPermissionsResponse(
            items=[
                AdminPermissionItem(
                    key=permission["code"],
                    label=permission["label"],
                    description=permission["label"],
                    category=permission["category"],
                )
                for permission in STARTER_PERMISSIONS
            ]
        )

    def get_sensitivity_tiers(self) -> SensitivityTiersResponse:
        items = [
            SensitivityTierItem(key=SENSITIVITY_BASIC_PROFILE, label="Basic Profile"),
            SensitivityTierItem(key=SENSITIVITY_ACADEMIC_RECORD, label="Academic Record"),
            SensitivityTierItem(key=SENSITIVITY_TRANSCRIPT_IMAGES, label="Transcript Images"),
            SensitivityTierItem(key=SENSITIVITY_TRUST_FRAUD_FLAGS, label="Trust Fraud Flags"),
            SensitivityTierItem(key=SENSITIVITY_NOTES, label="Notes"),
            SensitivityTierItem(key=SENSITIVITY_RELEASED_DECISIONS, label="Released Decisions"),
        ]
        return SensitivityTiersResponse(items=items)

    def get_admin_scope_options(self, tenant_id: UUID) -> AdminScopeOptionsResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            programs = session.execute(select(Program.name).where(Program.tenant_id == tenant_id).order_by(Program.name.asc())).scalars().all()
            stages = session.execute(select(Student.current_stage).where(Student.tenant_id == tenant_id).distinct().order_by(Student.current_stage.asc())).scalars().all()
            territories = session.execute(
                select(Student.state).where(Student.tenant_id == tenant_id, Student.state.is_not(None)).distinct().order_by(Student.state.asc())
            ).scalars().all()
            configured = self._ensure_tenant_settings(session, tenant_id).settings_json.get("scope_options", {})
            campuses = configured.get("campuses") or ["*", "main"]
            return AdminScopeOptionsResponse(
                campuses=sorted({*campuses}),
                territories=sorted({"*", *[value for value in territories if value]}),
                programs=sorted({"*", *[value for value in programs if value]}),
                studentPopulations=["*", "first_year", "transfer"],
                stages=sorted({"*", *[value for value in stages if value]}),
            )

    def get_admin_checklist_templates(self, tenant_id: UUID) -> AdminChecklistTemplatesResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            templates = session.execute(
                select(ChecklistTemplate)
                .where(ChecklistTemplate.tenant_id == tenant_id)
                .order_by(ChecklistTemplate.created_at.desc())
            ).scalars().all()
            items: list[AdminChecklistTemplateRecord] = []
            for template in templates:
                template_items = session.execute(
                    select(ChecklistTemplateItem)
                    .where(ChecklistTemplateItem.template_id == template.id)
                    .order_by(ChecklistTemplateItem.sort_order.asc())
                ).scalars().all()
                items.append(
                    AdminChecklistTemplateRecord(
                        id=str(template.id),
                        name=template.name,
                        population=template.population,
                        active=bool(template.active),
                        version=template.version,
                        items=[
                            AdminChecklistTemplateItem(
                                code=item.code,
                                label=item.label,
                                required=bool(item.required),
                                sortOrder=item.sort_order,
                                documentType=item.document_type,
                                reviewRequiredDefault=bool(item.review_required_default),
                            )
                            for item in template_items
                        ],
                    )
                )
            return AdminChecklistTemplatesResponse(items=items)

    def create_admin_checklist_template(self, tenant_id: UUID, payload: AdminChecklistTemplatePayload) -> AdminChecklistTemplateRecord:
        session_factory = self.session_factory()
        with session_factory() as session:
            template = ChecklistTemplate(
                tenant_id=tenant_id,
                name=payload.name,
                population=payload.population,
                active=payload.active,
                version=1,
            )
            session.add(template)
            session.flush()
            for index, item in enumerate(payload.items, start=1):
                session.add(
                    ChecklistTemplateItem(
                        template_id=template.id,
                        code=item.code,
                        label=item.label,
                        required=item.required,
                        sort_order=item.sortOrder or index,
                        document_type=item.documentType,
                        review_required_default=item.reviewRequiredDefault,
                        active=True,
                    )
                )
            session.commit()
            return self.get_admin_checklist_templates(tenant_id).items[0]

    def get_routing_rules(self, tenant_id: UUID) -> AdminConfigPayload:
        return self._get_tenant_config_list(tenant_id, "routing_rules")

    def save_routing_rules(self, tenant_id: UUID, payload: AdminConfigPayload) -> AdminConfigPayload:
        return self._save_tenant_config_list(tenant_id, "routing_rules", payload)

    def get_decision_rules(self, tenant_id: UUID) -> AdminConfigPayload:
        return self._get_tenant_config_list(tenant_id, "decision_rules")

    def save_decision_rules(self, tenant_id: UUID, payload: AdminConfigPayload) -> AdminConfigPayload:
        return self._save_tenant_config_list(tenant_id, "decision_rules", payload)

    def get_sensitivity_settings(self, tenant_id: UUID) -> AdminConfigPayload:
        return self._get_tenant_config_list(tenant_id, "sensitivity_settings")

    def save_sensitivity_settings(self, tenant_id: UUID, payload: AdminConfigPayload) -> AdminConfigPayload:
        return self._save_tenant_config_list(tenant_id, "sensitivity_settings", payload)

    def _serialize_admin_user(self, session: Session, tenant_id: UUID, user: AppUser, membership: TenantUserMembership) -> AdminUserItem:
        profile = self.rbac_service.resolve_profile(
            session,
            tenant_id=tenant_id,
            user_id=user.id,
            membership_role=membership.role,
        )
        last_login_at = session.execute(
            select(AuditEvent.occurred_at)
            .where(AuditEvent.tenant_id == tenant_id, AuditEvent.actor_user_id == user.id)
            .order_by(AuditEvent.occurred_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return AdminUserItem(
            userId=str(user.id),
            email=user.email,
            displayName=user.display_name,
            status=self._admin_user_status(user, membership),
            baseRole=membership.role,
            roles=sorted(profile.roles),
            permissions=sorted(profile.permissions),
            sensitivityTiers=sorted(profile.sensitivity_tiers),
            scopes={
                "campuses": sorted(profile.scopes.get("campus", set())),
                "territories": sorted(profile.scopes.get("territory", set())),
                "programs": sorted(profile.scopes.get("program", set())),
                "studentPopulations": sorted(profile.scopes.get("student_population", set())),
                "stages": sorted(profile.scopes.get("stage", set())),
            },
            lastLoginAt=self._iso(last_login_at),
            createdAt=self._iso(user.created_at),
            updatedAt=self._iso(user.updated_at),
        )

    def _replace_user_rbac(
        self,
        session: Session,
        tenant_id: UUID,
        user_id: UUID,
        roles: list[str] | tuple[str, ...],
        tiers: list[str] | tuple[str, ...],
        scopes,
    ) -> None:
        normalized_roles = [role for role in roles if role]
        normalized_tiers = [tier for tier in tiers if tier]
        session.execute(delete(AuthzUserRoleAssignment).where(AuthzUserRoleAssignment.tenant_id == tenant_id, AuthzUserRoleAssignment.user_id == user_id))
        session.execute(delete(AuthzSensitivityGrant).where(AuthzSensitivityGrant.tenant_id == tenant_id, AuthzSensitivityGrant.user_id == user_id))
        session.execute(delete(AuthzScopeGrant).where(AuthzScopeGrant.tenant_id == tenant_id, AuthzScopeGrant.user_id == user_id))
        if normalized_roles:
            role_rows = session.execute(select(AuthzRole).where(AuthzRole.system_key.in_(normalized_roles))).scalars().all()
            for role in role_rows:
                session.add(AuthzUserRoleAssignment(tenant_id=tenant_id, user_id=user_id, role_id=role.id, active=True))
        for tier in normalized_tiers:
            session.add(AuthzSensitivityGrant(tenant_id=tenant_id, user_id=user_id, sensitivity_tier=tier, active=True))
        scope_map = scopes.model_dump() if hasattr(scopes, "model_dump") else dict(scopes or {})
        scope_aliases = {
            "campuses": "campus",
            "territories": "territory",
            "programs": "program",
            "studentPopulations": "student_population",
            "stages": "stage",
        }
        for field_name, scope_type in scope_aliases.items():
            for value in scope_map.get(field_name, []) or []:
                session.add(
                    AuthzScopeGrant(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        role_assignment_id=None,
                        scope_type=scope_type,
                        scope_value=value,
                        active=True,
                    )
                )

    def _write_admin_audit(
        self,
        session: Session,
        tenant_id: UUID,
        actor_user_id: UUID,
        action: str,
        target_user_id: UUID,
        before: dict,
        after: dict,
    ) -> None:
        session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                entity_type="admin_user",
                entity_id=target_user_id,
                category="Admin",
                action=action,
                success=True,
                error_message=None,
                payload_json={"before": before, "after": after},
                correlation_id=None,
                source="AdminUsers",
                occurred_at=datetime.now(timezone.utc),
            )
        )

    def _load_admin_user_row(self, session: Session, tenant_id: UUID, user_id: str) -> tuple[AppUser, TenantUserMembership] | None:
        try:
            resolved_user_id = UUID(user_id)
        except ValueError:
            return None
        row = session.execute(
            select(AppUser, TenantUserMembership)
            .join(TenantUserMembership, TenantUserMembership.user_id == AppUser.id)
            .where(TenantUserMembership.tenant_id == tenant_id, AppUser.tenant_id == tenant_id, AppUser.id == resolved_user_id)
            .limit(1)
        ).one_or_none()
        return row

    def _change_admin_user_status(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        current_user_id: UUID,
        user_id: str,
        new_status: str,
    ) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            row = self._load_admin_user_row(session, tenant_id, user_id)
            if row is None:
                return ActionResponse(success=False, status="not_found", detail="User not found.")
            user, membership = row
            if user.id == current_user_id and new_status != "active":
                return ActionResponse(success=False, status="forbidden", detail="You cannot deactivate yourself.")
            if new_status != "active" and self._is_last_admin(session, tenant_id, user.id):
                return ActionResponse(success=False, status="forbidden", detail="Cannot deactivate the last admin user.")
            before = self._serialize_admin_user(session, tenant_id, user, membership).model_dump(mode="json")
            membership.status = new_status
            user.is_active = new_status == "active"
            after = self._serialize_admin_user(session, tenant_id, user, membership).model_dump(mode="json")
            self._write_admin_audit(session, tenant_id, actor_user_id, "admin_user_deactivated", user.id, before, after)
            session.commit()
            return ActionResponse(status=new_status, detail="User status updated.")

    def _is_last_admin(self, session: Session, tenant_id: UUID, candidate_user_id: UUID) -> bool:
        rows = session.execute(
            select(TenantUserMembership, AppUser)
            .join(AppUser, AppUser.id == TenantUserMembership.user_id)
            .where(
                TenantUserMembership.tenant_id == tenant_id,
                AppUser.tenant_id == tenant_id,
                TenantUserMembership.status == "active",
                AppUser.is_active.is_(True),
            )
        ).all()
        admin_count = 0
        for membership, _user in rows:
            if membership.role in {"director", "decision_releaser_director"}:
                admin_count += 1
            else:
                fallback = MEMBERSHIP_ROLE_FALLBACKS.get((membership.role or "").strip().lower())
                if fallback == "decision_releaser_director":
                    admin_count += 1
        if admin_count != 1:
            return False
        return any(membership.user_id == candidate_user_id for membership, _user in rows if membership.role in {"director", "decision_releaser_director"} or MEMBERSHIP_ROLE_FALLBACKS.get((membership.role or "").strip().lower()) == "decision_releaser_director")

    def _get_tenant_config_list(self, tenant_id: UUID, key: str) -> AdminConfigPayload:
        session_factory = self.session_factory()
        with session_factory() as session:
            settings_row = self._ensure_tenant_settings(session, tenant_id)
            return AdminConfigPayload(items=list(settings_row.settings_json.get(key) or []))

    def _save_tenant_config_list(self, tenant_id: UUID, key: str, payload: AdminConfigPayload) -> AdminConfigPayload:
        session_factory = self.session_factory()
        with session_factory() as session:
            settings_row = self._ensure_tenant_settings(session, tenant_id)
            settings_json = dict(settings_row.settings_json or {})
            settings_json[key] = payload.items
            settings_row.settings_json = settings_json
            session.commit()
            return AdminConfigPayload(items=payload.items)

    def _ensure_tenant_settings(self, session: Session, tenant_id: UUID) -> TenantSettings:
        settings_row = session.execute(
            select(TenantSettings).where(TenantSettings.tenant_id == tenant_id).limit(1)
        ).scalar_one_or_none()
        if settings_row is not None:
            return settings_row
        settings_row = TenantSettings(tenant_id=tenant_id, settings_json={})
        session.add(settings_row)
        session.flush()
        return settings_row

    def _handoff_action(self, tenant_id: UUID, student_id: str, action: str) -> ActionResponse:
        session_factory = self.session_factory()
        with session_factory() as session:
            student = self._resolve_student(session, tenant_id, student_id)
            if student is None:
                return ActionResponse(success=False, status="not_found", detail="Student not found.")
            session.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    actor_user_id=None,
                    entity_type="student",
                    entity_id=student.id,
                    category="Integration",
                    action=action,
                    success=True,
                    error_message=None,
                    payload_json={},
                    correlation_id=None,
                    source="Integrations",
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            return ActionResponse(status=action, detail=f"Handoff {action.replace('_', ' ')}.")

    def _resolve_document(self, session: Session, tenant_id: UUID, document_id: str) -> tuple[DocumentUpload, Transcript]:
        document = session.execute(
            select(DocumentUpload).where(DocumentUpload.tenant_id == tenant_id, DocumentUpload.id == UUID(document_id)).limit(1)
        ).scalar_one()
        transcript = session.execute(
            select(Transcript).where(Transcript.tenant_id == tenant_id, Transcript.document_upload_id == document.id).limit(1)
        ).scalar_one()
        return document, transcript

    def _resolve_student(self, session: Session, tenant_id: UUID, student_id: str) -> Student | None:
        stmt = select(Student).where(Student.tenant_id == tenant_id)
        try:
            stmt = stmt.where(Student.id == UUID(student_id))
        except ValueError:
            stmt = stmt.where(Student.external_student_id == student_id)
        return session.execute(stmt.limit(1)).scalar_one_or_none()

    def _milestone_completion(self, session: Session, tenant_id: UUID, student_id: UUID) -> float:
        total = session.execute(
            select(func.count()).select_from(StudentEnrollmentMilestone).where(StudentEnrollmentMilestone.tenant_id == tenant_id, StudentEnrollmentMilestone.student_id == student_id)
        ).scalar_one()
        if not total:
            return 0.0
        completed = session.execute(
            select(func.count()).select_from(StudentEnrollmentMilestone).where(
                StudentEnrollmentMilestone.tenant_id == tenant_id,
                StudentEnrollmentMilestone.student_id == student_id,
                StudentEnrollmentMilestone.status == "complete",
            )
        ).scalar_one()
        return round(completed / total, 2)

    def _missing_milestones(self, session: Session, tenant_id: UUID, student_id: UUID) -> list[str]:
        rows = session.execute(
            select(StudentEnrollmentMilestone).where(
                StudentEnrollmentMilestone.tenant_id == tenant_id,
                StudentEnrollmentMilestone.student_id == student_id,
                StudentEnrollmentMilestone.status != "complete",
            )
        ).scalars().all()
        return [row.milestone_label for row in rows]

    def _yield_next_step(self, session: Session, tenant_id: UUID, student_id: UUID) -> str | None:
        missing = self._missing_milestones(session, tenant_id, student_id)
        if missing:
            return f"Complete {missing[0]}"
        return None

    def _document_status(
        self,
        upload: DocumentUpload,
        transcript: Transcript,
        parse_run: TranscriptParseRun | None,
        match: TranscriptStudentMatch | None,
        trust_flag: TrustFlag | None,
    ) -> str:
        if trust_flag or transcript.is_fraudulent:
            return "quarantined"
        if parse_run and parse_run.status == "failed":
            return "processing_failed"
        if match and match.match_status in {"rejected", "needs_review", "unresolved"}:
            return "needs_human_review"
        if match and match.match_status in {"confirmed", "matched", "auto_completed"}:
            return "auto_matched"
        if upload.upload_status != "indexed":
            return "received_not_indexed"
        return "indexed"

    def _matches_incomplete_view(self, item: IncompleteQueueItem, view: str | None) -> bool:
        if not view:
            return True
        if view == "submitted_missing_items":
            return item.missingItemsCount > 0
        if view == "nearly_complete":
            return item.closestToComplete
        if view == "aging":
            return item.daysStalled >= 7
        if view == "missing_transcript":
            return any("transcript" in missing.lower() for missing in item.missingItems)
        if view == "missing_residency":
            return any("residency" in missing.lower() for missing in item.missingItems)
        if view == "missing_fafsa":
            return any("fafsa" in missing.lower() for missing in item.missingItems)
        return True

    def _matches_yield_view(self, item: YieldQueueItem, view: str | None, *, student: Student, next_step: str | None) -> bool:
        if not view:
            return True
        if view == "newly_admitted":
            return self._days_stalled(item.admitDate) <= 7
        if view == "high_likelihood":
            return item.yieldScore >= 70
        if view == "high_value_transfer":
            return (self._to_float(student.accepted_credits, 0.0) or 0.0) > 0 and item.yieldScore >= 60
        if view == "scholarship_sensitive":
            return bool(next_step and "scholarship" in next_step.lower())
        if view == "missing_next_step":
            return bool(next_step)
        if view == "no_recent_activity":
            return self._days_stalled(item.lastActivityAt) >= 7
        return True

    def _matches_melt_view(self, item: MeltQueueItem, view: str | None) -> bool:
        if not view:
            return True
        if view == "all_clear":
            return item.meltRisk < 50 and not item.missingMilestones
        if view == "at_risk":
            return item.meltRisk >= 50
        if view == "missing_fafsa":
            return any("fafsa" in entry.lower() for entry in item.missingMilestones)
        if view == "missing_orientation":
            return any("orientation" in entry.lower() for entry in item.missingMilestones)
        if view == "missing_final_transcript":
            return any("final transcript" in entry.lower() for entry in item.missingMilestones)
        if view == "registration_incomplete":
            return any("registration" in entry.lower() for entry in item.missingMilestones)
        return True

    def _matches_yield_q(self, item: YieldQueueItem, q: str | None) -> bool:
        if not q or not q.strip():
            return True
        needle = q.strip().lower()
        haystack = " ".join(filter(None, [item.studentName, item.program, item.nextStep or ""])).lower()
        return needle in haystack

    def _matches_melt_q(self, item: MeltQueueItem, q: str | None) -> bool:
        if not q or not q.strip():
            return True
        needle = q.strip().lower()
        haystack = " ".join([item.studentName, item.program, " ".join(item.missingMilestones)]).lower()
        return needle in haystack

    def _handoff_status(self, value: str | None) -> str:
        normalized = (value or "").lower()
        if normalized in {"failed", "error"}:
            return "failed"
        if normalized in {"blocked", "hold"}:
            return "blocked"
        return "healthy"

    def _office_from_queue(self, queue_name: str | None) -> str:
        normalized = (queue_name or "").lower()
        if "financial" in normalized:
            return "Financial Aid"
        if "orientation" in normalized:
            return "Orientation"
        if "sis" in normalized:
            return "SIS"
        return "Connector"

    def _student_name(self, student: Student | None, demographics: TranscriptDemographics | None) -> str:
        if student is not None:
            parts = [student.preferred_name or student.first_name or "", student.last_name or ""]
            name = " ".join(part for part in parts if part.strip()).strip()
            if name:
                return name
        if demographics is not None:
            parts = [demographics.student_first_name or "", demographics.student_last_name or ""]
            name = " ".join(part for part in parts if part.strip()).strip()
            if name:
                return name
        return "Unknown Student"

    def _admin_user_status(self, user: AppUser, membership: TenantUserMembership) -> str:
        normalized = (membership.status or "").lower()
        if normalized in {"invited", "inactive", "active"}:
            return normalized
        return "active" if user.is_active else "inactive"

    def _generate_temporary_password(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
        special = "!@#$%^&*"
        return "".join(
            [
                secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"),
                secrets.choice("abcdefghijkmnopqrstuvwxyz"),
                secrets.choice("23456789"),
                secrets.choice(special),
                *(secrets.choice(alphabet + special) for _ in range(12)),
            ]
        )

    def _fetch_cognito_sub(self, email: str) -> str | None:
        try:
            response = self.auth_service.admin_get_user(email=email)
        except Exception:
            return None
        attrs = {item["Name"]: item["Value"] for item in response.get("UserAttributes", [])}
        return attrs.get("sub")

    def _days_stalled(self, value: str | None) -> int:
        if not value:
            return 0
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0
        return max(0, (datetime.now(timezone.utc) - dt).days)

    def _iso(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _ratio(self, numerator: int, denominator: int) -> float:
        if not denominator:
            return 0.0
        return round(numerator / denominator, 2)

    def _to_float(self, value, fallback):
        if value is None:
            return fallback
        try:
            return float(value)
        except Exception:
            return fallback

    def _title_case(self, value: str) -> str:
        return value.replace("_", " ").replace("-", " ").title()
