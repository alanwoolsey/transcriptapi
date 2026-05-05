from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.agents.base import AgentResultEnvelope, AgentRunResult, StrandsAgentFactory
from app.agents.tools import OrchestratorProjectedWorkTool


@dataclass(slots=True)
class OrchestratorWorkItemInput:
    id: str
    student_id: str
    student_name: str
    section: str
    priority: str
    priority_score: int | None = None
    current_owner_agent: str | None = None
    current_stage: str | None = None
    recommended_agent: str | None = None
    queue_group: str | None = None
    reason_to_act_code: str | None = None
    suggested_action_code: str | None = None


@dataclass(slots=True)
class OrchestratorGroupOutput:
    key: str
    label: str
    total: int
    student_ids: list[str] = field(default_factory=list)
    next_agent: str | None = None
    reason: str | None = None
    action_label: str | None = None


@dataclass(slots=True)
class OrchestratorAgentInput:
    limit: int
    total_candidates: int
    items: list[OrchestratorWorkItemInput] = field(default_factory=list)


@dataclass(slots=True)
class OrchestratorAgentOutput:
    total_students: int
    groups: list[OrchestratorGroupOutput] = field(default_factory=list)


class OrchestratorAgent:
    """Coordinates read-only work prioritization and handoff recommendations."""

    def __init__(
        self,
        *,
        factory: StrandsAgentFactory | None = None,
        tools: list[Callable[..., Any]] | None = None,
        projected_work_tool: OrchestratorProjectedWorkTool | None = None,
    ) -> None:
        self.factory = factory or StrandsAgentFactory()
        self.tools = tools or []
        self.projected_work_tool = projected_work_tool or OrchestratorProjectedWorkTool()

    def build(self):
        return self.factory.create(
            system_prompt=(
                "You are the Orchestrator Agent for an admissions system. "
                "Use projected work-state tools to prioritize today's work, explain queue grouping, "
                "and recommend handoffs to document, trust, or decision agents. "
                "Do not mutate student records directly; routing and execution remain backend-owned."
            ),
            tools=[
                *self.projected_work_tool.as_strands_tools(),
                *self.tools,
            ],
        )

    def build_prioritization_result(
        self,
        *,
        payload: OrchestratorAgentInput,
        output: OrchestratorAgentOutput,
        board_snapshot: dict[str, Any] | None = None,
    ) -> AgentRunResult:
        result = AgentResultEnvelope(
            status="completed",
            code="today_work_prioritized",
            message="Today's work prioritized and grouped.",
            metrics={
                "totalStudents": output.total_students,
                "groupCount": len(output.groups),
            },
            artifacts={
                "groupKeys": [group.key for group in output.groups],
                "recommendedAgents": sorted({group.next_agent for group in output.groups if group.next_agent}),
                **({"boardSnapshot": board_snapshot} if board_snapshot is not None else {}),
            },
        )
        return AgentRunResult(
            agent_name="orchestrator_agent",
            status="completed",
            message=result.message,
            result=result,
            payload={
                "input": asdict(payload),
                "output": asdict(output),
                "summary": asdict(result),
            },
            tool_results=[
                {
                    "actionType": "prioritize_today_work",
                    "result": asdict(result),
                }
            ],
        )
