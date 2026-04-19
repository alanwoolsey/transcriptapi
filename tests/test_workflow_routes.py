from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.workflow_routes import router


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(tenant=SimpleNamespace(id=uuid4()))

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_list_workflows_returns_array(monkeypatch):
    from app.api import workflow_routes

    monkeypatch.setattr(
        workflow_routes.workflow_service,
        "list_workflows",
        lambda tenant_id: [
            {
                "id": "Q-201",
                "student": "Student Name",
                "studentId": "STU-12345",
                "institution": "Institution Name",
                "status": "Trust hold",
                "owner": "Trust Agent",
                "age": "15 min",
                "priority": "High",
                "reason": "Institution mismatch + synthetic pattern markers",
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/workflows")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["id"] == "Q-201"
