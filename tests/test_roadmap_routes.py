from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.roadmap_routes import router


def _build_test_app() -> FastAPI:
    tenant_id = uuid4()
    user_id = uuid4()

    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=tenant_id),
            user=SimpleNamespace(id=user_id),
            authorization=SimpleNamespace(can=lambda permission: True),
        )

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_checklist_template_routes_use_phase4_contract(monkeypatch):
    from app.api import roadmap_routes

    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "list_checklist_templates",
        lambda tenant_id, q=None, limit=50, offset=0: {"items": [{"id": "tmpl-1", "name": "Transfer"}], "total": 1, "limit": limit, "offset": offset},
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/checklist/templates?q=transfer&limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["id"] == "tmpl-1"
    assert payload["total"] == 1
    assert payload["limit"] == 5


def test_student_interaction_route_logs_payload(monkeypatch):
    from app.api import roadmap_routes

    captured = {}

    def fake_create_interaction(tenant_id, actor_user_id, student_id, payload):
        captured["student_id"] = student_id
        captured["type"] = payload.type
        return {"id": "note-1", "studentId": student_id, "type": payload.type}

    monkeypatch.setattr(roadmap_routes.roadmap_service, "create_interaction", fake_create_interaction)

    client = TestClient(_build_test_app())
    response = client.post("/api/v1/students/student-1/interactions", json={"type": "call", "body": "Left voicemail"})

    assert response.status_code == 200
    assert response.json()["item"]["id"] == "note-1"
    assert captured == {"student_id": "student-1", "type": "call"}


def test_connector_and_reporting_routes_return_backend_shapes(monkeypatch):
    from app.api import roadmap_routes

    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "connectors",
        lambda tenant_id, q=None, limit=50, offset=0: {"items": [{"id": "salesforce", "status": "connected"}], "total": 1, "limit": limit, "offset": offset},
    )
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "reporting",
        lambda tenant_id, report_type, q=None, limit=50, offset=0: {"type": report_type, "metrics": {"students": 3}, "items": [], "total": 0},
    )

    client = TestClient(_build_test_app())

    connectors = client.get("/api/v1/connectors")
    operational = client.get("/api/v1/reporting/operational")

    assert connectors.status_code == 200
    assert connectors.json()["items"][0]["id"] == "salesforce"
    assert operational.status_code == 200
    assert operational.json()["type"] == "operational"
