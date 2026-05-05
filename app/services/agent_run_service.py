from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentAction, AgentHandoff, AgentRun, StudentAgentState
from app.db.session import get_database_url, get_session_factory


class AgentRunService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or get_session_factory

    def is_enabled(self) -> bool:
        return bool(get_database_url())

    def create_run(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        agent_name: str,
        status: str,
        input_json: dict,
        student_id: UUID | None = None,
        transcript_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        correlation_id: str | None = None,
        agent_type: str | None = None,
        trigger_event: str | None = None,
        parent_run_id: UUID | None = None,
    ) -> AgentRun:
        run = AgentRun(
            tenant_id=tenant_id,
            student_id=student_id,
            transcript_id=transcript_id,
            actor_user_id=actor_user_id,
            parent_run_id=parent_run_id,
            agent_name=agent_name,
            agent_type=agent_type,
            trigger_event=trigger_event,
            status=status,
            input_json=self._json_safe(input_json or {}),
            output_json={},
            correlation_id=correlation_id,
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.flush()
        return run

    def get_run(self, session: Session, *, tenant_id: UUID, run_id: UUID) -> AgentRun | None:
        return session.execute(
            select(AgentRun).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == run_id,
            ).limit(1)
        ).scalar_one_or_none()

    def list_actions(self, session: Session, *, tenant_id: UUID, run_id: UUID) -> list[AgentAction]:
        return session.execute(
            select(AgentAction)
            .where(
                AgentAction.tenant_id == tenant_id,
                AgentAction.run_id == run_id,
            )
            .order_by(AgentAction.started_at.asc(), AgentAction.created_at.asc())
        ).scalars().all()

    def get_latest_run_for_transcript(self, session: Session, *, tenant_id: UUID, transcript_id: UUID) -> AgentRun | None:
        return session.execute(
            select(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.transcript_id == transcript_id,
            )
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def complete_run(
        self,
        session: Session,
        *,
        run: AgentRun,
        status: str,
        output_json: dict | None = None,
        error_message: str | None = None,
    ) -> AgentRun:
        run.status = status
        run.output_json = self._json_safe(output_json or {})
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        run.updated_at = datetime.now(timezone.utc)
        session.flush()
        return run

    def record_action(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        run_id: UUID,
        action_type: str,
        status: str,
        input_json: dict | None = None,
        output_json: dict | None = None,
        student_id: UUID | None = None,
        transcript_id: UUID | None = None,
        tool_name: str | None = None,
        error_message: str | None = None,
    ) -> AgentAction:
        action = AgentAction(
            tenant_id=tenant_id,
            run_id=run_id,
            student_id=student_id,
            transcript_id=transcript_id,
            action_type=action_type,
            tool_name=tool_name,
            status=status,
            input_json=self._json_safe(input_json or {}),
            output_json=self._json_safe(output_json or {}),
            error_message=error_message,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(action)
        session.flush()
        return action

    def record_handoff(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        from_agent_name: str,
        to_agent_name: str,
        status: str,
        student_id: UUID | None = None,
        transcript_id: UUID | None = None,
        from_run_id: UUID | None = None,
        to_run_id: UUID | None = None,
        reason: str | None = None,
        payload_json: dict | None = None,
    ) -> AgentHandoff:
        handoff = AgentHandoff(
            tenant_id=tenant_id,
            student_id=student_id,
            transcript_id=transcript_id,
            from_run_id=from_run_id,
            to_run_id=to_run_id,
            from_agent_name=from_agent_name,
            to_agent_name=to_agent_name,
            status=status,
            reason=reason,
            payload_json=self._json_safe(payload_json or {}),
        )
        session.add(handoff)
        session.flush()
        return handoff

    def upsert_student_state(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        student_id: UUID,
        current_owner_agent: str | None = None,
        current_stage: str | None = None,
        state_json: dict | None = None,
        last_document_run_id: UUID | None = None,
        last_trust_run_id: UUID | None = None,
        last_decision_run_id: UUID | None = None,
        last_orchestrator_run_id: UUID | None = None,
    ) -> StudentAgentState:
        state = session.execute(
            select(StudentAgentState).where(
                StudentAgentState.tenant_id == tenant_id,
                StudentAgentState.student_id == student_id,
            ).limit(1)
        ).scalar_one_or_none()
        if state is None:
            state = StudentAgentState(tenant_id=tenant_id, student_id=student_id)
            session.add(state)
            session.flush()

        if current_owner_agent is not None:
            state.current_owner_agent = current_owner_agent
        if current_stage is not None:
            state.current_stage = current_stage
        if state_json is not None:
            state.state_json = self._json_safe(state_json)
        if last_document_run_id is not None:
            state.last_document_run_id = last_document_run_id
        if last_trust_run_id is not None:
            state.last_trust_run_id = last_trust_run_id
        if last_decision_run_id is not None:
            state.last_decision_run_id = last_decision_run_id
        if last_orchestrator_run_id is not None:
            state.last_orchestrator_run_id = last_orchestrator_run_id
        state.updated_at = datetime.now(timezone.utc)
        session.flush()
        return state

    def _json_safe(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, (datetime, date)):
            if isinstance(value, datetime) and value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]
        return str(value)
