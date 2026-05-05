from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.document_routes import router as document_router
from app.api.student_routes import router as student_router
from app.api.work_routes import router as work_router
from app.db import get_db


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
    app.include_router(student_router, prefix="/api/v1")
    app.include_router(work_router, prefix="/api/v1")
    app.include_router(document_router, prefix="/api/v1")
    return app


def test_get_student_checklist_returns_payload(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(
        student_routes.admissions_ops_service,
        "get_student_checklist",
        lambda tenant_id, student_id: [
            {
                "id": "chk-1",
                "code": "official_transcript",
                "label": "Official transcript",
                "required": True,
                "status": "needs_review",
                "done": False,
                "receivedAt": "2026-04-19T12:10:00Z",
                "completedAt": None,
                "sourceDocumentId": "doc-1",
                "sourceConfidence": 0.93,
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/student-1/checklist")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "needs_review"


def test_update_checklist_item_status_returns_updated_checklist(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(
        student_routes.admissions_ops_service,
        "update_checklist_item_status",
        lambda **kwargs: [
            {
                "id": kwargs["item_id"],
                "code": "official_transcript",
                "label": "Official transcript",
                "required": True,
                "status": "complete",
                "done": True,
                "receivedAt": "2026-04-19T12:10:00Z",
                "completedAt": "2026-04-20T12:10:00Z",
                "sourceDocumentId": "doc-1",
                "sourceConfidence": 0.93,
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.post("/api/v1/students/student-1/checklist/items/item-1/status", json={"status": "complete"})

    assert response.status_code == 200
    assert response.json()[0]["status"] == "complete"


def test_get_student_readiness_returns_payload(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(
        student_routes.admissions_ops_service,
        "get_student_readiness",
        lambda tenant_id, student_id: {
            "studentId": student_id,
            "readinessState": "blocked_by_review",
            "reasonCode": "needs_review",
            "reasonLabel": "Official transcript requires staff review",
            "blockingItemCount": 1,
            "trustBlocked": False,
            "computedAt": "2026-04-20T18:45:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/student-1/readiness")

    assert response.status_code == 200
    assert response.json()["readinessState"] == "blocked_by_review"


def test_get_work_summary_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.admissions_ops_service,
        "get_work_summary",
        lambda tenant_id: {
            "summary": {
                "needsAttention": 18,
                "closeToCompletion": 9,
                "readyForDecision": 11,
                "exceptions": 4,
            }
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/summary")

    assert response.status_code == 200
    assert response.json()["summary"]["readyForDecision"] == 11


def test_get_work_items_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.admissions_ops_service,
        "get_work_items",
        lambda tenant_id, **kwargs: {
            "items": [
                {
                    "id": "work_123",
                    "studentId": "student-1",
                    "studentName": "Mira Holloway",
                    "population": "transfer",
                    "stage": "incomplete",
                    "completionPercent": 83,
                    "priority": "urgent",
                    "section": "close",
                    "owner": {"id": "usr_42", "name": "Elian Brooks"},
                    "reasonToAct": {"code": "missing_one_item", "label": "One item away: Official transcript"},
                    "suggestedAction": {"code": "review_document", "label": "Review official transcript"},
                    "blockingItems": [{"id": "chk_2", "code": "official_transcript", "label": "Official transcript", "status": "needs_review"}],
                    "checklistSummary": {"totalRequired": 6, "completedCount": 5, "missingCount": 0, "needsReviewCount": 1, "oneItemAway": True},
                    "fitScore": 94,
                    "depositLikelihood": 82,
                    "program": "BS Nursing Transfer",
                    "institutionGoal": "Harbor Gate University",
                    "risk": "Low",
                    "lastActivity": "2 hours ago",
                }
            ],
            "total": 42,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/items?section=close&limit=10&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 42
    assert payload["items"][0]["priority"] == "urgent"


def test_get_work_projection_status_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.work_state_projector,
        "get_projection_status",
        lambda tenant_id: {
            "projectedStudents": 129,
            "totalStudents": 129,
            "ready": True,
            "lastProjectedAt": "2026-05-05T18:11:18Z",
            "remainingStudents": 0,
            "nextCursor": None,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/projection/status")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["projectedStudents"] == 129
    assert response.json()["remainingStudents"] == 0


def test_rebuild_work_projection_queues_background_task(monkeypatch):
    from app.api import work_routes

    reset_calls = []

    monkeypatch.setattr(
        work_routes.work_state_projector,
        "reset_tenant_projection",
        lambda tenant_id: reset_calls.append(str(tenant_id)),
    )
    monkeypatch.setattr(
        work_routes.work_state_projector,
        "rebuild_tenant_projection_chunk",
        lambda tenant_id, limit, cursor: {
            "processedStudents": 25,
            "nextCursor": "next-123",
            "remainingStudents": 104,
        },
    )

    client = TestClient(_build_test_app())
    response = client.post("/api/v1/work/projection/rebuild?reset=true&limit=25")

    assert response.status_code == 202
    assert response.json()["status"] == "partial"
    assert response.json()["processedStudents"] == 25
    assert response.json()["nextCursor"] == "next-123"
    assert response.json()["remainingStudents"] == 104
    assert len(reset_calls) == 1


def test_link_document_to_checklist_item_returns_updated_checklist(monkeypatch):
    from app.api import document_routes

    monkeypatch.setattr(
        document_routes.admissions_ops_service,
        "link_document_to_checklist_item",
        lambda **kwargs: [
            {
                "id": "chk-2",
                "code": "official_transcript",
                "label": "Official transcript",
                "required": True,
                "status": "needs_review",
                "done": False,
                "receivedAt": "2026-04-19T12:10:00Z",
                "completedAt": None,
                "sourceDocumentId": "doc-1",
                "sourceConfidence": 0.93,
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/documents/doc-1/link-checklist-item",
        json={
            "studentId": "student-1",
            "checklistItemId": "chk-2",
            "matchConfidence": 0.93,
            "matchStatus": "needs_review",
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["sourceDocumentId"] == "doc-1"


def test_get_document_exceptions_returns_payload(monkeypatch):
    from app.api import document_routes

    monkeypatch.setattr(
        document_routes.admissions_ops_service,
        "get_document_exceptions",
        lambda tenant_id: {
            "items": [
                {
                    "id": "exc-1",
                    "studentId": "student-1",
                    "studentName": "Mira Holloway",
                    "documentId": "doc-1",
                    "transcriptId": "tx-1",
                    "issueType": "checklist_linkage",
                    "label": "Official transcript requires review",
                    "status": "needs_review",
                    "createdAt": "2026-04-20T18:45:00Z",
                    "transcriptStatus": "processing",
                    "documentStatus": "indexed",
                    "parserConfidence": 0.93,
                    "reason": "Checklist match is needs review.",
                    "suggestedAction": "Open the exception details and confirm or reject the document match.",
                    "latestRunStatus": None,
                }
            ],
            "total": 1,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/documents/exceptions")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["suggestedAction"] == "Open the exception details and confirm or reject the document match."


def test_get_document_exception_summary_returns_payload(monkeypatch):
    from app.api import document_routes

    monkeypatch.setattr(
        document_routes.operations_service,
        "get_document_exception_summary",
        lambda tenant_id, document_id: {
            "documentId": document_id,
            "transcriptId": "tx-1",
            "studentId": "student-1",
            "studentName": "Mira Holloway",
            "documentStatus": "failed",
            "transcriptStatus": "failed",
            "parserConfidence": None,
            "issueType": "processing_failure",
            "issueLabel": "No courses were extracted from transcript.",
            "issueStatus": "course_mapping_failed",
            "suggestedAction": "Retry document processing with the same file.",
            "failureCode": "course_mapping_failed",
            "failureMessage": "No courses were extracted from transcript.",
            "createdAt": "2026-05-05T18:11:10Z",
            "updatedAt": "2026-05-05T18:11:18Z",
            "latestRun": {
                "runId": "run-1",
                "agentName": "document_agent",
                "status": "failed",
                "triggerEvent": "stored_reprocess",
                "error": "No courses were extracted from transcript.",
                "startedAt": "2026-05-05T18:11:10Z",
                "completedAt": "2026-05-05T18:11:18Z",
            },
            "recentActions": [
                {
                    "actionId": "action-1",
                    "actionType": "parse_transcript",
                    "toolName": "parse_transcript",
                    "status": "failed",
                    "error": "No courses were extracted from transcript.",
                    "startedAt": "2026-05-05T18:11:10Z",
                    "completedAt": "2026-05-05T18:11:18Z",
                    "input": {"filename": "one.pdf"},
                    "output": {},
                }
            ],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/documents/doc-1/exception-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["issueType"] == "processing_failure"
    assert payload["latestRun"]["status"] == "failed"
    assert payload["recentActions"][0]["actionType"] == "parse_transcript"
