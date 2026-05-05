from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentExecutionContext
from app.agents.trust_agent import TrustAgent, TrustAgentInput
from app.db.models import AgentRun, AppUser, Student, Transcript, TranscriptDemographics, TrustFlag
from app.db.session import get_session_factory
from app.models.operations_models import ActionResponse
from app.models.operations_models import AgentRunActionItemResponse, AgentRunResultResponse, AgentRunStatusResponse
from app.models.trust_models import TrustCaseDetailsResponse, TrustCaseItem, TrustCaseSummary
from app.services.agent_run_service import AgentRunService


class TrustService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory
        self.agent_run_service = AgentRunService(session_factory=self.session_factory)
        self.trust_agent = TrustAgent(agent_run_service=self.agent_run_service)

    def list_cases(self, tenant_id: UUID) -> list[TrustCaseItem]:
        session_factory = self.session_factory()
        with session_factory() as session:
            trust_cases = self._list_trust_flags(session, tenant_id)
            if trust_cases:
                return trust_cases
            return self._list_fraudulent_transcripts(session, tenant_id)

    def get_case_details(self, tenant_id: UUID, transcript_id: str) -> TrustCaseDetailsResponse | None:
        try:
            resolved_transcript_id = UUID(transcript_id)
        except ValueError:
            return None
        session_factory = self.session_factory()
        with session_factory() as session:
            row = session.execute(
                select(Transcript, Student, TranscriptDemographics)
                .outerjoin(Student, Student.id == Transcript.student_id)
                .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
                .where(Transcript.tenant_id == tenant_id, Transcript.id == resolved_transcript_id)
                .limit(1)
            ).one_or_none()
            if row is None:
                return None
            transcript, student, demographics = row
            latest_flag = session.execute(
                select(TrustFlag)
                .where(TrustFlag.tenant_id == tenant_id, TrustFlag.transcript_id == transcript.id)
                .order_by(TrustFlag.detected_at.desc(), TrustFlag.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            assigned_user = (
                session.get(AppUser, latest_flag.assigned_to_user_id)
                if latest_flag is not None and latest_flag.assigned_to_user_id is not None
                else None
            )
            latest_run = session.execute(
                select(AgentRun)
                .where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.transcript_id == transcript.id,
                    AgentRun.agent_name == "trust_agent",
                )
                .order_by(AgentRun.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            actions: list[AgentRunActionItemResponse] = []
            run_response: AgentRunStatusResponse | None = None
            latest_result = self._build_agent_run_result(latest_run.output_json) if latest_run is not None else None
            if latest_run is not None:
                run_response = AgentRunStatusResponse(
                    runId=str(latest_run.id),
                    agentName=latest_run.agent_name,
                    agentType=latest_run.agent_type,
                    status=latest_run.status,
                    triggerEvent=latest_run.trigger_event,
                    studentId=str(latest_run.student_id) if latest_run.student_id else None,
                    transcriptId=str(latest_run.transcript_id) if latest_run.transcript_id else None,
                    actorUserId=str(latest_run.actor_user_id) if latest_run.actor_user_id else None,
                    correlationId=latest_run.correlation_id,
                    error=latest_run.error_message,
                    startedAt=self._format_time(latest_run.started_at),
                    completedAt=self._format_time(latest_run.completed_at),
                    result=latest_result,
                )
                actions = [
                    AgentRunActionItemResponse(
                        actionId=str(action.id),
                        actionType=action.action_type,
                        toolName=action.tool_name,
                        status=action.status,
                        studentId=str(action.student_id) if action.student_id else None,
                        transcriptId=str(action.transcript_id) if action.transcript_id else None,
                        error=action.error_message,
                        startedAt=self._format_time(action.started_at),
                        completedAt=self._format_time(action.completed_at),
                        result=self._build_agent_run_result(action.output_json),
                        input=action.input_json or {},
                        output=action.output_json or {},
                    )
                    for action in self.agent_run_service.list_actions(session, tenant_id=tenant_id, run_id=latest_run.id)
                ]
            signal = self._title_case(latest_flag.flag_type) if latest_flag is not None else "Fraudulent transcript"
            evidence = (
                latest_flag.reason
                if latest_flag is not None and latest_flag.reason
                else (transcript.notes or "Transcript was flagged as fraudulent and requires manual review.")
            )
            status = self._title_case(latest_flag.status) if latest_flag is not None else (self._title_case(transcript.status) or "Quarantined")
            severity = self._title_case(latest_flag.severity) if latest_flag is not None else "High"
            opened_at = self._format_time(latest_flag.detected_at) if latest_flag is not None else self._format_time(transcript.created_at)
            summary = self._build_trust_summary(
                severity=severity,
                signal=signal,
                evidence=evidence,
                status=status,
                trust_blocked=bool(transcript.is_fraudulent or (latest_flag is not None and (latest_flag.status or "").lower() not in {"resolved", "closed"})),
                owner=self._user_ref(assigned_user),
                latest_result_code=(latest_result.code if latest_result is not None else None),
            )
            return TrustCaseDetailsResponse(
                transcriptId=str(transcript.id),
                studentId=(str(student.id) if student else None),
                student=self._student_name(student, demographics),
                document="Official transcript",
                severity=severity,
                signal=signal,
                evidence=evidence,
                status=status,
                trustBlocked=bool(transcript.is_fraudulent or (latest_flag is not None and (latest_flag.status or "").lower() not in {"resolved", "closed"})),
                owner=self._user_ref(assigned_user),
                openedAt=opened_at,
                summary=summary,
                latestRun=run_response,
                actions=actions,
            )

    def assign_case(self, tenant_id: UUID, transcript_id: str, actor_user_id: UUID | None, assignee_user_id: str, note: str | None = None) -> ActionResponse:
        try:
            resolved_transcript_id = UUID(transcript_id)
            resolved_assignee_user_id = UUID(assignee_user_id)
        except ValueError:
            return ActionResponse(success=False, status="not_found", detail="Trust case or assignee not found.")
        session_factory = self.session_factory()
        with session_factory() as session:
            transcript = session.execute(
                select(Transcript)
                .where(Transcript.tenant_id == tenant_id, Transcript.id == resolved_transcript_id)
                .limit(1)
            ).scalar_one_or_none()
            assignee = session.execute(
                select(AppUser)
                .where(AppUser.tenant_id == tenant_id, AppUser.id == resolved_assignee_user_id)
                .limit(1)
            ).scalar_one_or_none()
            if transcript is None or assignee is None:
                return ActionResponse(success=False, status="not_found", detail="Trust case or assignee not found.")
            open_flags = session.execute(
                select(TrustFlag)
                .where(
                    TrustFlag.tenant_id == tenant_id,
                    TrustFlag.transcript_id == transcript.id,
                    TrustFlag.status.notin_(["resolved", "closed"]),
                )
            ).scalars().all()
            reason = note or f"Assigned to {assignee.display_name}."
            if open_flags:
                for flag in open_flags:
                    flag.assigned_to_user_id = assignee.id
                    if note:
                        flag.reason = note
            else:
                session.add(
                    TrustFlag(
                        tenant_id=tenant_id,
                        transcript_id=transcript.id,
                        student_id=transcript.student_id,
                        flag_type="manual_assignment",
                        severity="medium",
                        status="open",
                        reason=reason,
                        detected_by="user",
                        detected_at=datetime.now(timezone.utc),
                        assigned_to_user_id=assignee.id,
                    )
                )
            session.commit()
            self.trust_agent.record_action(
                context=AgentExecutionContext(
                    tenant_id=tenant_id,
                    student_id=transcript.student_id,
                    transcript_id=transcript.id,
                    actor_user_id=actor_user_id,
                    correlation_id=f"trust-assign:{transcript.id}",
                ),
                payload=TrustAgentInput(
                    action="assign_case",
                    document_id=str(transcript.document_upload_id),
                    transcript_id=str(transcript.id),
                    student_id=(str(transcript.student_id) if transcript.student_id is not None else None),
                    assigned_user_id=str(assignee.id),
                    reason=reason,
                ),
                trigger_event="manual_assign",
                action_type="assign_trust_case",
                tool_name="assign_trust_case",
                code="trust_case_assigned",
                message="Trust case assigned.",
                owner_student_id=transcript.student_id,
                state_json={"last_trust_action": "assign_case", "transcriptId": str(transcript.id), "assignedUserId": str(assignee.id)},
            )
            return ActionResponse(status="assigned", detail="Trust case assigned.")

    def resolve_case(self, tenant_id: UUID, transcript_id: str, actor_user_id: UUID | None, note: str | None = None) -> ActionResponse:
        try:
            resolved_transcript_id = UUID(transcript_id)
        except ValueError:
            return ActionResponse(success=False, status="not_found", detail="Trust case not found.")
        session_factory = self.session_factory()
        with session_factory() as session:
            transcript = session.execute(
                select(Transcript)
                .where(Transcript.tenant_id == tenant_id, Transcript.id == resolved_transcript_id)
                .limit(1)
            ).scalar_one_or_none()
            if transcript is None:
                return ActionResponse(success=False, status="not_found", detail="Trust case not found.")
            open_flags = session.execute(
                select(TrustFlag)
                .where(
                    TrustFlag.tenant_id == tenant_id,
                    TrustFlag.transcript_id == transcript.id,
                    TrustFlag.status.notin_(["resolved", "closed"]),
                )
            ).scalars().all()
            transcript.is_fraudulent = False
            for flag in open_flags:
                flag.status = "resolved"
                flag.resolved_by_user_id = actor_user_id
                flag.resolved_at = datetime.now(timezone.utc)
                flag.resolution_notes = note or "Resolved by reviewer."
            session.commit()
            self.trust_agent.record_action(
                context=AgentExecutionContext(
                    tenant_id=tenant_id,
                    student_id=transcript.student_id,
                    transcript_id=transcript.id,
                    actor_user_id=actor_user_id,
                    correlation_id=f"trust-resolve:{transcript.id}",
                ),
                payload=TrustAgentInput(
                    action="resolve_case",
                    document_id=str(transcript.document_upload_id),
                    transcript_id=str(transcript.id),
                    student_id=(str(transcript.student_id) if transcript.student_id is not None else None),
                    reason=note or "Resolved by reviewer.",
                ),
                trigger_event="manual_resolve",
                action_type="resolve_trust_case",
                tool_name="resolve_trust_case",
                code="trust_case_resolved",
                message="Trust case resolved.",
                owner_student_id=transcript.student_id,
                state_json={"last_trust_action": "resolve_case", "transcriptId": str(transcript.id)},
            )
            return ActionResponse(status="resolved", detail="Trust case resolved.")

    def block_case(self, tenant_id: UUID, transcript_id: str, actor_user_id: UUID | None, note: str | None = None) -> ActionResponse:
        try:
            resolved_transcript_id = UUID(transcript_id)
        except ValueError:
            return ActionResponse(success=False, status="not_found", detail="Trust case not found.")
        session_factory = self.session_factory()
        with session_factory() as session:
            transcript = session.execute(
                select(Transcript)
                .where(Transcript.tenant_id == tenant_id, Transcript.id == resolved_transcript_id)
                .limit(1)
            ).scalar_one_or_none()
            if transcript is None:
                return ActionResponse(success=False, status="not_found", detail="Trust case not found.")
            open_flags = session.execute(
                select(TrustFlag)
                .where(
                    TrustFlag.tenant_id == tenant_id,
                    TrustFlag.transcript_id == transcript.id,
                    TrustFlag.status.notin_(["resolved", "closed"]),
                )
            ).scalars().all()
            transcript.is_fraudulent = True
            reason = note or "Blocked pending trust review."
            if open_flags:
                for flag in open_flags:
                    flag.status = "blocked"
                    flag.severity = "high"
                    flag.reason = reason
            else:
                session.add(
                    TrustFlag(
                        tenant_id=tenant_id,
                        transcript_id=transcript.id,
                        student_id=transcript.student_id,
                        flag_type="manual_block",
                        severity="high",
                        status="blocked",
                        reason=reason,
                        detected_by="user",
                        detected_at=datetime.now(timezone.utc),
                    )
                )
            session.commit()
            self.trust_agent.record_action(
                context=AgentExecutionContext(
                    tenant_id=tenant_id,
                    student_id=transcript.student_id,
                    transcript_id=transcript.id,
                    actor_user_id=actor_user_id,
                    correlation_id=f"trust-block:{transcript.id}",
                ),
                payload=TrustAgentInput(
                    action="block_case",
                    document_id=str(transcript.document_upload_id),
                    transcript_id=str(transcript.id),
                    student_id=(str(transcript.student_id) if transcript.student_id is not None else None),
                    reason=reason,
                ),
                trigger_event="manual_block",
                action_type="block_trust_case",
                tool_name="block_trust_case",
                code="trust_case_blocked",
                message="Trust case blocked.",
                owner_student_id=transcript.student_id,
                state_json={"last_trust_action": "block_case", "transcriptId": str(transcript.id)},
            )
            return ActionResponse(status="blocked", detail="Trust case blocked.")

    def unblock_case(self, tenant_id: UUID, transcript_id: str, actor_user_id: UUID | None, note: str | None = None) -> ActionResponse:
        try:
            resolved_transcript_id = UUID(transcript_id)
        except ValueError:
            return ActionResponse(success=False, status="not_found", detail="Trust case not found.")
        session_factory = self.session_factory()
        with session_factory() as session:
            transcript = session.execute(
                select(Transcript)
                .where(Transcript.tenant_id == tenant_id, Transcript.id == resolved_transcript_id)
                .limit(1)
            ).scalar_one_or_none()
            if transcript is None:
                return ActionResponse(success=False, status="not_found", detail="Trust case not found.")
            open_flags = session.execute(
                select(TrustFlag)
                .where(
                    TrustFlag.tenant_id == tenant_id,
                    TrustFlag.transcript_id == transcript.id,
                    TrustFlag.status.notin_(["resolved", "closed"]),
                )
            ).scalars().all()
            transcript.is_fraudulent = False
            for flag in open_flags:
                flag.status = "resolved"
                flag.resolved_by_user_id = actor_user_id
                flag.resolved_at = datetime.now(timezone.utc)
                flag.resolution_notes = note or "Unblocked by reviewer."
            session.commit()
            self.trust_agent.record_action(
                context=AgentExecutionContext(
                    tenant_id=tenant_id,
                    student_id=transcript.student_id,
                    transcript_id=transcript.id,
                    actor_user_id=actor_user_id,
                    correlation_id=f"trust-unblock:{transcript.id}",
                ),
                payload=TrustAgentInput(
                    action="unblock_case",
                    document_id=str(transcript.document_upload_id),
                    transcript_id=str(transcript.id),
                    student_id=(str(transcript.student_id) if transcript.student_id is not None else None),
                    reason=note or "Unblocked by reviewer.",
                ),
                trigger_event="manual_unblock",
                action_type="unblock_trust_case",
                tool_name="unblock_trust_case",
                code="trust_case_unblocked",
                message="Trust case unblocked.",
                owner_student_id=transcript.student_id,
                state_json={"last_trust_action": "unblock_case", "transcriptId": str(transcript.id)},
            )
            return ActionResponse(status="unblocked", detail="Trust case unblocked.")

    def escalate_case(self, tenant_id: UUID, transcript_id: str, actor_user_id: UUID | None, note: str | None = None) -> ActionResponse:
        try:
            resolved_transcript_id = UUID(transcript_id)
        except ValueError:
            return ActionResponse(success=False, status="not_found", detail="Trust case not found.")
        session_factory = self.session_factory()
        with session_factory() as session:
            transcript = session.execute(
                select(Transcript)
                .where(Transcript.tenant_id == tenant_id, Transcript.id == resolved_transcript_id)
                .limit(1)
            ).scalar_one_or_none()
            if transcript is None:
                return ActionResponse(success=False, status="not_found", detail="Trust case not found.")
            open_flags = session.execute(
                select(TrustFlag)
                .where(
                    TrustFlag.tenant_id == tenant_id,
                    TrustFlag.transcript_id == transcript.id,
                    TrustFlag.status.notin_(["resolved", "closed"]),
                )
            ).scalars().all()
            transcript.is_fraudulent = True
            reason = note or "Escalated for additional trust review."
            if open_flags:
                for flag in open_flags:
                    flag.status = "escalated"
                    flag.severity = "high"
                    flag.reason = reason
            else:
                session.add(
                    TrustFlag(
                        tenant_id=tenant_id,
                        transcript_id=transcript.id,
                        student_id=transcript.student_id,
                        flag_type="manual_escalation",
                        severity="high",
                        status="escalated",
                        reason=reason,
                        detected_by="user",
                        detected_at=datetime.now(timezone.utc),
                    )
                )
            session.commit()
            self.trust_agent.record_action(
                context=AgentExecutionContext(
                    tenant_id=tenant_id,
                    student_id=transcript.student_id,
                    transcript_id=transcript.id,
                    actor_user_id=actor_user_id,
                    correlation_id=f"trust-escalate:{transcript.id}",
                ),
                payload=TrustAgentInput(
                    action="escalate_case",
                    document_id=str(transcript.document_upload_id),
                    transcript_id=str(transcript.id),
                    student_id=(str(transcript.student_id) if transcript.student_id is not None else None),
                    reason=reason,
                ),
                trigger_event="manual_escalate",
                action_type="escalate_trust_case",
                tool_name="escalate_trust_case",
                code="trust_case_escalated",
                message="Trust case escalated.",
                owner_student_id=transcript.student_id,
                state_json={"last_trust_action": "escalate_case", "transcriptId": str(transcript.id)},
            )
            return ActionResponse(status="escalated", detail="Trust case escalated.")

    def _list_trust_flags(self, session: Session, tenant_id: UUID) -> list[TrustCaseItem]:
        stmt = (
            select(TrustFlag, Student, TranscriptDemographics)
            .outerjoin(Student, Student.id == TrustFlag.student_id)
            .outerjoin(Transcript, Transcript.id == TrustFlag.transcript_id)
            .outerjoin(TranscriptDemographics, TranscriptDemographics.transcript_id == Transcript.id)
            .where(TrustFlag.tenant_id == tenant_id)
            .order_by(TrustFlag.detected_at.desc())
        )
        rows = session.execute(stmt).all()
        transcript_ids = [trust_flag.transcript_id for trust_flag, _student, _demographics in rows if trust_flag.transcript_id is not None]
        latest_runs = self._latest_trust_runs_by_transcript(session, tenant_id, transcript_ids)
        items: list[TrustCaseItem] = []
        for trust_flag, student, demographics in rows:
            latest_run = latest_runs.get(trust_flag.transcript_id) if trust_flag.transcript_id is not None else None
            latest_result = self._build_agent_run_result(latest_run.output_json if latest_run is not None else None)
            assigned_user = session.get(AppUser, trust_flag.assigned_to_user_id) if trust_flag.assigned_to_user_id is not None else None
            severity = self._title_case(trust_flag.severity)
            signal = self._title_case(trust_flag.flag_type)
            status = self._title_case(trust_flag.status)
            trust_blocked = (trust_flag.status or "").lower() not in {"resolved", "closed"}
            owner = self._user_ref(assigned_user)
            items.append(
                TrustCaseItem(
                    id=str(trust_flag.id),
                    transcriptId=(str(trust_flag.transcript_id) if trust_flag.transcript_id is not None else None),
                    studentId=(str(student.id) if student else None),
                    student=self._student_name(student, demographics),
                    documentId=str(trust_flag.transcript_id),
                    document="Official transcript",
                    severity=severity,
                    signal=signal,
                    evidence=trust_flag.reason,
                    status=status,
                    trustBlocked=trust_blocked,
                    latestRunStatus=(latest_run.status if latest_run is not None else None),
                    latestResultCode=(latest_result.code if latest_result is not None else None),
                    owner=owner,
                    openedAt=self._format_time(trust_flag.detected_at),
                    summary=self._build_trust_summary(
                        severity=severity,
                        signal=signal,
                        evidence=trust_flag.reason,
                        status=status,
                        trust_blocked=trust_blocked,
                        owner=owner,
                        latest_result_code=(latest_result.code if latest_result is not None else None),
                    ),
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
        rows = session.execute(stmt).all()
        transcript_ids = [transcript.id for transcript, _student, _demographics in rows]
        latest_runs = self._latest_trust_runs_by_transcript(session, tenant_id, transcript_ids)
        items: list[TrustCaseItem] = []
        for transcript, student, demographics in rows:
            latest_run = latest_runs.get(transcript.id)
            latest_result = self._build_agent_run_result(latest_run.output_json if latest_run is not None else None)
            severity = "High"
            signal = "Fraudulent transcript"
            status = self._title_case(transcript.status) or "Quarantined"
            evidence = transcript.notes or "Transcript was flagged as fraudulent and requires manual review."
            items.append(
                TrustCaseItem(
                    id=f"TRUST-{str(transcript.id)[:8]}",
                    transcriptId=str(transcript.id),
                    studentId=(str(student.id) if student else None),
                    student=self._student_name(student, demographics),
                    documentId=str(transcript.id),
                    document="Official transcript",
                    severity=severity,
                    signal=signal,
                    evidence=evidence,
                    status=status,
                    trustBlocked=True,
                    latestRunStatus=(latest_run.status if latest_run is not None else None),
                    latestResultCode=(latest_result.code if latest_result is not None else None),
                    owner=None,
                    openedAt=self._format_time(transcript.created_at),
                    summary=self._build_trust_summary(
                        severity=severity,
                        signal=signal,
                        evidence=evidence,
                        status=status,
                        trust_blocked=True,
                        owner=None,
                        latest_result_code=(latest_result.code if latest_result is not None else None),
                    ),
                )
            )
        return items

    def _build_trust_summary(
        self,
        *,
        severity: str,
        signal: str,
        evidence: str | None,
        status: str,
        trust_blocked: bool,
        owner: dict[str, str] | None,
        latest_result_code: str | None,
    ) -> TrustCaseSummary:
        normalized_severity = (severity or "").strip().lower()
        if trust_blocked and normalized_severity == "high":
            risk_level = "high"
        elif trust_blocked:
            risk_level = "medium"
        else:
            risk_level = "low"

        if trust_blocked and owner is None:
            recommended_action = "Assign this case for trust review."
        elif trust_blocked and (status or "").lower() in {"blocked", "escalated"}:
            recommended_action = "Review evidence and resolve, unblock, or keep escalated."
        elif trust_blocked:
            recommended_action = "Review the trust signal and decide whether progression should remain blocked."
        else:
            recommended_action = "No active trust hold is blocking progression."

        signal_text = signal or "Trust signal"
        summary_text = f"{signal_text} is {status.lower() if status else 'open'}."
        if trust_blocked:
            summary_text += " Student progression is currently blocked."
        else:
            summary_text += " Student progression is not blocked by trust."

        rationale_parts = []
        if evidence:
            rationale_parts.append(evidence)
        if latest_result_code:
            rationale_parts.append(f"Latest trust-agent outcome: {latest_result_code}.")
        if owner is not None:
            rationale_parts.append(f"Owner: {owner.get('name') or owner.get('id')}.")

        return TrustCaseSummary(
            riskLevel=risk_level,
            summary=summary_text,
            rationale=" ".join(rationale_parts) or "No additional evidence is available.",
            recommendedAction=recommended_action,
            signals=[value for value in [signal, severity, status] if value],
        )

    def _latest_trust_runs_by_transcript(self, session: Session, tenant_id: UUID, transcript_ids: list[UUID]) -> dict[UUID, AgentRun]:
        if not transcript_ids:
            return {}
        rows = session.execute(
            select(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.agent_name == "trust_agent",
                AgentRun.transcript_id.in_(transcript_ids),
            )
            .order_by(AgentRun.transcript_id.asc(), AgentRun.created_at.desc())
        ).scalars().all()
        items: dict[UUID, AgentRun] = {}
        for row in rows:
            if row.transcript_id is not None and row.transcript_id not in items:
                items[row.transcript_id] = row
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

    def _build_agent_run_result(self, payload: dict | None) -> AgentRunResultResponse | None:
        if not isinstance(payload, dict):
            return None
        required_keys = {"status", "code", "message"}
        if not required_keys.issubset(payload.keys()):
            return None
        return AgentRunResultResponse(
            status=str(payload.get("status")),
            code=str(payload.get("code")),
            message=str(payload.get("message")),
            error=(str(payload.get("error")) if payload.get("error") is not None else None),
            metrics=(payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}),
            artifacts=(payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}),
        )

    def _user_ref(self, user: AppUser | None) -> dict[str, str] | None:
        if user is None:
            return None
        return {"id": str(user.id), "name": user.display_name}
