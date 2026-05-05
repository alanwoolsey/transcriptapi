from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.services.agent_run_service import AgentRunService


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1


def test_agent_run_service_sanitizes_json_payloads_before_flush():
    session = _FakeSession()
    service = AgentRunService(session_factory=lambda: None)
    tenant_id = uuid4()
    student_id = uuid4()
    transcript_id = uuid4()
    actor_user_id = uuid4()
    created_at = datetime(2026, 5, 5, 18, 11, 10, tzinfo=timezone.utc)

    run = service.create_run(
        session,
        tenant_id=tenant_id,
        student_id=student_id,
        transcript_id=transcript_id,
        actor_user_id=actor_user_id,
        correlation_id="decision:test",
        agent_name="decision_agent",
        agent_type="decision",
        trigger_event="manual_recommendation",
        status="running",
        input_json={
            "context": {
                "tenant_id": tenant_id,
                "student_id": student_id,
                "transcript_id": transcript_id,
                "actor_user_id": actor_user_id,
                "created_at": created_at,
            },
            "input": {
                "decision_id": transcript_id,
                "credits": Decimal("42.5"),
                "items": [student_id],
            },
        },
    )

    assert session.flush_count == 1
    assert run.input_json["context"]["tenant_id"] == str(tenant_id)
    assert run.input_json["context"]["created_at"] == "2026-05-05T18:11:10Z"
    assert run.input_json["input"]["decision_id"] == str(transcript_id)
    assert run.input_json["input"]["credits"] == 42.5
    assert run.input_json["input"]["items"] == [str(student_id)]
