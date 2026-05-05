from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.agents.base import AgentExecutionContext
from app.agents.decision_agent import DecisionAgent, DecisionAgentInput
from app.agents.tools import DecisionPacketAssemblyTool, DecisionReadinessEvidenceTool


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return self


class _FakeAgentRunService:
    def __init__(self) -> None:
        self.runs: dict = {}
        self.actions: list[dict] = []
        self.student_states: list[dict] = []
        self._session_factory = lambda: _FakeSession()

    def session_factory(self):
        return self._session_factory

    def is_enabled(self) -> bool:
        return True

    def create_run(self, session, **kwargs):
        run = SimpleNamespace(
            id=uuid4(),
            tenant_id=kwargs["tenant_id"],
            student_id=kwargs.get("student_id"),
            transcript_id=kwargs.get("transcript_id"),
            actor_user_id=kwargs.get("actor_user_id"),
            agent_name=kwargs["agent_name"],
            agent_type=kwargs.get("agent_type"),
            trigger_event=kwargs.get("trigger_event"),
            status=kwargs["status"],
            input_json=kwargs["input_json"],
            output_json={},
            correlation_id=kwargs.get("correlation_id"),
            error_message=None,
            started_at=object(),
            completed_at=None,
            updated_at=None,
        )
        self.runs[run.id] = run
        return run

    def record_action(self, session, **kwargs):
        self.actions.append(kwargs)
        return kwargs

    def complete_run(self, session, *, run, status, output_json=None, error_message=None):
        run.status = status
        run.output_json = output_json or {}
        run.error_message = error_message
        run.completed_at = object()
        return run

    def upsert_student_state(self, session, **kwargs):
        self.student_states.append(kwargs)
        return kwargs


class _FakeFactory:
    def __init__(self) -> None:
        self.created: dict | None = None

    def create(self, **kwargs):
        self.created = kwargs
        return kwargs


class _FakePacketAssemblyTool:
    action_type = "assemble_decision_context"
    tool_name = "assemble_decision_context"

    def __init__(self) -> None:
        self.strands_tool = object()

    def assemble_decision_context(self, payload):
        return DecisionPacketAssemblyTool().assemble_decision_context(payload)

    def as_strands_tool(self):
        return self.strands_tool


class _FakeReadinessEvidenceTool:
    def __init__(self) -> None:
        self.strands_tools = [object(), object(), object()]

    def as_strands_tools(self):
        return self.strands_tools


def test_decision_packet_assembly_tool_builds_normalized_context():
    tool = DecisionPacketAssemblyTool()

    result = tool.assemble_decision_context(
        {
            "decision_id": "decision-1",
            "student_id": "student-1",
            "transcript_id": "transcript-1",
            "status": "Draft",
            "readiness": "Ready for review",
            "trust_status": "Clear",
            "trust_signal_count": 1,
            "active_trust_signal_count": 0,
            "document_count": 3,
            "institution": "Harbor Gate University",
            "gpa": 3.42,
            "credits_earned": 42.0,
            "parser_confidence": 0.96,
        }
    )

    assert result["code"] == "decision_context_assembled"
    assert result["metrics"]["readiness"] == "Ready for review"
    assert result["metrics"]["trustSignalCount"] == 1
    assert result["artifacts"]["institution"] == "Harbor Gate University"
    assert result["artifacts"]["parserConfidence"] == 0.96


def test_decision_readiness_evidence_tool_builds_normalized_results():
    tool = DecisionReadinessEvidenceTool()
    payload = {
        "decision_id": "decision-1",
        "student_id": "student-1",
        "transcript_id": "transcript-1",
        "status": "Draft",
        "readiness": "Ready for review",
        "readiness_reason": "Checklist complete and transcript confidence is high.",
        "trust_status": "Clear",
        "trust_signal_count": 1,
        "active_trust_signal_count": 0,
        "document_count": 3,
        "institution": "Harbor Gate University",
        "gpa": 3.42,
        "credits_earned": 42.0,
        "parser_confidence": 0.96,
    }

    readiness = tool.load_decision_readiness(payload)
    trust = tool.load_decision_trust_status(payload)
    evidence = tool.load_decision_supporting_evidence(payload)

    assert readiness["code"] == "decision_readiness_loaded"
    assert readiness["metrics"]["readiness"] == "Ready for review"
    assert readiness["artifacts"]["readinessReason"] == "Checklist complete and transcript confidence is high."
    assert trust["code"] == "decision_trust_status_loaded"
    assert trust["metrics"]["trustStatus"] == "Clear"
    assert trust["metrics"]["activeTrustSignalCount"] == 0
    assert evidence["code"] == "decision_supporting_evidence_loaded"
    assert evidence["metrics"]["documentCount"] == 3
    assert evidence["artifacts"]["institution"] == "Harbor Gate University"
    assert evidence["artifacts"]["parserConfidence"] == 0.96


