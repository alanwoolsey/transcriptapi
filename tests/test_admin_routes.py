from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.operations_routes import router


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4()),
            authorization=SimpleNamespace(
                can=lambda permission: True,
                can_access_tier=lambda tier: True,
            ),
        )

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_get_admin_users_returns_paginated_payload(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "get_admin_users",
        lambda tenant_id, **kwargs: {
            "items": [
                {
                    "userId": "123",
                    "email": "jane@example.edu",
                    "displayName": "Jane Smith",
                    "status": "active",
                    "baseRole": "director",
                    "roles": ["admissions_counselor"],
                    "permissions": ["view_student_360", "edit_checklist"],
                    "sensitivityTiers": ["basic_profile"],
                    "scopes": {
                        "campuses": ["main"],
                        "territories": ["midwest"],
                        "programs": ["business"],
                        "studentPopulations": ["transfer"],
                        "stages": ["*"],
                    },
                    "lastLoginAt": "2026-04-20T10:00:00Z",
                    "createdAt": "2026-04-01T12:00:00Z",
                    "updatedAt": "2026-04-20T10:00:00Z",
                }
            ],
            "page": 1,
            "pageSize": 25,
            "total": 1,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/admin/users?q=jane&page=1&pageSize=25")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["userId"] == "123"


def test_get_incomplete_queue_returns_frontend_shape(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "list_incomplete",
        lambda tenant_id, **kwargs: {
            "items": [
                {
                    "id": "inc_1",
                    "studentId": "stu_1001",
                    "studentName": "Maya Johnson",
                    "population": "transfer",
                    "program": "Nursing BSN",
                    "missingItemsCount": 2,
                    "missingItems": ["Official transcript", "Residency proof"],
                    "completedItemsCount": 3,
                    "totalRequired": 5,
                    "daysStalled": 2,
                    "closestToComplete": False,
                    "assignedOwner": {"id": "123", "name": "Jane Smith"},
                    "suggestedNextAction": "Request official transcript",
                    "readinessState": "in_progress",
                    "priorityScore": 88,
                    "lastActivityAt": "2026-04-18T15:00:00Z",
                }
            ],
            "page": 1,
            "pageSize": 25,
            "total": 1,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/incomplete?view=submitted_missing_items&q=maya")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["program"] == "Nursing BSN"
    assert item["completedItemsCount"] == 3


def test_get_review_ready_queue_accepts_q_and_returns_frontend_shape(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "list_review_ready",
        lambda tenant_id, **kwargs: {
            "items": [
                {
                    "id": "rr_1",
                    "studentId": "stu_1001",
                    "studentName": "Maya Johnson",
                    "population": "transfer",
                    "program": "Nursing BSN",
                    "assignedReviewer": {"id": "900", "name": "A. Reviewer"},
                    "daysWaiting": 1,
                    "reviewSlaHours": 24,
                    "transferCredits": 27,
                    "completedItemsCount": 5,
                    "totalRequired": 5,
                }
            ]
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/review-ready?q=maya")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["population"] == "transfer"
    assert item["completedItemsCount"] == 5


def test_get_yield_queue_accepts_q_and_returns_frontend_shape(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "list_yield",
        lambda tenant_id, **kwargs: {
            "items": [
                {
                    "studentId": "stu_1001",
                    "studentName": "Maya Johnson",
                    "program": "Nursing BSN",
                    "admitDate": "2026-04-15T00:00:00Z",
                    "depositStatus": "not_deposited",
                    "yieldScore": 72,
                    "lastActivityAt": "2026-04-20T10:00:00Z",
                    "milestoneCompletion": 0.4,
                    "assignedCounselor": {"id": "123", "name": "Jane Smith"},
                    "nextStep": "Call after housing page visit",
                }
            ]
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/yield?view=missing_next_step&q=maya")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["program"] == "Nursing BSN"
    assert item["nextStep"] == "Call after housing page visit"


def test_get_melt_queue_accepts_q_and_returns_frontend_shape(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "list_melt",
        lambda tenant_id, **kwargs: {
            "items": [
                {
                    "studentId": "stu_1001",
                    "studentName": "Maya Johnson",
                    "program": "Nursing BSN",
                    "depositDate": "2026-04-10T00:00:00Z",
                    "meltRisk": 31,
                    "missingMilestones": ["Orientation registration"],
                    "lastOutreachAt": "2026-04-18T14:00:00Z",
                    "owner": {"id": "123", "name": "Jane Smith"},
                }
            ]
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/melt?view=missing_orientation&q=maya")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["program"] == "Nursing BSN"
    assert item["meltRisk"] == 31


def test_create_admin_user_returns_created_record(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "create_admin_user",
        lambda tenant_id, actor_user_id, payload: {
            "userId": "123",
            "email": payload.email,
            "displayName": payload.displayName,
            "status": "invited",
            "baseRole": payload.baseRole,
            "roles": payload.roles,
            "permissions": ["admin_users_view"],
            "sensitivityTiers": payload.sensitivityTiers,
            "scopes": payload.scopes.model_dump(),
            "lastLoginAt": None,
            "createdAt": "2026-04-20T10:00:00Z",
            "updatedAt": "2026-04-20T10:00:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "newuser@example.edu",
            "displayName": "New User",
            "baseRole": "director",
            "roles": ["admissions_processor"],
            "sensitivityTiers": ["basic_profile"],
            "scopes": {
                "campuses": ["main"],
                "territories": ["midwest"],
                "programs": ["business"],
                "studentPopulations": ["transfer"],
                "stages": ["*"],
            },
            "sendInvite": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "invited"


def test_get_admin_user_returns_404_when_missing(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(operations_routes.operations_service, "get_admin_user", lambda tenant_id, user_id: None)

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/admin/users/{uuid4()}")

    assert response.status_code == 404


def test_patch_admin_user_returns_updated_record(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "update_admin_user",
        lambda tenant_id, actor_user_id, user_id, payload: {
            "userId": user_id,
            "email": "jane@example.edu",
            "displayName": payload.displayName,
            "status": payload.status,
            "baseRole": "director",
            "roles": payload.roles,
            "permissions": ["admin_users_update"],
            "sensitivityTiers": payload.sensitivityTiers,
            "scopes": payload.scopes.model_dump(),
            "lastLoginAt": "2026-04-20T10:00:00Z",
            "createdAt": "2026-04-01T12:00:00Z",
            "updatedAt": "2026-04-20T10:00:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.patch(
        f"/api/v1/admin/users/{uuid4()}",
        json={
            "displayName": "Jane Smith",
            "roles": ["admissions_counselor", "reviewer_evaluator"],
            "sensitivityTiers": ["basic_profile", "academic_record"],
            "scopes": {
                "territories": ["midwest", "south"],
                "programs": ["business", "transfer"],
            },
            "status": "active",
        },
    )

    assert response.status_code == 200
    assert response.json()["displayName"] == "Jane Smith"


def test_deactivate_admin_user_surfaces_forbidden(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "deactivate_admin_user",
        lambda tenant_id, actor_user_id, current_user_id, user_id: {
            "success": False,
            "status": "forbidden",
            "detail": "Cannot deactivate the last admin user.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/admin/users/{uuid4()}/deactivate")

    assert response.status_code == 403


def test_get_admin_roles_returns_items(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "get_admin_roles",
        lambda: {"items": [{"key": "admissions_counselor", "label": "Admissions Counselor", "description": "Works students, yield, melt", "active": True}]},
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/admin/roles")

    assert response.status_code == 200
    assert response.json()["items"][0]["key"] == "admissions_counselor"


def test_get_admin_scope_options_returns_values(monkeypatch):
    from app.api import operations_routes

    monkeypatch.setattr(
        operations_routes.operations_service,
        "get_admin_scope_options",
        lambda tenant_id: {
            "campuses": ["*", "main"],
            "territories": ["*", "midwest"],
            "programs": ["*", "business"],
            "studentPopulations": ["*", "transfer"],
            "stages": ["*", "incomplete"],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/admin/scope-options")

    assert response.status_code == 200
    assert response.json()["territories"] == ["*", "midwest"]


def test_reprocess_document_upload_returns_agent_run(monkeypatch):
    from app.api import operations_routes

    background_calls = []
    storage_calls = []

    monkeypatch.setattr(
        operations_routes.operations_service,
        "start_document_reprocess_upload",
        lambda tenant_id, **kwargs: {
            "success": True,
            "status": "processing",
            "detail": "Document queued for agent reprocessing.",
            "documentId": kwargs["document_id"],
            "documentUploadId": kwargs["document_id"],
            "transcriptId": "tx-1",
            "agentRunId": "run-1",
        },
    )

    def fake_background(**kwargs):
        background_calls.append(kwargs)

    monkeypatch.setattr(operations_routes, "_run_document_reprocess_upload", fake_background)
    monkeypatch.setattr(
        operations_routes.document_storage,
        "store_bytes",
        lambda **kwargs: storage_calls.append(kwargs),
    )

    client = TestClient(_build_test_app())
    response = client.post(
        f"/api/v1/documents/{uuid4()}/reprocess-upload",
        files={"file": ("replacement.pdf", b"%PDF-1.4 replacement", "application/pdf")},
        data={"document_type": "official_transcript", "use_bedrock": "false"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["agentRunId"] == "run-1"
    assert payload["transcriptId"] == "tx-1"
    assert len(background_calls) == 1
    assert background_calls[0]["requested_document_type"] == "official_transcript"
    assert background_calls[0]["use_bedrock"] is False
    assert storage_calls[0]["storage_key"] == "tx-1/replacement.pdf"


def test_reprocess_document_queues_stored_reprocess(monkeypatch):
    from app.api import operations_routes

    background_calls = []

    monkeypatch.setattr(
        operations_routes.operations_service,
        "start_stored_document_reprocess",
        lambda tenant_id, **kwargs: {
            "success": True,
            "status": "processing",
            "detail": "Document queued for reprocessing.",
            "documentId": kwargs["document_id"],
            "documentUploadId": kwargs["document_id"],
            "transcriptId": "tx-1",
            "agentRunId": "run-2",
        },
    )

    def fake_background(**kwargs):
        background_calls.append(kwargs)

    monkeypatch.setattr(operations_routes, "_run_stored_document_reprocess", fake_background)

    client = TestClient(_build_test_app())
    response = client.post(f"/api/v1/documents/{uuid4()}/reprocess")

    assert response.status_code == 202
    assert response.json()["status"] == "processing"
    assert response.json()["agentRunId"] == "run-2"
    assert len(background_calls) == 1
    assert background_calls[0]["agent_run_id"] == "run-2"


def test_get_agent_run_status_returns_payload(monkeypatch):
    from app.api import operations_routes

    run_id = str(uuid4())
    monkeypatch.setattr(
        operations_routes.operations_service,
        "get_agent_run_status",
        lambda tenant_id, requested_run_id: {
            "runId": requested_run_id,
            "agentName": "document_agent",
            "agentType": "document",
            "status": "completed",
            "triggerEvent": "manual_reprocess_upload",
            "studentId": str(uuid4()),
            "transcriptId": str(uuid4()),
            "actorUserId": str(uuid4()),
            "correlationId": "document-reprocess:test",
            "error": None,
            "startedAt": "2026-05-05T18:11:10Z",
            "completedAt": "2026-05-05T18:11:18Z",
            "result": {
                "status": "completed",
                "code": "transcript_processed",
                "message": "Transcript parsed successfully.",
                "error": None,
                "metrics": {"courses": 31, "use_bedrock": True},
                "artifacts": {"documentId": "doc-1", "transcriptId": "tx-1"},
            },
        },
    )

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/agent-runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result"]["code"] == "transcript_processed"


def test_get_agent_run_actions_returns_payload(monkeypatch):
    from app.api import operations_routes

    run_id = str(uuid4())
    monkeypatch.setattr(
        operations_routes.operations_service,
        "get_agent_run_actions",
        lambda tenant_id, requested_run_id: {
            "runId": requested_run_id,
            "items": [
                {
                    "actionId": str(uuid4()),
                    "actionType": "parse_transcript",
                    "toolName": "parse_transcript",
                    "status": "completed",
                    "studentId": str(uuid4()),
                    "transcriptId": str(uuid4()),
                    "error": None,
                    "startedAt": "2026-05-05T18:11:10Z",
                    "completedAt": "2026-05-05T18:11:15Z",
                    "result": {
                        "status": "completed",
                        "code": "transcript_parsed",
                        "message": "Transcript parsing completed.",
                        "error": None,
                        "metrics": {"courses": 31, "use_bedrock": True},
                        "artifacts": {"documentId": "doc-1", "transcriptId": "tx-1"},
                    },
                    "input": {"filename": "one.pdf"},
                    "output": {
                        "status": "completed",
                        "code": "transcript_parsed",
                        "message": "Transcript parsing completed.",
                        "error": None,
                        "metrics": {"courses": 31, "use_bedrock": True},
                        "artifacts": {"documentId": "doc-1", "transcriptId": "tx-1"},
                    },
                }
            ],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get(f"/api/v1/agent-runs/{run_id}/actions")

    assert response.status_code == 200
    assert response.json()["items"][0]["actionType"] == "parse_transcript"
    assert response.json()["items"][0]["result"]["code"] == "transcript_parsed"
