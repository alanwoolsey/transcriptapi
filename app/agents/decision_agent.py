from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from app.agents.base import AgentExecutionContext, AgentResultEnvelope, AgentRunResult, StrandsAgentFactory, log_agent_execution_event
from app.agents.tools import DecisionPacketAssemblyTool, DecisionReadinessEvidenceTool
from app.services.agent_run_service import AgentRunService


@dataclass(slots=True)
class DecisionAgentInput:
    decision_id: str
    student_id: str | None = None
    transcript_id: str | None = None
    status: str | None = None
    readiness: str | None = None
    readiness_reason: str | None = None
    fit: int | None = None
    credit_estimate: int | None = None
    trust_status: str | None = None
    trust_signal_count: int | None = None
    active_trust_signal_count: int | None = None
    institution: str | None = None
    gpa: float | None = None
    credits_earned: float | None = None
    parser_confidence: float | None = None
    document_count: int | None = None
    reason: str | None = None
    confidence: int | None = None
    rationale: list[str] | None = None


class DecisionAgent:
    def __init__(
        self,
        *,
        factory: StrandsAgentFactory | None = None,
        agent_run_service: AgentRunService | None = None,
        packet_assembly_tool: DecisionPacketAssemblyTool | None = None,
        readiness_evidence_tool: DecisionReadinessEvidenceTool | None = None,
    ) -> None:
        self.factory = factory or StrandsAgentFactory()
        self.agent_run_service = agent_run_service or AgentRunService()
        self.packet_assembly_tool = packet_assembly_tool or DecisionPacketAssemblyTool()
        self.readiness_evidence_tool = readiness_evidence_tool or DecisionReadinessEvidenceTool()

    def _build_context_envelope(self, payload: DecisionAgentInput) -> AgentResultEnvelope:
        result = self.packet_assembly_tool.assemble_decision_context(asdict(payload))
        return AgentResultEnvelope(
            status=str(result["status"]),
            code=str(result["code"]),
            message=str(result["message"]),
            error=result.get("error"),
            metrics=result.get("metrics") if isinstance(result.get("metrics"), dict) else {},
            artifacts=result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {},
        )

    def build(self):
        return self.factory.create(
            system_prompt=(
                "You are the Decision Agent for an admissions system. "
                "Use deterministic packet assembly tools to gather evidence before recommending. "
                "Keep finalization human-approved."
            ),
            tools=[
                self.packet_assembly_tool.as_strands_tool(),
                *self.readiness_evidence_tool.as_strands_tools(),
            ],
        )

    def _build_recommendation_envelope(self, payload: DecisionAgentInput) -> AgentResultEnvelope:
        metrics: dict[str, Any] = {}
        if payload.fit is not None:
            metrics["fit"] = payload.fit
        if payload.credit_estimate is not None:
            metrics["creditEstimate"] = payload.credit_estimate
        if payload.confidence is not None:
            metrics["recommendationConfidence"] = payload.confidence
        if payload.trust_status is not None:
            metrics["trustStatus"] = payload.trust_status
        artifacts: dict[str, Any] = {"decisionId": payload.decision_id}
        if payload.student_id is not None:
            artifacts["studentId"] = payload.student_id
        if payload.transcript_id is not None:
            artifacts["transcriptId"] = payload.transcript_id
        if payload.reason is not None:
            artifacts["recommendationReason"] = payload.reason
        if payload.rationale is not None:
            artifacts["recommendationRationale"] = payload.rationale
        return AgentResultEnvelope(
            status="completed",
            code="decision_recommendation_generated",
            message="Decision recommendation generated.",
            metrics=metrics,
            artifacts=artifacts,
        )

    def record_recommendation(
        self,
        *,
        context: AgentExecutionContext,
        payload: DecisionAgentInput,
        owner_student_id: UUID | None,
    ) -> AgentRunResult:
        context_result = self._build_context_envelope(payload)
        recommendation_result = self._build_recommendation_envelope(payload)
        log_agent_execution_event(
            "agent_run_started",
            agent_name="decision_agent",
            context=context,
            status="running",
            triggerEvent="manual_recommendation",
            decisionId=payload.decision_id,
        )
        if not self.agent_run_service.is_enabled():
            log_agent_execution_event(
                "agent_run_completed",
                agent_name="decision_agent",
                context=context,
                status="completed",
                result_code=recommendation_result.code,
                metrics=recommendation_result.metrics,
            )
            return AgentRunResult(
                agent_name="decision_agent",
                status="completed",
                message=recommendation_result.message,
                result=recommendation_result,
                payload={
                    "context": asdict(context),
                    "input": asdict(payload),
                    "summary": asdict(recommendation_result),
                    "runId": None,
                },
                tool_results=[
                    {"actionType": "assemble_decision_context", "result": asdict(context_result)},
                    {"actionType": "generate_decision_recommendation", "result": asdict(recommendation_result)},
                ],
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
                    agent_name="decision_agent",
                    agent_type="decision",
                    trigger_event="manual_recommendation",
                    status="running",
                    input_json={"context": asdict(context), "input": asdict(payload)},
                )
                log_agent_execution_event(
                    "agent_run_persisted",
                    agent_name="decision_agent",
                    context=context,
                    status="running",
                    run_id=run.id,
                    triggerEvent="manual_recommendation",
                    decisionId=payload.decision_id,
                )
                self.agent_run_service.record_action(
                    session,
                    tenant_id=context.tenant_id,
                    run_id=run.id,
                    student_id=owner_student_id,
                    transcript_id=context.transcript_id,
                    action_type=self.packet_assembly_tool.action_type,
                    tool_name=self.packet_assembly_tool.tool_name,
                    status="completed",
                    input_json=asdict(payload),
                    output_json=asdict(context_result),
                )
                log_agent_execution_event(
                    "agent_action_completed",
                    agent_name="decision_agent",
                    context=context,
                    status="completed",
                    run_id=run.id,
                    action_type=self.packet_assembly_tool.action_type,
                    tool_name=self.packet_assembly_tool.tool_name,
                    result_code=context_result.code,
                    metrics=context_result.metrics,
                )
                self.agent_run_service.record_action(
                    session,
                    tenant_id=context.tenant_id,
                    run_id=run.id,
                    student_id=owner_student_id,
                    transcript_id=context.transcript_id,
                    action_type="generate_decision_recommendation",
                    tool_name="generate_decision_recommendation",
                    status="completed",
                    input_json=asdict(payload),
                    output_json=asdict(recommendation_result),
                )
                log_agent_execution_event(
                    "agent_action_completed",
                    agent_name="decision_agent",
                    context=context,
                    status="completed",
                    run_id=run.id,
                    action_type="generate_decision_recommendation",
                    tool_name="generate_decision_recommendation",
                    result_code=recommendation_result.code,
                    metrics=recommendation_result.metrics,
                )
                self.agent_run_service.complete_run(
                    session,
                    run=run,
                    status="completed",
                    output_json=asdict(recommendation_result),
                )
                if owner_student_id is not None:
                    self.agent_run_service.upsert_student_state(
                        session,
                        tenant_id=context.tenant_id,
                        student_id=owner_student_id,
                        current_owner_agent="decision_agent",
                        state_json={
                            "last_decision_action": "generate_recommendation",
                            "decisionId": payload.decision_id,
                        },
                        last_decision_run_id=run.id,
                    )
        log_agent_execution_event(
            "agent_run_completed",
            agent_name="decision_agent",
            context=context,
            status="completed",
            run_id=run.id,
            result_code=recommendation_result.code,
            metrics=recommendation_result.metrics,
        )
        return AgentRunResult(
            agent_name="decision_agent",
            status="completed",
            message=recommendation_result.message,
            result=recommendation_result,
            payload={
                "context": asdict(context),
                "input": asdict(payload),
                "summary": asdict(recommendation_result),
                "runId": str(run.id),
            },
            tool_results=[
                {"actionType": "assemble_decision_context", "result": asdict(context_result)},
                {"actionType": "generate_decision_recommendation", "result": asdict(recommendation_result)},
            ],
        )
