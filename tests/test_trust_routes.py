from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.trust_routes import router


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(tenant=SimpleNamespace(id=uuid4()), user=SimpleNamespace(id=uuid4()))

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_list_trust_cases_returns_array(monkeypatch):
    from app.api import trust_routes

    monkeypatch.setattr(
        trust_routes.trust_service,
        "list_cases",
        lambda tenant_id: [
            {
                "id": "TRUST-01",
                "transcriptId": "tx-1",
                "studentId": "student-1",
                "student": "Student Name",
                "documentId": "tx-1",
                "document": "Official transcript",
                "severity": "High",
                "signal": "Issuer mismatch",
                "evidence": "Explanation of the trust issue.",
                "status": "Quarantined",
                "trustBlocked": True,
                "latestRunStatus": "completed",
                "latestResultCode": "trust_document_quarantined",
                "owner": {"id": "user-1", "name": "Taylor Reed"},
                "summary": {
                    "riskLevel": "high",
                    "summary": "Manual quarantine is open. Student progression is currently blocked.",
                    "rationale": "Document quarantined by reviewer.",
                    "recommendedAction": "Review the trust signal and decide whether progression should remain blocked.",
                    "signals": ["Manual quarantine", "High", "Open"],
                },
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/trust/cases")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["id"] == "TRUST-01"
    assert payload[0]["trustBlocked"] is True
    assert payload[0]["latestResultCode"] == "trust_document_quarantined"
    assert payload[0]["owner"]["name"] == "Taylor Reed"
    assert payload[0]["summary"]["riskLevel"] == "high"


def test_get_trust_case_details_returns_payload(monkeypatch):
    from app.api import trust_routes

    monkeypatch.setattr(
        trust_routes.trust_service,
        "get_case_details",
        lambda tenant_id, transcript_id: {
            "transcriptId": transcript_id,
            "studentId": "student-1",
            "student": "Student Name",
            "document": "Official transcript",
            "severity": "High",
            "signal": "Manual quarantine",
            "evidence": "Document quarantined by reviewer.",
            "status": "Open",
            "trustBlocked": True,
            "owner": {"id": "user-1", "name": "Taylor Reed"},
            "openedAt": "2026-05-05T18:11:10Z",
            "summary": {
                "riskLevel": "high",
                "summary": "Manual quarantine is open. Student progression is currently blocked.",
                "rationale": "Document quarantined by reviewer.",
                "recommendedAction": "Review the trust signal and decide whether progression should remain blocked.",
                "signals": ["Manual quarantine", "High", "Open"],
            },
            "latestRun": {
                "runId": "run-1",
                "agentName": "trust_agent",
                "agentType": "trust",
                "status": "completed",
                "triggerEvent": "manual_quarantine",
                "studentId": "student-1",
                "transcriptId": transcript_id,
                "actorUserId": "user-1",
                "correlationId": "trust-quarantine:doc-1",
                "error": None,
                "startedAt": "2026-05-05T18:11:10Z",
                "completedAt": "2026-05-05T18:11:12Z",
                "result": {
                    "status": "completed",
                    "code": "trust_document_quarantined",
                    "message": "Document quarantined.",
                    "error": None,
                    "metrics": {},
                    "artifacts": {"documentId": "doc-1", "transcriptId": transcript_id},
                },
            },
            "actions": [
                {
                    "actionId": "action-1",
                    "actionType": "quarantine_document",
                    "toolName": "quarantine_document",
                    "status": "completed",
                    "studentId": "student-1",
                    "transcriptId": transcript_id,
                    "error": None,
                    "startedAt": "2026-05-05T18:11:10Z",
                    "completedAt": "2026-05-05T18:11:12Z",
                    "result": {
                        "status": "completed",
                        "code": "trust_document_quarantined",
                        "message": "Document quarantined.",
                        "error": None,
                        "metrics": {},
                        "artifacts": {"documentId": "doc-1", "transcriptId": transcript_id},
                    },
                    "input": {"action": "quarantine_document"},
                    "output": {
                        "status": "completed",
                        "code": "trust_document_quarantined",
                        "message": "Document quarantined.",
                        "error": None,
                        "metrics": {},
                        "artifacts": {"documentId": "doc-1", "transcriptId": transcript_id},
                    },
                }
            ],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/trust/transcripts/{uuid4()}/details")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latestRun"]["agentName"] == "trust_agent"
    assert payload["actions"][0]["result"]["code"] == "trust_document_quarantined"
    assert payload["owner"]["id"] == "user-1"
    assert payload["summary"]["recommendedAction"] == "Review the trust signal and decide whether progression should remain blocked."


def test_resolve_trust_case_returns_action_response(monkeypatch):
    from app.api import trust_routes

    monkeypatch.setattr(
        trust_routes.trust_service,
        "resolve_case",
        lambda tenant_id, transcript_id, actor_user_id, note: {
            "success": True,
            "status": "resolved",
            "detail": "Trust case resolved.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/trust/transcripts/{uuid4()}/resolve", json={"note": "False positive"})

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_block_trust_case_returns_action_response(monkeypatch):
    from app.api import trust_routes

    monkeypatch.setattr(
        trust_routes.trust_service,
        "block_case",
        lambda tenant_id, transcript_id, actor_user_id, note: {
            "success": True,
            "status": "blocked",
            "detail": "Trust case blocked.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/trust/transcripts/{uuid4()}/block", json={"note": "Hold until verified"})

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"


def test_unblock_trust_case_returns_action_response(monkeypatch):
    from app.api import trust_routes

    monkeypatch.setattr(
        trust_routes.trust_service,
        "unblock_case",
        lambda tenant_id, transcript_id, actor_user_id, note: {
            "success": True,
            "status": "unblocked",
            "detail": "Trust case unblocked.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/trust/transcripts/{uuid4()}/unblock", json={"note": "Cleared for review"})

    assert response.status_code == 200
    assert response.json()["status"] == "unblocked"


def test_escalate_trust_case_returns_action_response(monkeypatch):
    from app.api import trust_routes

    monkeypatch.setattr(
        trust_routes.trust_service,
        "escalate_case",
        lambda tenant_id, transcript_id, actor_user_id, note: {
            "success": True,
            "status": "escalated",
            "detail": "Trust case escalated.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/trust/transcripts/{uuid4()}/escalate", json={"note": "Need secondary review"})

    assert response.status_code == 200
    assert response.json()["status"] == "escalated"


def test_assign_trust_case_returns_action_response(monkeypatch):
    from app.api import trust_routes

    monkeypatch.setattr(
        trust_routes.trust_service,
        "assign_case",
        lambda tenant_id, transcript_id, actor_user_id, user_id, note: {
            "success": True,
            "status": "assigned",
            "detail": "Trust case assigned.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        f"/api/v1/trust/transcripts/{uuid4()}/assign",
        json={"userId": str(uuid4()), "note": "Assigning for investigation"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "assigned"
