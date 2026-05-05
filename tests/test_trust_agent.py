from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.agents.base import AgentExecutionContext
from app.agents.trust_agent import TrustAgent, TrustAgentInput
from app.agents.tools.trust_tools import TrustCaseTool, TrustContextTool


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return self

    def flush(self):
        return None


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


class _FakeTrustContextTool:
    def __init__(self) -> None:
        self.tools = [object(), object(), object()]

    def as_strands_tools(self):
        return self.tools


class _FakeTrustCaseTool:
    def __init__(self) -> None:
        self.tools = [object(), object(), object()]

    def as_strands_tools(self):
        return self.tools


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        tenant_id=uuid4(),
        student_id=uuid4(),
        transcript_id=uuid4(),
        actor_user_id=uuid4(),
        correlation_id="trust:test",
    )


def test_trust_context_tool_serializes_identity_context():
    student_id = uuid4()
    transcript_id = uuid4()
    document_id = uuid4()
    matched_at = SimpleNamespace(isoformat=lambda: "2026-05-05T18:11:10+00:00")
    student = SimpleNamespace(
        id=student_id,
        external_student_id="STU-1",
        preferred_name=None,
        first_name="Mira",
        last_name="Holloway",
    )
    transcript = SimpleNamespace(
        id=transcript_id,
        document_upload_id=document_id,
        matched_at=matched_at,
        matched_by="system",
    )
    demographics = SimpleNamespace(
        student_first_name="Mira",
        student_last_name="Holloway",
        student_external_id="STU-1",
    )
    tool = TrustContextTool(session_factory=lambda: None)

    result = tool._student_name(student, demographics)
    iso = tool._iso(matched_at)

    assert result == "Mira Holloway"
    assert iso == "2026-05-05T18:11:10Z"
    assert {
        "status": "matched",
        "transcriptId": str(transcript.id),
        "documentId": str(transcript.document_upload_id),
        "studentId": str(student.id),
        "studentExternalId": student.external_student_id,
        "studentName": tool._student_name(student, demographics),
        "transcriptStudentName": tool._demographic_name(demographics),
        "transcriptStudentExternalId": demographics.student_external_id,
        "matchedAt": tool._iso(transcript.matched_at),
        "matchedBy": transcript.matched_by,
    }["status"] == "matched"


def test_trust_agent_build_registers_context_tools():
    factory = _FakeFactory()
    trust_context_tool = _FakeTrustContextTool()
    trust_case_tool = _FakeTrustCaseTool()
    agent = TrustAgent(
        factory=factory,
        agent_run_service=_FakeAgentRunService(),
        trust_context_tool=trust_context_tool,
        trust_case_tool=trust_case_tool,
    )

    built = agent.build()

    assert built["tools"] == [*trust_context_tool.tools, *trust_case_tool.tools]
    assert "Trust Agent" in built["system_prompt"]


def test_trust_case_tool_serializes_case_result():
    tool = TrustCaseTool(session_factory=lambda: None)
    transcript = SimpleNamespace(
        id=uuid4(),
        student_id=uuid4(),
        document_upload_id=uuid4(),
    )
    flag = SimpleNamespace(
        id=uuid4(),
        flag_type="issuer_mismatch",
        severity="high",
    )

    result = tool._case_result(
        status="escalated",
        code="trust_case_escalated",
        transcript=transcript,
        flag=flag,
        reason="Issuer mismatch requires review.",
    )

    assert result == {
        "status": "escalated",
        "code": "trust_case_escalated",
        "trustFlagId": str(flag.id),
        "transcriptId": str(transcript.id),
        "studentId": str(transcript.student_id),
        "documentId": str(transcript.document_upload_id),
        "flagType": "issuer_mismatch",
        "severity": "high",
        "reason": "Issuer mismatch requires review.",
    }


def test_trust_agent_records_quarantine_result_and_state():
    context = _context()
    service = _FakeAgentRunService()
    agent = TrustAgent(agent_run_service=service)
    payload = TrustAgentInput(
        action="quarantine_document",
        document_id="doc-1",
        transcript_id=str(context.transcript_id),
        student_id=str(context.student_id),
        reason="Document quarantined by reviewer.",
    )

    result = agent.record_action(
        context=context,
        payload=payload,
        trigger_event="manual_quarantine",
        action_type="quarantine_document",
        tool_name="quarantine_document",
        code="trust_document_quarantined",
        message="Document quarantined.",
        owner_student_id=context.student_id,
    )

    assert result.status == "completed"
    assert result.result is not None
    assert result.result.code == "trust_document_quarantined"
    run = next(iter(service.runs.values()))
    assert run.agent_name == "trust_agent"
    assert run.output_json["code"] == "trust_document_quarantined"
    assert service.actions[0]["output_json"]["code"] == "trust_document_quarantined"
    assert service.student_states[0]["last_trust_run_id"] == run.id


def test_trust_agent_records_match_confirmation_with_target_student():
    context = _context()
    service = _FakeAgentRunService()
    agent = TrustAgent(agent_run_service=service)
    target_student_id = uuid4()
    payload = TrustAgentInput(
        action="confirm_match",
        document_id="doc-2",
        transcript_id=str(context.transcript_id),
        student_id=str(context.student_id),
        target_student_id=str(target_student_id),
        reason="Document matched to student by reviewer.",
    )

    result = agent.record_action(
        context=context,
        payload=payload,
        trigger_event="manual_match_confirm",
        action_type="confirm_document_match",
        tool_name="confirm_document_match",
        code="document_match_confirmed",
        message="Document match confirmed.",
        owner_student_id=target_student_id,
    )

    assert result.result is not None
    assert result.result.code == "document_match_confirmed"
    assert result.result.metrics["targetStudentAssigned"] is True
    assert result.result.artifacts["targetStudentId"] == str(target_student_id)
