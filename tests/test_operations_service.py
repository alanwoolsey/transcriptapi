from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.operations_service import OperationsService


class _FakeResult:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return self

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(self, current_matches=None):
        self.current_matches = list(current_matches or [])
        self.added: list[object] = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _statement):
        return _FakeResult(self.current_matches)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True


class _RecorderTrustAgent:
    def __init__(self):
        self.calls: list[dict] = []

    def record_action(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(status="completed")


class _RecorderProjector:
    def __init__(self):
        self.calls: list[dict] = []

    def refresh_student_projection(self, session, *, tenant_id, student_id):
        self.calls.append({"tenant_id": tenant_id, "student_id": student_id})


def _service(session: _FakeSession) -> OperationsService:
    service = OperationsService(session_factory=lambda: (lambda: session))
    service.trust_agent = _RecorderTrustAgent()
    service.work_state_projector = _RecorderProjector()
    return service


def test_confirm_document_match_reassigns_student_and_records_trust_action():
    tenant_id = uuid4()
    actor_user_id = uuid4()
    previous_student_id = uuid4()
    new_student_id = uuid4()
    document = SimpleNamespace(id=uuid4(), upload_status="received")
    transcript = SimpleNamespace(
        id=uuid4(),
        student_id=previous_student_id,
        matched_at=None,
        matched_by=None,
    )
    current_match = SimpleNamespace(is_current=True)
    session = _FakeSession(current_matches=[current_match])
    service = _service(session)
    service._resolve_document = lambda _session, _tenant_id, _document_id: (document, transcript)
    service._resolve_student = lambda _session, _tenant_id, _student_id: SimpleNamespace(id=new_student_id)

    response = service.confirm_document_match(tenant_id, str(document.id), str(new_student_id), actor_user_id)

    assert response.success is True
    assert response.status == "confirmed"
    assert current_match.is_current is False
    assert transcript.student_id == new_student_id
    assert transcript.matched_by == "user"
    assert document.upload_status == "indexed"
    assert session.committed is True
    assert len(session.added) == 1
    assert service.work_state_projector.calls == [
        {"tenant_id": tenant_id, "student_id": previous_student_id},
        {"tenant_id": tenant_id, "student_id": new_student_id},
    ]
    assert service.trust_agent.calls[0]["code"] == "document_match_confirmed"
    assert service.trust_agent.calls[0]["payload"].target_student_id == str(new_student_id)


def test_reject_document_match_clears_student_and_records_trust_action():
    tenant_id = uuid4()
    actor_user_id = uuid4()
    previous_student_id = uuid4()
    document = SimpleNamespace(id=uuid4(), upload_status="indexed")
    transcript = SimpleNamespace(
        id=uuid4(),
        student_id=previous_student_id,
        matched_at=None,
        matched_by=None,
    )
    current_match = SimpleNamespace(is_current=True)
    session = _FakeSession(current_matches=[current_match])
    service = _service(session)
    service._resolve_document = lambda _session, _tenant_id, _document_id: (document, transcript)

    response = service.reject_document_match(tenant_id, str(document.id), actor_user_id)

    assert response.success is True
    assert response.status == "rejected"
    assert current_match.is_current is False
    assert transcript.student_id is None
    assert transcript.matched_by == "user"
    assert session.committed is True
    assert len(session.added) == 1
    assert service.work_state_projector.calls == [
        {"tenant_id": tenant_id, "student_id": previous_student_id},
    ]
    assert service.trust_agent.calls[0]["code"] == "document_match_rejected"
    assert service.trust_agent.calls[0]["payload"].student_id == str(previous_student_id)
