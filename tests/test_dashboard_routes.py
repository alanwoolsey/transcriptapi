from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dashboard_routes import router
from app.api.dependencies import get_current_tenant_context


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(tenant=SimpleNamespace(id=uuid4()))

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_get_dashboard_returns_payload(monkeypatch):
    from app.api import dashboard_routes

    monkeypatch.setattr(
        dashboard_routes.dashboard_service,
        "get_dashboard",
        lambda tenant_id: {
            "stats": [{"label": "Prospects in motion", "value": "12", "delta": "+20% vs prior 30 days", "tone": "indigo"}],
            "funnel": [{"step": "Prospects", "count": 12}],
            "routing_mix": [{"name": "Auto-certified", "value": 68}],
            "agents": [{"name": "Recruiter Agent", "objective": "Convert", "metric": "23%", "summary": "Tenant scoped"}],
            "activity": [{"title": "Ready Completed event recorded", "detail": "Documents recorded ready completed.", "when": "6 min ago", "category": "Document"}],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"][0]["label"] == "Prospects in motion"
    assert payload["routing_mix"][0]["name"] == "Auto-certified"
