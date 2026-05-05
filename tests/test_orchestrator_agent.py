from app.agents.orchestrator_agent import (
    OrchestratorAgent,
    OrchestratorAgentInput,
    OrchestratorAgentOutput,
    OrchestratorGroupOutput,
    OrchestratorWorkItemInput,
)
from app.agents.tools import OrchestratorProjectedWorkTool


class _FakeFactory:
    def __init__(self) -> None:
        self.created: dict | None = None

    def create(self, **kwargs):
        self.created = kwargs
        return kwargs


class _FakeProjectedWorkTool:
    def __init__(self) -> None:
        self.strands_tools = [object(), object(), object()]

    def as_strands_tools(self):
        return self.strands_tools


def test_orchestrator_agent_build_defines_responsibilities():
    factory = _FakeFactory()
    tool = object()
    projected_work_tool = _FakeProjectedWorkTool()
    agent = OrchestratorAgent(factory=factory, tools=[tool], projected_work_tool=projected_work_tool)

    built = agent.build()

    assert built["tools"] == [*projected_work_tool.strands_tools, tool]
    assert "Orchestrator Agent" in built["system_prompt"]
    assert "prioritize today's work" in built["system_prompt"]
    assert "document, trust, or decision agents" in built["system_prompt"]
    assert "Do not mutate student records directly" in built["system_prompt"]


def test_orchestrator_projected_work_tool_builds_normalized_results():
    tool = OrchestratorProjectedWorkTool()
    payload = {
        "limit": 2,
        "items": [
            {
                "id": "work-1",
                "studentId": "student-1",
                "studentName": "Avery Carter",
                "section": "ready",
                "priority": "urgent",
                "priorityScore": 88,
                "currentOwnerAgent": "document_agent",
                "currentStage": "routed",
                "recommendedAgent": "decision_agent",
                "queueGroup": "decision_review",
                "reasonToAct": {"code": "ready_for_decision", "label": "Ready for decision"},
                "suggestedAction": {"code": "review_recommendation", "label": "Review recommendation"},
            },
            {
                "id": "work-2",
                "studentId": "student-2",
                "studentName": "Mira Holloway",
                "section": "exceptions",
                "priority": "today",
                "priorityScore": 75,
                "recommendedAgent": "trust_agent",
                "queueGroup": "trust_review",
                "reasonToAct": {"code": "trust_block", "label": "Trust hold"},
                "suggestedAction": {"code": "review_trust", "label": "Review trust"},
            },
        ],
    }

    queue = tool.load_projected_work_queue(payload)
    ownership = tool.load_work_ownership(payload)
    priority = tool.load_work_priority(payload)

    assert queue["code"] == "projected_work_queue_loaded"
    assert queue["metrics"]["totalItems"] == 2
    assert queue["metrics"]["queueGroupCount"] == 2
    assert queue["artifacts"]["queueGroups"] == ["decision_review", "trust_review"]
    assert queue["artifacts"]["items"][0]["recommendedAgent"] == "decision_agent"
    assert ownership["code"] == "work_ownership_loaded"
    assert ownership["artifacts"]["currentOwnerAgents"] == ["document_agent"]
    assert ownership["artifacts"]["recommendedAgents"] == ["decision_agent", "trust_agent"]
    assert priority["code"] == "work_priority_loaded"
    assert priority["metrics"]["urgentCount"] == 1
    assert priority["metrics"]["maxPriorityScore"] == 88
    assert priority["artifacts"]["items"][0]["reasonToActCode"] == "ready_for_decision"


def test_orchestrator_agent_builds_normalized_prioritization_result():
    agent = OrchestratorAgent(factory=_FakeFactory())
    payload = OrchestratorAgentInput(
        limit=25,
        total_candidates=2,
        items=[
            OrchestratorWorkItemInput(
                id="work-1",
                student_id="student-1",
                student_name="Avery Carter",
                section="ready",
                priority="urgent",
                priority_score=88,
                recommended_agent="decision_agent",
                queue_group="decision_review",
                reason_to_act_code="ready_for_decision",
                suggested_action_code="review_recommendation",
            )
        ],
    )
    output = OrchestratorAgentOutput(
        total_students=1,
        groups=[
            OrchestratorGroupOutput(
                key="decision_review",
                label="Decision Review",
                total=1,
                student_ids=["student-1"],
                next_agent="decision_agent",
                reason="Ready for decision review.",
                action_label="Route to decision review",
            )
        ],
    )

    result = agent.build_prioritization_result(
        payload=payload,
        output=output,
        board_snapshot={"groups": [], "total": 1},
    )

    assert result.agent_name == "orchestrator_agent"
    assert result.result is not None
    assert result.result.code == "today_work_prioritized"
    assert result.result.metrics["totalStudents"] == 1
    assert result.result.metrics["groupCount"] == 1
    assert result.result.artifacts["groupKeys"] == ["decision_review"]
    assert result.result.artifacts["recommendedAgents"] == ["decision_agent"]
    assert result.result.artifacts["boardSnapshot"] == {"groups": [], "total": 1}
    assert result.payload["input"]["items"][0]["student_id"] == "student-1"
    assert result.payload["output"]["groups"][0]["next_agent"] == "decision_agent"
    assert result.tool_results[0]["actionType"] == "prioritize_today_work"
