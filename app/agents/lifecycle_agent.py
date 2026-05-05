from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.agents.base import AgentResultEnvelope, AgentRunResult, StrandsAgentFactory
from app.agents.tools import LifecycleCohortTool, LifecycleInterventionTool, LifecycleScoringTool


@dataclass(slots=True)
class LifecycleStudentInput:
    student_id: str
    student_name: str
    stage: str
    risk: str | None = None
    fit_score: int | None = None
    deposit_likelihood: int | None = None
    melt_risk: int | None = None
    missing_milestones: list[str] = field(default_factory=list)
    next_best_action: str | None = None


@dataclass(slots=True)
class LifecycleAgentInput:
    cohort: str = "admit_to_deposit"
    students: list[LifecycleStudentInput] = field(default_factory=list)


@dataclass(slots=True)
class LifecycleRecommendationOutput:
    student_id: str
    deposit_likelihood: int
    melt_risk: int
    recommended_action: str
    rationale: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LifecycleAgentOutput:
    cohort: str
    recommendations: list[LifecycleRecommendationOutput] = field(default_factory=list)


class LifecycleAgent:
    """Coordinates admit-to-deposit lifecycle recommendations and intervention logging."""

    def __init__(
        self,
        *,
        factory: StrandsAgentFactory | None = None,
        tools: list[Callable[..., Any]] | None = None,
        cohort_tool: LifecycleCohortTool | None = None,
        scoring_tool: LifecycleScoringTool | None = None,
        intervention_tool: LifecycleInterventionTool | None = None,
    ) -> None:
        self.factory = factory or StrandsAgentFactory()
        self.tools = tools or []
        self.cohort_tool = cohort_tool or LifecycleCohortTool()
        self.scoring_tool = scoring_tool or LifecycleScoringTool()
        self.intervention_tool = intervention_tool or LifecycleInterventionTool()

    def build(self):
        return self.factory.create(
            system_prompt=(
                "You are the Lifecycle Agent for an admissions system. "
                "Use deterministic cohort, deposit likelihood, melt risk, and intervention tools "
                "to recommend admit-to-deposit outreach. Keep outreach logging backend-owned and auditable."
            ),
            tools=[
                *self.cohort_tool.as_strands_tools(),
                *self.scoring_tool.as_strands_tools(),
                *self.intervention_tool.as_strands_tools(),
                *self.tools,
            ],
        )

    def build_recommendation_result(
        self,
        *,
        payload: LifecycleAgentInput,
        output: LifecycleAgentOutput,
    ) -> AgentRunResult:
        result = AgentResultEnvelope(
            status="completed",
            code="lifecycle_recommendations_generated",
            message="Lifecycle recommendations generated.",
            metrics={
                "studentCount": len(payload.students),
                "recommendationCount": len(output.recommendations),
            },
            artifacts={
                "cohort": output.cohort,
                "studentIds": [item.student_id for item in output.recommendations],
            },
        )
        return AgentRunResult(
            agent_name="lifecycle_agent",
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
                    "actionType": "generate_lifecycle_recommendations",
                    "result": asdict(result),
                }
            ],
        )
