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


def test_counselor_root_routes_return_backend_shapes(monkeypatch):
    from app.api import roadmap_routes

    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "communication_templates",
        lambda tenant_id: {"items": [{"id": "tmpl_missing_transcript", "key": "missing_transcript", "active": True}], "total": 1},
    )
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "list_handoffs",
        lambda tenant_id, limit=100, offset=0: {"items": [{"id": "handoff-1", "status": "Open"}], "total": 1, "limit": limit, "offset": offset},
    )
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "update_handoff_status",
        lambda db, tenant_id, actor_user_id, handoff_id, payload: {"handoff": {"id": handoff_id, "status": payload["status"]}},
    )
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "counselor_reporting",
        lambda tenant_id, report_type, filters: {"type": report_type, "metrics": {"handoffs": {"openCount": 1}}, "filters": filters},
    )
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "recruitment_events",
        lambda tenant_id: {"items": [{"id": "event-1", "eventType": "Webinar"}], "total": 1},
    )
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "add_recruitment_attendee",
        lambda tenant_id, actor_user_id, event_id, payload: {"event": {"id": event_id}, "attendee": payload},
    )

    client = TestClient(_build_test_app())

    templates = client.get("/api/v1/communication/templates")
    handoffs = client.get("/api/v1/handoffs")
    handoff_status = client.post("/api/v1/handoffs/handoff-1/status", json={"status": "Complete"})
    reporting = client.get("/api/v1/reporting/funnel?program=BSN")
    events = client.get("/api/v1/recruitment/events")
    attendee = client.post("/api/v1/recruitment/events/event-1/attendees", json={"studentId": "STU-123"})

    assert templates.status_code == 200
    assert templates.json()["items"][0]["key"] == "missing_transcript"
    assert handoffs.status_code == 200
    assert handoffs.json()["items"][0]["id"] == "handoff-1"
    assert handoff_status.status_code == 200
    assert handoff_status.json()["handoff"]["status"] == "Complete"
    assert reporting.status_code == 200
    assert reporting.json()["type"] == "funnel"
    assert events.status_code == 200
    assert events.json()["items"][0]["id"] == "event-1"
    assert attendee.status_code == 200
    assert attendee.json()["event"]["id"] == "event-1"
