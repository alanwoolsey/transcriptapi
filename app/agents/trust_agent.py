from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from app.agents.base import AgentExecutionContext, AgentResultEnvelope, AgentRunResult, StrandsAgentFactory, log_agent_execution_event
from app.agents.tools import TrustCaseTool, TrustContextTool
from app.services.agent_run_service import AgentRunService


@dataclass(slots=True)
class TrustAgentInput:
    action: str
    document_id: str
    transcript_id: str
    student_id: str | None = None
    target_student_id: str | None = None
    assigned_user_id: str | None = None
    reason: str | None = None


class TrustAgent:
    def __init__(
        self,
        *,
        factory: StrandsAgentFactory | None = None,
        agent_run_service: AgentRunService | None = None,
        trust_context_tool: TrustContextTool | None = None,
        trust_case_tool: TrustCaseTool | None = None,
    ) -> None:
        self.factory = factory or StrandsAgentFactory()
        self.agent_run_service = agent_run_service or AgentRunService()
        self.trust_context_tool = trust_context_tool or TrustContextTool()
        self.trust_case_tool = trust_case_tool or TrustCaseTool()

    def build(self):
        return self.factory.create(
            system_prompt=(
                "You are the Trust Agent for an admissions system. "
                "Use deterministic trust tools to inspect identity matches, trust flags, and document history. "
                "Explain risk clearly and never mark a document trusted without evidence."
            ),
            tools=[
                *self.trust_context_tool.as_strands_tools(),
                *self.trust_case_tool.as_strands_tools(),
            ],
        )

    def _build_result_envelope(
        self,
        *,
        code: str,
        message: str,
        transcript_id: str,
        document_id: str,
        student_id: str | None = None,
        target_student_id: str | None = None,
        assigned_user_id: str | None = None,
        reason: str | None = None,
    ) -> AgentResultEnvelope:
        metrics: dict[str, Any] = {}
        if target_student_id is not None:
            metrics["targetStudentAssigned"] = True
        artifacts: dict[str, Any] = {
            "documentId": document_id,
            "transcriptId": transcript_id,
        }
        if student_id is not None:
            artifacts["studentId"] = student_id
        if target_student_id is not None:
            artifacts["targetStudentId"] = target_student_id
        if assigned_user_id is not None:
            artifacts["assignedUserId"] = assigned_user_id
        if reason is not None:
            artifacts["reason"] = reason
        return AgentResultEnvelope(
            status="completed",
            code=code,
            message=message,
            metrics=metrics,
            artifacts=artifacts,
        )

    def record_action(
        self,
        *,
        context: AgentExecutionContext,
        payload: TrustAgentInput,
        trigger_event: str,
        action_type: str,
        tool_name: str,
        code: str,
        message: str,
        owner_student_id: UUID | None,
        state_json: dict[str, Any] | None = None,
    ) -> AgentRunResult:
        result = self._build_result_envelope(
            code=code,
            message=message,
            transcript_id=payload.transcript_id,
            document_id=payload.document_id,
            student_id=payload.student_id,
            target_student_id=payload.target_student_id,
            assigned_user_id=payload.assigned_user_id,
            reason=payload.reason,
        )
        log_agent_execution_event(
            "agent_run_started",
            agent_name="trust_agent",
            context=context,
            status="running",
            triggerEvent=trigger_event,
            action_type=action_type,
        )
        if not self.agent_run_service.is_enabled():
            log_agent_execution_event(
                "agent_run_completed",
                agent_name="trust_agent",
                context=context,
                status="completed",
                result_code=result.code,
            )
            return AgentRunResult(
                agent_name="trust_agent",
                status="completed",
                message=result.message,
                result=result,
                payload={
                    "context": asdict(context),
                    "input": asdict(payload),
                    "summary": asdict(result),
                },
            )

        session_factory = self.agent_run_service.session_factory()
        with session_factory() as session:
            with session.begin():
                run = self.agent_run_service.create_run(
                    session,
                    tenant_id=context.tenant_id,
                    student_id=owner_student_id,
                    transcript_id=context.transcript_id,
                    actor_user_id=context.actor_user_id,
                    correlation_id=context.correlation_id,
                    agent_name="trust_agent",
                    agent_type="trust",
                    trigger_event=trigger_event,
                    status="running",
                    input_json={
                        "context": asdict(context),
                        "input": asdict(payload),
                    },
                )
                log_agent_execution_event(
                    "agent_run_persisted",
                    agent_name="trust_agent",
                    context=context,
                    status="running",
                    run_id=run.id,
                    triggerEvent=trigger_event,
                )
                self.agent_run_service.record_action(
                    session,
                    tenant_id=context.tenant_id,
                    run_id=run.id,
                    student_id=owner_student_id,
                    transcript_id=context.transcript_id,
                    action_type=action_type,
                    tool_name=tool_name,
                    status="completed",
                    input_json=asdict(payload),
                    output_json=asdict(result),
                )
                log_agent_execution_event(
                    "agent_action_completed",
                    agent_name="trust_agent",
                    context=context,
                    status="completed",
                    run_id=run.id,
                    action_type=action_type,
                    tool_name=tool_name,
                    result_code=result.code,
                )
                self.agent_run_service.complete_run(
                    session,
                    run=run,
                    status="completed",
                    output_json=asdict(result),
                )
                if owner_student_id is not None:
                    self.agent_run_service.upsert_student_state(
                        session,
                        tenant_id=context.tenant_id,
                        student_id=owner_student_id,
                        current_owner_agent="trust_agent",
                        state_json=(state_json or {"last_trust_action": payload.action}),
                        last_trust_run_id=run.id,
                    )
        log_agent_execution_event(
            "agent_run_completed",
            agent_name="trust_agent",
            context=context,
            status="completed",
            run_id=run.id,
            result_code=result.code,
        )
        return AgentRunResult(
            agent_name="trust_agent",
            status="completed",
            message=result.message,
            result=result,
            payload={
                "context": asdict(context),
                "input": asdict(payload),
                "summary": asdict(result),
            },
        )
