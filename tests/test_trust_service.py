from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.db.models import TrustFlag
from app.services.trust_service import TrustService


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


class _FakeSession:
    def __init__(self, transcript, *, assignee=None, open_flags=None):
        self.transcript = transcript
        self.assignee = assignee
        self.open_flags = list(open_flags or [])
        self.added: list[object] = []
        self.committed = False
        self._execute_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _statement):
        self._execute_calls += 1
        if self._execute_calls == 1:
            return _FakeResult(self.transcript)
        if self._execute_calls == 2 and self.assignee is not None:
            return _FakeResult(self.assignee)
        return _FakeResult(self.open_flags)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True


class _RecorderTrustAgent:
    def __init__(self):
        self.calls: list[dict] = []

    def record_action(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(status="completed", result=SimpleNamespace(code=kwargs["code"]))


def _service_with_session(session: _FakeSession, recorder: _RecorderTrustAgent) -> TrustService:
    return TrustService(session_factory=lambda: (lambda: session))


def _transcript():
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        student_id=uuid4(),
        document_upload_id=uuid4(),
        is_fraudulent=False,
        updated_at=None,
    )


def test_block_case_marks_transcript_and_records_agent_action():
    transcript = _transcript()
    session = _FakeSession(transcript, open_flags=[])
    recorder = _RecorderTrustAgent()
    service = _service_with_session(session, recorder)
    service.trust_agent = recorder

    response = service.block_case(transcript.tenant_id, str(transcript.id), uuid4(), "Hold pending verification")

    assert response.success is True
    assert response.status == "blocked"
    assert transcript.is_fraudulent is True
    assert session.committed is True
    assert len(session.added) == 1
    assert isinstance(session.added[0], TrustFlag)
    assert session.added[0].status == "blocked"
    assert session.added[0].flag_type == "manual_block"
    assert session.added[0].reason == "Hold pending verification"
    assert recorder.calls[0]["code"] == "trust_case_blocked"


def test_unblock_case_resolves_open_flags_and_clears_fraud():
    transcript = _transcript()
    transcript.is_fraudulent = True
    open_flag = SimpleNamespace(
        status="blocked",
        severity="high",
        reason="Hold",
        resolved_by_user_id=None,
        resolved_at=None,
        resolution_notes=None,
    )
    session = _FakeSession(transcript, open_flags=[open_flag])
    recorder = _RecorderTrustAgent()
    service = _service_with_session(session, recorder)
    service.trust_agent = recorder

    response = service.unblock_case(transcript.tenant_id, str(transcript.id), uuid4(), "False positive")

    assert response.success is True
    assert response.status == "unblocked"
    assert transcript.is_fraudulent is False
    assert open_flag.status == "resolved"
    assert open_flag.resolved_at is not None
    assert open_flag.resolution_notes == "False positive"
    assert recorder.calls[0]["code"] == "trust_case_unblocked"


def test_assign_case_creates_assignment_flag_when_no_open_flags():
    transcript = _transcript()
    assignee = SimpleNamespace(id=uuid4(), display_name="Taylor Reed")
    session = _FakeSession(transcript, assignee=assignee, open_flags=[])
    recorder = _RecorderTrustAgent()
    service = _service_with_session(session, recorder)
    service.trust_agent = recorder

    response = service.assign_case(
        transcript.tenant_id,
        str(transcript.id),
        uuid4(),
        str(assignee.id),
        "Assigning for deeper investigation",
    )

    assert response.success is True
    assert response.status == "assigned"
    assert len(session.added) == 1
    assert isinstance(session.added[0], TrustFlag)
    assert session.added[0].flag_type == "manual_assignment"
    assert session.added[0].assigned_to_user_id == assignee.id
    assert session.added[0].reason == "Assigning for deeper investigation"
    assert recorder.calls[0]["code"] == "trust_case_assigned"


def test_resolve_case_marks_false_positive_as_resolved_and_clears_fraud():
    transcript = _transcript()
    transcript.is_fraudulent = True
    actor_user_id = uuid4()
    open_flag = SimpleNamespace(
        status="open",
        severity="high",
        reason="Issuer mismatch",
        resolved_by_user_id=None,
        resolved_at=None,
        resolution_notes=None,
    )
    session = _FakeSession(transcript, open_flags=[open_flag])
    recorder = _RecorderTrustAgent()
    service = _service_with_session(session, recorder)
    service.trust_agent = recorder

    response = service.resolve_case(transcript.tenant_id, str(transcript.id), actor_user_id, "False positive after review")

    assert response.success is True
    assert response.status == "resolved"
    assert transcript.is_fraudulent is False
    assert open_flag.status == "resolved"
    assert open_flag.resolved_by_user_id == actor_user_id
    assert open_flag.resolved_at is not None
    assert open_flag.resolution_notes == "False positive after review"
    assert recorder.calls[0]["code"] == "trust_case_resolved"


def test_escalate_case_marks_transcript_fraudulent_and_creates_flag_when_missing():
    transcript = _transcript()
    session = _FakeSession(transcript, open_flags=[])
    recorder = _RecorderTrustAgent()
    service = _service_with_session(session, recorder)
    service.trust_agent = recorder

    response = service.escalate_case(transcript.tenant_id, str(transcript.id), uuid4(), "Needs secondary trust review")

    assert response.success is True
    assert response.status == "escalated"
    assert transcript.is_fraudulent is True
    assert len(session.added) == 1
    assert isinstance(session.added[0], TrustFlag)
    assert session.added[0].flag_type == "manual_escalation"
    assert session.added[0].status == "escalated"
    assert session.added[0].reason == "Needs secondary trust review"
    assert recorder.calls[0]["code"] == "trust_case_escalated"


def test_build_trust_summary_explains_blocking_state_and_recommended_action():
    service = TrustService(session_factory=lambda: (lambda: None))

    summary = service._build_trust_summary(
        severity="High",
        signal="Issuer Mismatch",
        evidence="Issuer name does not match expected sender.",
        status="Blocked",
        trust_blocked=True,
        owner={"id": "user-1", "name": "Taylor Reed"},
        latest_result_code="trust_case_blocked",
    )

    assert summary.riskLevel == "high"
    assert summary.summary == "Issuer Mismatch is blocked. Student progression is currently blocked."
    assert summary.recommendedAction == "Review evidence and resolve, unblock, or keep escalated."
    assert "Issuer name does not match expected sender." in summary.rationale
    assert "trust_case_blocked" in summary.rationale
    assert "Taylor Reed" in summary.rationale