def test_decision_agent_build_registers_packet_and_context_tools():
    factory = _FakeFactory()
    packet_assembly_tool = _FakePacketAssemblyTool()
    readiness_evidence_tool = _FakeReadinessEvidenceTool()
    agent = DecisionAgent(
        factory=factory,
        agent_run_service=_FakeAgentRunService(),
        packet_assembly_tool=packet_assembly_tool,
        readiness_evidence_tool=readiness_evidence_tool,
    )

    built = agent.build()

    assert built["tools"] == [packet_assembly_tool.strands_tool, *readiness_evidence_tool.strands_tools]
    assert "Decision Agent" in built["system_prompt"]


def test_decision_agent_records_recommendation_result():
    context = AgentExecutionContext(
        tenant_id=uuid4(),
        student_id=uuid4(),
        transcript_id=uuid4(),
        actor_user_id=uuid4(),
        correlation_id="decision:test",
    )
    service = _FakeAgentRunService()
    agent = DecisionAgent(agent_run_service=service)
    payload = DecisionAgentInput(
        decision_id=str(context.transcript_id),
        student_id=str(context.student_id),
        transcript_id=str(context.transcript_id),
        status="Draft",
        readiness="Ready for review",
        readiness_reason="Checklist complete and transcript confidence is high.",
        fit=88,
        credit_estimate=42,
        trust_status="Clear",
        trust_signal_count=1,
        active_trust_signal_count=0,
        institution="Harbor Gate University",
        gpa=3.42,
        credits_earned=42.0,
        parser_confidence=0.96,
        document_count=3,
        reason="Checklist complete and transcript confidence is high.",
        confidence=96,
        rationale=[
            "Checklist complete and transcript confidence is high.",
            "No active trust signals are blocking review.",
        ],
    )

    result = agent.record_recommendation(
        context=context,
        payload=payload,
        owner_student_id=context.student_id,
    )

    assert result.status == "completed"
    assert result.result is not None
    assert result.result.code == "decision_recommendation_generated"
    assert result.result.metrics["fit"] == 88
    assert result.result.metrics["creditEstimate"] == 42
    assert result.result.metrics["recommendationConfidence"] == 96
    assert result.result.metrics["trustStatus"] == "Clear"
    assert result.result.artifacts["recommendationReason"] == "Checklist complete and transcript confidence is high."
    assert result.result.artifacts["recommendationRationale"] == [
        "Checklist complete and transcript confidence is high.",
        "No active trust signals are blocking review.",
    ]
    assert len(result.tool_results) == 2
    assert result.tool_results[0]["actionType"] == "assemble_decision_context"
    assert result.tool_results[0]["result"]["code"] == "decision_context_assembled"
    assert result.tool_results[0]["result"]["metrics"]["readiness"] == "Ready for review"
    assert result.tool_results[0]["result"]["metrics"]["trustSignalCount"] == 1
    assert result.tool_results[0]["result"]["metrics"]["documentCount"] == 3
    assert result.tool_results[0]["result"]["artifacts"]["institution"] == "Harbor Gate University"
    assert result.tool_results[0]["result"]["artifacts"]["parserConfidence"] == 0.96
    assert result.tool_results[1]["actionType"] == "generate_decision_recommendation"
    assert result.payload["runId"] is not None
    run = next(iter(service.runs.values()))
    assert run.agent_name == "decision_agent"
    assert run.output_json["code"] == "decision_recommendation_generated"
    assert service.actions[0]["output_json"]["code"] == "decision_context_assembled"
    assert service.actions[1]["output_json"]["code"] == "decision_recommendation_generated"
    assert service.student_states[0]["last_decision_run_id"] == run.id
