from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.decision_routes import router
from app.db import get_db
from app.api.dependencies import get_current_tenant_context


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4(), display_name="Taylor Reed"),
        )

    def override_db():
        yield SimpleNamespace()

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.dependency_overrides[get_db] = override_db
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


def test_create_decision_returns_created_item(monkeypatch):
    from app.api import decision_routes

    captured = {}

    def fake_create_decision(*, db, tenant_id, user_id, payload):
        captured["tenant_id"] = tenant_id
        captured["user_id"] = user_id
        captured["payload"] = payload
        return {
            "id": "decision-1",
            "student": payload.student,
            "program": payload.program,
            "fit": payload.fit,
            "creditEstimate": payload.creditEstimate,
            "readiness": payload.readiness,
            "reason": payload.reason,
        }

    monkeypatch.setattr(decision_routes.decision_service, "create_decision", fake_create_decision)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/decisions",
        json={
            "student": "Avery Carter",
            "program": "Nursing transfer review",
            "fit": 92,
            "creditEstimate": 38,
            "readiness": "Draft",
            "reason": "Explainable rationale text",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["student"] == "Avery Carter"
    assert payload["program"] == "Nursing transfer review"
    assert payload["fit"] == 92
    assert payload["creditEstimate"] == 38
    assert payload["readiness"] == "Draft"
    assert payload["reason"] == "Explainable rationale text"
    assert "tenant_id" in captured
    assert "user_id" in captured


def test_get_decision_detail_returns_packet(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "get_decision_detail",
        lambda tenant_id, decision_id: {
            "id": str(decision_id),
            "status": "Draft",
            "readiness": "Draft",
            "assignedTo": {"id": "user-1", "name": "Taylor Reed"},
            "queue": "Admissions Review",
            "createdAt": "2026-04-19T15:22:11Z",
            "updatedAt": "2026-04-19T16:03:48Z",
            "student": {"id": "student-1", "name": "Avery Carter", "email": "avery@example.com", "externalId": "STU-10441"},
            "program": {"name": "Nursing transfer review"},
            "recommendation": {"fit": 92, "creditEstimate": 38, "reason": "Explainable rationale text"},
            "evidence": {"institution": "Harbor Gate University", "gpa": 3.42, "creditsEarned": 42, "parserConfidence": 0.96, "documentCount": 3},
            "trust": {"status": "Clear", "signals": []},
            "notes": [],
            "timelinePreview": [],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/decisions/{uuid4()}")

    assert response.status_code == 200
    assert response.json()["student"]["name"] == "Avery Carter"


def test_generate_decision_recommendation_returns_agent_run(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "generate_recommendation",
        lambda **kwargs: {
            "decisionId": str(kwargs["decision_id"]),
            "agentRunId": "run-1",
            "recommendation": {"fit": 92, "creditEstimate": 38, "reason": "Explainable rationale text"},
            "status": "completed",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/decisions/{uuid4()}/recommendation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agentRunId"] == "run-1"
    assert payload["recommendation"]["fit"] == 92


def test_review_decision_recommendation_returns_status(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "review_recommendation",
        lambda **kwargs: {
            "id": str(kwargs["decision_id"]),
            "action": kwargs["payload"].action,
            "status": "Approved",
            "snapshotVersion": "4d0f13d56a1c2b33",
            "updatedAt": "2026-05-05T18:12:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        f"/api/v1/decisions/{uuid4()}/review",
        json={"action": "accept_recommendation", "note": "Recommendation accepted."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "accept_recommendation"
    assert payload["status"] == "Approved"
    assert payload["snapshotVersion"] == "4d0f13d56a1c2b33"


def test_get_decision_snapshot_returns_snapshot(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "get_snapshot",
        lambda tenant_id, decision_id: {
            "decisionId": str(decision_id),
            "status": "Draft",
            "readiness": "Ready for review",
            "student": {"id": "student-1", "name": "Avery Carter", "email": "avery@example.com", "externalId": "STU-10441"},
            "program": {"id": None, "name": "Nursing transfer review"},
            "recommendation": {"fit": 92, "creditEstimate": 38, "reason": "Explainable rationale text"},
            "evidence": {"institution": "Harbor Gate University", "gpa": 3.42, "creditsEarned": 42, "parserConfidence": 0.96, "documentCount": 3},
            "trust": {"status": "Clear", "signals": []},
        },
    )

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/decisions/{uuid4()}/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommendation"]["fit"] == 92
    assert payload["evidence"]["documentCount"] == 3


def test_get_decision_agent_details_returns_latest_run(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "get_agent_details",
        lambda tenant_id, decision_id: {
            "decisionId": str(decision_id),
            "student": {"id": "student-1", "name": "Avery Carter", "email": "avery@example.com", "externalId": "STU-10441"},
            "program": {"id": None, "name": "Nursing transfer review"},
            "recommendation": {"fit": 92, "creditEstimate": 38, "reason": "Explainable rationale text"},
            "latestRun": {
                "runId": "run-1",
                "agentName": "decision_agent",
                "agentType": "decision",
                "status": "completed",
                "triggerEvent": "manual_recommendation",
                "studentId": "student-1",
                "transcriptId": str(decision_id),
                "actorUserId": "user-1",
                "correlationId": "decision-recommend:1",
                "error": None,
                "startedAt": "2026-05-05T18:11:10Z",
                "completedAt": "2026-05-05T18:11:12Z",
                "result": {
                    "status": "completed",
                    "code": "decision_recommendation_generated",
                    "message": "Decision recommendation generated.",
                    "error": None,
                    "metrics": {"fit": 92},
                    "artifacts": {"decisionId": str(decision_id)},
                },
            },
            "actions": [],
            "lastReviewedSnapshot": {
                "action": "accept_recommendation",
                "snapshotVersion": "4d0f13d56a1c2b33",
                "reviewedAt": "2026-05-05T18:12:00Z",
                "reviewedByUserId": "user-1",
                "snapshot": {
                    "decisionId": str(decision_id),
                    "status": "Draft",
                    "readiness": "Ready for review",
                    "student": {"id": "student-1", "name": "Avery Carter", "email": "avery@example.com", "externalId": "STU-10441"},
                    "program": {"id": None, "name": "Nursing transfer review"},
                    "recommendation": {"fit": 92, "creditEstimate": 38, "reason": "Explainable rationale text"},
                    "evidence": {"institution": "Harbor Gate University", "gpa": 3.42, "creditsEarned": 42, "parserConfidence": 0.96, "documentCount": 3},
                    "trust": {"status": "Clear", "signals": []},
                },
            },
        },
    )

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/decisions/{uuid4()}/agent-details")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latestRun"]["agentName"] == "decision_agent"
    assert payload["latestRun"]["result"]["code"] == "decision_recommendation_generated"
    assert payload["lastReviewedSnapshot"]["snapshotVersion"] == "4d0f13d56a1c2b33"


def test_update_decision_status_returns_updated_status(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "update_status",
        lambda **kwargs: {
            "id": str(kwargs["decision_id"]),
            "status": kwargs["payload"].status,
            "updatedAt": "2026-04-19T16:12:33Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/decisions/{uuid4()}/status", json={"status": "Ready for review"})

    assert response.status_code == 200
    assert response.json()["status"] == "Ready for review"


def test_assign_decision_returns_assignee(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "assign_decision",
        lambda **kwargs: {
            "id": str(kwargs["decision_id"]),
            "assignedTo": {"id": kwargs["payload"].assignee_user_id, "name": "Taylor Reed"},
            "updatedAt": "2026-04-19T16:18:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        f"/api/v1/decisions/{uuid4()}/assign",
        json={"assignee_user_id": str(uuid4())},
    )

    assert response.status_code == 200
    assert response.json()["assignedTo"]["name"] == "Taylor Reed"


def test_add_decision_note_returns_created_note(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "add_note",
        lambda **kwargs: {
            "id": "note-1",
            "body": kwargs["payload"].body,
            "authorName": "Taylor Reed",
            "createdAt": "2026-04-19T16:20:14Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        f"/api/v1/decisions/{uuid4()}/notes",
        json={"body": "Manual review needed for lab sequence."},
    )

    assert response.status_code == 201
    assert response.json()["authorName"] == "Taylor Reed"


def test_get_decision_timeline_returns_events(monkeypatch):
    from app.api import decision_routes

    monkeypatch.setattr(
        decision_routes.decision_service,
        "get_timeline",
        lambda tenant_id, decision_id: [
            {
                "id": "event-1",
                "type": "packet_created",
                "label": "Decision packet created",
                "detail": "Packet opened for Avery Carter.",
                "actorName": "Taylor Reed",
                "at": "2026-04-19T15:22:11Z",
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/decisions/{uuid4()}/timeline")

    assert response.status_code == 200
    assert response.json()[0]["type"] == "packet_created"
