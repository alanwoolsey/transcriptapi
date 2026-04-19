from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.decision_routes import router
from app.api.dependencies import get_current_tenant_context


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(tenant=SimpleNamespace(id=uuid4()))

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_list_decisions_returns_array(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "list_decisions",
        lambda tenant_id: [
            {
                "id": "decision-1",
                "student": "Alyssa Mcculley",
                "program": "High School Review",
                "fit": 94,
                "creditEstimate": 42,
                "readiness": "Auto-certify",
                "reason": "All prerequisites satisfied. No risk signals present.",
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/decisions")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["student"] == "Alyssa Mcculley"
