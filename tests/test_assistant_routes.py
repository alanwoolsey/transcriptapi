from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.assistant_routes import router
from app.api.dependencies import get_current_tenant_context


def _build_test_app(can_view_student=True):
    tenant_id = uuid4()
    user_id = uuid4()

    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=tenant_id, name="CRTFY", slug="crtfy"),
            user=SimpleNamespace(id=user_id, display_name="Test User", email="test@example.edu"),
            claims={"raw_token": "token"},
            authorization=SimpleNamespace(
                base_role="tenant_admin",
                roles={"tenant_admin"},
                permissions={"view_student_360"} if can_view_student else set(),
                sensitivity_tiers=set(),
                can=lambda permission: can_view_student and permission == "view_student_360",
            ),
        )

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_assistant_chat_builds_student_context(monkeypatch):
    from app.api import assistant_routes

    captured = {}

    def fake_run_chat(payload, auth_context):
        captured["message"] = payload.message
        captured["route"] = payload.route
        captured["tenant"] = str(auth_context.tenant.id)
        return {
            "response": "Emily is missing a transcript.",
            "policyStatus": "allowed",
            "guardrails": ["tenant_scoped"],
            "citations": [{"id": "student-1:checklist", "label": "Student checklist", "type": "student_checklist"}],
            "auditId": "audit-1",
            "retrieval": {
                "intent": "student_checklist_question",
                "confidence": 0.92,
                "toolsUsed": ["get_active_student_summary", "get_student_checklist_summary"],
                "inputContextTokens": 500,
                "cacheHit": False,
                "sources": ["student-1:checklist"],
            },
        }

    monkeypatch.setattr(assistant_routes.assistant_context_service, "run_chat", fake_run_chat)
    client = TestClient(_build_test_app())

    response = client.post(
        "/api/v1/assistant/chat",
        json={"message": "What is missing for this student?", "route": "/students/student-1", "activeEntity": {"type": "student", "id": "student-1"}},
    )

    assert response.status_code == 200
    assert response.json()["retrieval"]["intent"] == "student_checklist_question"
    assert captured["route"] == "/students/student-1"


def test_assistant_chat_requires_authenticated_tenant_context():
    client = TestClient(FastAPI())
    client.app.include_router(router, prefix="/api/v1")

    response = client.post("/api/v1/assistant/chat", json={"message": "hello"})

    assert response.status_code in {400, 401, 403}


def test_assistant_classify_document_route(monkeypatch):
    from app.api import assistant_routes

    def fake_classify_document(payload, auth_context):
        return {
            "documentType": "Government ID / residency proof",
            "confidence": 0.91,
            "rationale": "The image appears to be a driver's license.",
            "policyStatus": "allowed",
            "guardrails": ["document_classification"],
            "auditId": "audit-doc-1",
        }

    monkeypatch.setattr(assistant_routes.assistant_context_service, "classify_document", fake_classify_document)
    client = TestClient(_build_test_app())

    response = client.post(
        "/api/v1/assistant/classify-document",
        json={
            "fileName": "dl example.jpeg",
            "contentType": "image/jpeg",
            "sizeBytes": 1234,
            "dataBase64": "abc123",
            "classificationOptions": ["Application form", "Government ID / residency proof"],
        },
    )

    assert response.status_code == 200
    assert response.json()["documentType"] == "Government ID / residency proof"
