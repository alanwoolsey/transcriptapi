from app.agents.lifecycle_agent import (
    LifecycleAgent,
    LifecycleAgentInput,
    LifecycleAgentOutput,
    LifecycleRecommendationOutput,
    LifecycleStudentInput,
)
from app.agents.tools import LifecycleCohortTool, LifecycleInterventionTool, LifecycleScoringTool


class _FakeFactory:
    def __init__(self) -> None:
        self.created: dict | None = None

    def create(self, **kwargs):
        self.created = kwargs
        return kwargs


class _FakeToolSet:
    def __init__(self, count: int) -> None:
        self.strands_tools = [object() for _ in range(count)]

    def as_strands_tools(self):
        return self.strands_tools


def test_lifecycle_agent_build_registers_tools_and_responsibilities():
    factory = _FakeFactory()
    cohort_tool = _FakeToolSet(1)
    scoring_tool = _FakeToolSet(2)
    intervention_tool = _FakeToolSet(2)
    extra_tool = object()
    agent = LifecycleAgent(
        factory=factory,
        tools=[extra_tool],
        cohort_tool=cohort_tool,
        scoring_tool=scoring_tool,
        intervention_tool=intervention_tool,
    )

    built = agent.build()

    assert built["tools"] == [*cohort_tool.strands_tools, *scoring_tool.strands_tools, *intervention_tool.strands_tools, extra_tool]
    assert "Lifecycle Agent" in built["system_prompt"]
    assert "admit-to-deposit" in built["system_prompt"]
    assert "melt risk" in built["system_prompt"]
    assert "outreach logging" in built["system_prompt"]


def test_lifecycle_agent_builds_normalized_recommendation_result():
    agent = LifecycleAgent(
        factory=_FakeFactory(),
        cohort_tool=_FakeToolSet(0),
        scoring_tool=_FakeToolSet(0),
        intervention_tool=_FakeToolSet(0),
    )
    payload = LifecycleAgentInput(
        students=[
            LifecycleStudentInput(
                student_id="student-1",
                student_name="Avery Carter",
                stage="Admitted",
                risk="Low",
                fit_score=88,
                deposit_likelihood=72,
                melt_risk=20,
            )
        ]
    )
    output = LifecycleAgentOutput(
        cohort="admit_to_deposit",
        recommendations=[
            LifecycleRecommendationOutput(
                student_id="student-1",
                deposit_likelihood=72,
                melt_risk=20,
                recommended_action="Send deposit reminder.",
                rationale=["High fit and no missing milestones."],
            )
        ],
    )

    result = agent.build_recommendation_result(payload=payload, output=output)

    assert result.agent_name == "lifecycle_agent"
    assert result.result is not None
    assert result.result.code == "lifecycle_recommendations_generated"
    assert result.result.metrics["studentCount"] == 1
    assert result.result.metrics["recommendationCount"] == 1
    assert result.result.artifacts["cohort"] == "admit_to_deposit"
    assert result.result.artifacts["studentIds"] == ["student-1"]
    assert result.payload["output"]["recommendations"][0]["recommended_action"] == "Send deposit reminder."
    assert result.tool_results[0]["actionType"] == "generate_lifecycle_recommendations"


def test_lifecycle_cohort_tool_filters_admit_to_deposit_students():
    tool = LifecycleCohortTool()

    result = tool.load_admit_to_deposit_cohort(
        {
            "students": [
                {"id": "student-1", "name": "Avery Carter", "stage": "Admitted", "fitScore": 88, "depositLikelihood": 72},
                {"id": "student-2", "name": "Mira Holloway", "stage": "Inquiry", "fitScore": 91, "depositLikelihood": 64},
                {"id": "student-3", "name": "Taylor Reed", "stage": "Deposited", "fitScore": 75, "depositLikelihood": 80},
            ]
        }
    )

    assert result["code"] == "admit_to_deposit_cohort_loaded"
    assert result["metrics"]["studentCount"] == 2
    assert result["metrics"]["highFitCount"] == 1
    assert result["artifacts"]["studentIds"] == ["student-1", "student-3"]


def test_lifecycle_scoring_tool_scores_deposit_and_melt_risk():
    tool = LifecycleScoringTool()
    payload = {
        "students": [
            {
                "studentId": "student-1",
                "fitScore": 88,
                "risk": "low",
                "missingMilestones": ["orientation", "housing form"],
            },
            {
                "studentId": "student-2",
                "fitScore": 82,
                "risk": "high",
                "depositLikelihood": 20,
                "missingMilestones": [],
            },
        ]
    }

    deposit = tool.score_deposit_likelihood(payload)
    melt = tool.score_melt_risk(payload)

    assert deposit["code"] == "deposit_likelihood_scored"
    assert deposit["metrics"]["studentCount"] == 2
    assert deposit["artifacts"]["students"][0]["depositLikelihood"] == 70
    assert deposit["artifacts"]["students"][1]["depositLikelihood"] == 20
    assert melt["code"] == "melt_risk_scored"
    assert melt["metrics"]["highRiskCount"] == 1
    assert melt["artifacts"]["students"][0]["meltRisk"] == 36
    assert melt["artifacts"]["students"][1]["meltRisk"] == 55


def test_lifecycle_intervention_tool_logs_intervention_and_outreach():
    tool = LifecycleInterventionTool()

    intervention = tool.log_lifecycle_intervention(
        {
            "studentId": "student-1",
            "recommendedAction": "Schedule advisor call.",
            "channel": "task",
            "note": "Needs orientation help.",
        }
    )
    outreach = tool.log_lifecycle_outreach(
        {
            "studentId": "student-1",
            "recommendedAction": "Send deposit reminder.",
            "channel": "email",
        }
    )

    assert intervention["code"] == "lifecycle_intervention_logged"
    assert intervention["metrics"]["hasNote"] is True
    assert intervention["artifacts"]["actionType"] == "intervention"
    assert intervention["artifacts"]["studentId"] == "student-1"
    assert intervention["artifacts"]["loggedAt"]
    assert outreach["code"] == "lifecycle_outreach_logged"
    assert outreach["metrics"]["hasNote"] is False
    assert outreach["artifacts"]["actionType"] == "outreach"
    assert outreach["artifacts"]["channel"] == "email"
