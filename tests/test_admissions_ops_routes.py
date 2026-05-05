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


def test_get_today_work_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.admissions_ops_service,
        "get_today_work",
        lambda tenant_id, limit=25: {
            "items": [
                {
                    "id": "work_123",
                    "studentId": "student-1",
                    "studentName": "Mira Holloway",
                    "section": "ready",
                    "priority": "urgent",
                    "owner": {"id": "usr_42", "name": "Elian Brooks"},
                    "reasonToAct": {"code": "ready_for_decision", "label": "Ready for decision"},
                    "suggestedAction": {"code": "review_recommendation", "label": "Review recommendation"},
                    "currentOwnerAgent": "decision_agent",
                    "currentStage": "recommendation_ready",
                    "documentAgent": {
                        "runId": "run-doc-1",
                        "status": "completed",
                        "resultCode": "transcript_processed",
                        "updatedAt": "2026-05-05T18:11:18Z",
                    },
                    "trustAgent": {
                        "runId": "run-trust-1",
                        "status": "completed",
                        "resultCode": "trust_case_resolved",
                        "updatedAt": "2026-05-05T18:12:00Z",
                    },
                    "decisionAgent": {
                        "runId": "run-decision-1",
                        "status": "completed",
                        "resultCode": "decision_recommendation_generated",
                        "updatedAt": "2026-05-05T18:13:00Z",
                    },
                    "updatedAt": "2026-05-05T18:13:00Z",
                }
            ],
            "total": 1,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/today?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["currentOwnerAgent"] == "decision_agent"
    assert payload["items"][0]["decisionAgent"]["resultCode"] == "decision_recommendation_generated"


def test_get_today_work_board_returns_grouped_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.admissions_ops_service,
        "get_today_work_board",
        lambda tenant_id, limit=50: {
            "groups": [
                {
                    "key": "decision_review",
                    "label": "Decision Review",
                    "total": 1,
                    "routeHint": {
                        "nextAgent": "decision_agent",
                        "reason": "These students are ready for recommendation or decision review.",
                        "actionLabel": "Route to decision review",
                    },
                    "items": [
                        {
                            "id": "work_123",
                            "studentId": "student-1",
                            "studentName": "Mira Holloway",
                            "section": "ready",
                            "priority": "urgent",
                            "priorityScore": 88,
                            "owner": {"id": "usr_42", "name": "Elian Brooks"},
                            "reasonToAct": {"code": "ready_for_decision", "label": "Ready for decision"},
                            "suggestedAction": {"code": "review_recommendation", "label": "Review recommendation"},
                            "currentOwnerAgent": "document_agent",
                            "currentStage": "routed",
                            "recommendedAgent": "decision_agent",
                            "queueGroup": "decision_review",
                            "documentAgent": {
                                "runId": "run-doc-1",
                                "status": "completed",
                                "resultCode": "transcript_processed",
                                "updatedAt": "2026-05-05T18:11:18Z",
                            },
                            "trustAgent": None,
                            "decisionAgent": {
                                "runId": "run-decision-1",
                                "status": "completed",
                                "resultCode": "decision_recommendation_generated",
                                "updatedAt": "2026-05-05T18:13:00Z",
                            },
                            "updatedAt": "2026-05-05T18:13:00Z",
                        }
                    ],
                }
            ],
            "total": 1,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/today/board?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["groups"][0]["key"] == "decision_review"
    assert payload["groups"][0]["items"][0]["recommendedAgent"] == "decision_agent"
    assert payload["groups"][0]["routeHint"]["nextAgent"] == "decision_agent"


def test_orchestrate_today_work_returns_run_and_grouped_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.admissions_ops_service,
        "orchestrate_today_work",
        lambda **kwargs: {
            "agentRunId": "run-orch-1",
            "board": {
                "groups": [
                    {
                        "key": "decision_review",
                        "label": "Decision Review",
                        "total": 1,
                        "routeHint": {
                            "nextAgent": "decision_agent",
                            "reason": "These students are ready for recommendation or decision review.",
                            "actionLabel": "Route to decision review",
                        },
                        "items": [
                            {
                                "id": "work_123",
                                "studentId": "student-1",
                                "studentName": "Mira Holloway",
                                "section": "ready",
                                "priority": "urgent",
                                "priorityScore": 88,
                                "owner": {"id": "usr_42", "name": "Elian Brooks"},
                                "reasonToAct": {"code": "ready_for_decision", "label": "Ready for decision"},
                                "suggestedAction": {"code": "review_recommendation", "label": "Review recommendation"},
                                "currentOwnerAgent": "document_agent",
                                "currentStage": "routed",
                                "recommendedAgent": "decision_agent",
                                "queueGroup": "decision_review",
                                "updatedAt": "2026-05-05T18:13:00Z",
                            }
                        ],
                    }
                ],
                "total": 1,
            },
            "run": {
                "runId": "run-orch-1",
                "agentName": "orchestrator_agent",
                "agentType": "orchestrator",
                "status": "completed",
                "triggerEvent": "manual_today_work_orchestration",
                "studentId": None,
                "transcriptId": None,
                "actorUserId": "user-1",
                "correlationId": "today-work:user-1",
                "error": None,
                "startedAt": "2026-05-05T18:13:00Z",
                "completedAt": "2026-05-05T18:13:00Z",
                "result": {
                    "status": "completed",
                    "code": "today_work_prioritized",
                    "message": "Today's work prioritized and grouped.",
                    "error": None,
                    "metrics": {"totalStudents": 1, "groupCount": 1},
                    "artifacts": {"groupKeys": ["decision_review"]},
                },
            },
            "actions": [
                {
                    "actionId": "action-orch-1",
                    "actionType": "prioritize_today_work_group",
                    "toolName": "prioritize_today_work_group",
                    "status": "completed",
                    "studentId": None,
                    "transcriptId": None,
                    "error": None,
                    "startedAt": "2026-05-05T18:13:00Z",
                    "completedAt": "2026-05-05T18:13:00Z",
                    "result": {
                        "status": "completed",
                        "code": "today_work_group_prioritized",
                        "message": "Decision Review queue grouped.",
                        "error": None,
                        "metrics": {"groupTotal": 1},
                        "artifacts": {
                            "groupKey": "decision_review",
                            "studentIds": ["student-1"],
                            "routeHint": {
                                "nextAgent": "decision_agent",
                                "reason": "These students are ready for recommendation or decision review.",
                                "actionLabel": "Route to decision review",
                            },
                        },
                    },
                    "input": {"groupKey": "decision_review", "limit": 10},
                    "output": {
                        "status": "completed",
                        "code": "today_work_group_prioritized",
                        "message": "Decision Review queue grouped.",
                        "error": None,
                        "metrics": {"groupTotal": 1},
                        "artifacts": {
                            "groupKey": "decision_review",
                            "studentIds": ["student-1"],
                            "routeHint": {
                                "nextAgent": "decision_agent",
                                "reason": "These students are ready for recommendation or decision review.",
                                "actionLabel": "Route to decision review",
                            },
                        },
                    },
                }
            ],
        },
    )

    client = TestClient(_build_test_app())
    response = client.post("/api/v1/work/today/orchestrate?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agentRunId"] == "run-orch-1"
    assert payload["run"]["result"]["code"] == "today_work_prioritized"
    assert payload["actions"][0]["result"]["code"] == "today_work_group_prioritized"
    assert payload["board"]["groups"][0]["routeHint"]["nextAgent"] == "decision_agent"
    assert payload["actions"][0]["result"]["artifacts"]["routeHint"]["nextAgent"] == "decision_agent"


def test_get_latest_today_work_orchestration_returns_snapshot(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.admissions_ops_service,
        "get_latest_today_work_orchestration",
        lambda tenant_id, student_id=None: {
            "agentRunId": "run-orch-1",
            "board": {
                "groups": [
                    {
                        "key": "decision_review",
                        "label": "Decision Review",
                        "total": 1,
                        "routeHint": {
                            "nextAgent": "decision_agent",
                            "reason": "These students are ready for recommendation or decision review.",
                            "actionLabel": "Route to decision review",
                        },
                        "items": [
                            {
                                "id": "work_123",
                                "studentId": "student-1",
                                "studentName": "Mira Holloway",
                                "section": "ready",
                                "priority": "urgent",
                                "priorityScore": 88,
                                "owner": {"id": "usr_42", "name": "Elian Brooks"},
                                "reasonToAct": {"code": "ready_for_decision", "label": "Ready for decision"},
                                "suggestedAction": {"code": "review_recommendation", "label": "Review recommendation"},
                                "recommendedAgent": "decision_agent",
                                "queueGroup": "decision_review",
                                "updatedAt": "2026-05-05T18:13:00Z",
                            }
                        ],
                    }
                ],
                "total": 1,
            },
            "run": {
                "runId": "run-orch-1",
                "agentName": "orchestrator_agent",
                "agentType": "orchestrator",
                "status": "completed",
                "triggerEvent": "manual_today_work_orchestration",
                "studentId": None,
                "transcriptId": None,
                "actorUserId": "user-1",
                "correlationId": "today-work:user-1",
                "error": None,
                "startedAt": "2026-05-05T18:13:00Z",
                "completedAt": "2026-05-05T18:13:00Z",
                "result": {
                    "status": "completed",
                    "code": "today_work_prioritized",
                    "message": "Today's work prioritized and grouped.",
                    "error": None,
                    "metrics": {"totalStudents": 1, "groupCount": 1},
                    "artifacts": {"groupKeys": ["decision_review"]},
                },
            },
            "actions": [],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/today/orchestrations/latest?studentId=student-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agentRunId"] == "run-orch-1"
    assert payload["board"]["groups"][0]["key"] == "decision_review"
    assert payload["board"]["groups"][0]["routeHint"]["nextAgent"] == "decision_agent"


def test_route_today_work_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.admissions_ops_service,
        "route_today_work",
        lambda **kwargs: {
            "studentId": kwargs["student_id"],
            "nextAgent": kwargs["payload"].nextAgent,
            "currentStage": "routed",
            "detail": "Work item routed to decision_agent.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/work/today/student-1/route",
        json={"nextAgent": "decision_agent", "note": "Ready for recommendation review."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["studentId"] == "student-1"
    assert payload["nextAgent"] == "decision_agent"
    assert payload["currentStage"] == "routed"


def test_get_today_work_recommendation_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.admissions_ops_service,
        "get_today_work_recommendation",
        lambda tenant_id, student_id: {
            "studentId": student_id,
            "recommendedAgent": "decision_agent",
            "currentOwnerAgent": "document_agent",
            "currentStage": "routed",
            "reason": "The student is ready for decision review, so decision handling should own the next step.",
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/today/student-1/recommendation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["studentId"] == "student-1"
    assert payload["recommendedAgent"] == "decision_agent"
    assert payload["currentOwnerAgent"] == "document_agent"


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
            "currentJob": {
                "jobId": "job-1",
                "status": "completed",
                "resetRequested": True,
                "chunkSize": 100,
                "processedStudents": 129,
                "remainingStudents": 0,
                "nextCursor": None,
                "error": None,
                "startedAt": "2026-05-05T18:10:00Z",
                "completedAt": "2026-05-05T18:11:18Z",
            },
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/projection/status")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["projectedStudents"] == 129
    assert response.json()["remainingStudents"] == 0
    assert response.json()["currentJob"]["status"] == "completed"


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


def test_rebuild_all_work_projection_queues_background_loop(monkeypatch):
    from app.api import work_routes

    background_calls = []

    monkeypatch.setattr(
        work_routes.work_state_projector,
        "create_projection_job",
        lambda tenant_id, reset, limit: "job-queued-1",
    )

    def fake_background(tenant_id, job_id):
        background_calls.append({"tenant_id": tenant_id, "job_id": job_id})

    monkeypatch.setattr(work_routes, "_run_projection_job", fake_background)

    client = TestClient(_build_test_app())
    response = client.post("/api/v1/work/projection/rebuild-all?reset=true&limit=50")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["jobId"] == "job-queued-1"
    assert response.json()["detail"] == "Full work-state projection rebuild queued."
    assert len(background_calls) == 1
    assert background_calls[0]["job_id"] == "job-queued-1"


def test_list_work_projection_jobs_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.work_state_projector,
        "list_projection_jobs",
        lambda tenant_id, limit=20: [
            {
                "jobId": "job-1",
                "status": "failed",
                "resetRequested": True,
                "chunkSize": 100,
                "processedStudents": 50,
                "remainingStudents": 79,
                "nextCursor": "next-123",
                "error": "boom",
                "startedAt": "2026-05-05T18:10:00Z",
                "completedAt": "2026-05-05T18:12:00Z",
                "createdAt": "2026-05-05T18:09:55Z",
                "updatedAt": "2026-05-05T18:12:00Z",
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/projection/jobs?limit=10")

    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "failed"
    assert response.json()["items"][0]["error"] == "boom"


def test_get_work_projection_job_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.work_state_projector,
        "get_projection_job",
        lambda tenant_id, job_id: {
            "jobId": job_id,
            "status": "running",
            "resetRequested": False,
            "chunkSize": 100,
            "processedStudents": 75,
            "remainingStudents": 54,
            "nextCursor": "next-456",
            "error": None,
            "startedAt": "2026-05-05T18:10:00Z",
            "completedAt": None,
            "createdAt": "2026-05-05T18:09:55Z",
            "updatedAt": "2026-05-05T18:11:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/work/projection/jobs/job-2")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["jobId"] == "job-2"


def test_retry_work_projection_job_queues_background_task(monkeypatch):
    from app.api import work_routes

    background_calls = []

    monkeypatch.setattr(
        work_routes.work_state_projector,
        "retry_projection_job",
        lambda tenant_id, job_id: "job-retry-1",
    )

    def fake_background(tenant_id, job_id):
        background_calls.append({"tenant_id": tenant_id, "job_id": job_id})

    monkeypatch.setattr(work_routes, "_run_projection_job", fake_background)

    client = TestClient(_build_test_app())
    response = client.post("/api/v1/work/projection/jobs/job-1/retry")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["jobId"] == "job-retry-1"
    assert response.json()["detail"] == "Projection job retry queued."
    assert background_calls[0]["job_id"] == "job-retry-1"


def test_cancel_work_projection_job_returns_payload(monkeypatch):
    from app.api import work_routes

    monkeypatch.setattr(
        work_routes.work_state_projector,
        "cancel_projection_job",
        lambda tenant_id, job_id: {
            "jobId": job_id,
            "status": "canceled",
            "resetRequested": True,
            "chunkSize": 100,
            "processedStudents": 40,
            "remainingStudents": 88,
            "nextCursor": "next-789",
            "error": None,
            "startedAt": "2026-05-05T18:10:00Z",
            "completedAt": "2026-05-05T18:11:00Z",
            "createdAt": "2026-05-05T18:09:55Z",
            "updatedAt": "2026-05-05T18:11:00Z",
        },
    )

    client = TestClient(_build_test_app())
    response = client.post("/api/v1/work/projection/jobs/job-3/cancel")

    assert response.status_code == 200
    assert response.json()["jobId"] == "job-3"
    assert response.json()["status"] == "canceled"


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


def test_get_document_agent_run_details_returns_payload(monkeypatch):
    from app.api import document_routes

    monkeypatch.setattr(
        document_routes.operations_service,
        "get_document_agent_run_details",
        lambda tenant_id, document_id: {
            "documentId": document_id,
            "transcriptId": "tx-1",
            "studentId": "student-1",
            "studentName": "Mira Holloway",
            "documentStatus": "processing",
            "transcriptStatus": "processing",
            "parserConfidence": 0.91,
            "latestFailure": {
                "code": "course_mapping_failed",
                "message": "No courses were extracted from transcript.",
                "createdAt": "2026-05-05T18:11:10Z",
                "updatedAt": "2026-05-05T18:11:10Z",
            },
            "run": {
                "runId": "run-1",
                "agentName": "document_agent",
                "agentType": "document",
                "status": "failed",
                "triggerEvent": "stored_reprocess",
                "studentId": "student-1",
                "transcriptId": "tx-1",
                "actorUserId": "user-1",
                "correlationId": "document-reprocess:doc-1",
                "error": "No courses were extracted from transcript.",
                "startedAt": "2026-05-05T18:11:10Z",
                "completedAt": "2026-05-05T18:11:18Z",
                "result": {
                    "status": "failed",
                    "code": "document_processing_failed",
                    "message": "Transcript processing failed.",
                    "error": "No courses were extracted from transcript.",
                    "metrics": {"use_bedrock": True},
                    "artifacts": {"transcriptId": "tx-1"},
                },
            },
            "actions": [
                {
                    "actionId": "action-1",
                    "actionType": "parse_transcript",
                    "toolName": "parse_transcript",
                    "status": "failed",
                    "studentId": "student-1",
                    "transcriptId": "tx-1",
                    "error": "No courses were extracted from transcript.",
                    "startedAt": "2026-05-05T18:11:10Z",
                    "completedAt": "2026-05-05T18:11:18Z",
                    "result": {
                        "status": "failed",
                        "code": "document_processing_failed",
                        "message": "Transcript processing failed.",
                        "error": "No courses were extracted from transcript.",
                        "metrics": {"use_bedrock": True},
                        "artifacts": {"transcriptId": "tx-1"},
                    },
                    "input": {"filename": "replacement.pdf"},
                    "output": {},
                }
            ],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/documents/doc-1/run-details")

    assert response.status_code == 200
    payload = response.json()
    assert payload["documentId"] == "doc-1"
    assert payload["run"]["result"]["code"] == "document_processing_failed"
    assert payload["actions"][0]["actionType"] == "parse_transcript"
