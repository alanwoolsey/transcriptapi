from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.student_routes import router
from app.services.admissions_ops_service import AdmissionsOpsService
from app.services.operations_service import OperationsService
from app.services.student_360_service import Student360Service


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=uuid4()),
            authorization=SimpleNamespace(can=lambda permission: True),
        )

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_list_students_returns_records(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(
        student_routes.student_service,
        "list_students",
        lambda tenant_id, q=None, **kwargs: {
            "students": [
                {
                    "id": "student-1",
                    "name": "Hunter Haymore",
                    "program": "Transcript intake",
                    "institutionGoal": "Grantsville High",
                    "stage": "Decision-ready",
                    "risk": "Low",
                    "fitScore": 86,
                    "depositLikelihood": 61,
                    "summary": "Latest transcript parsed from Grantsville High. Outcome draft prepared for review.",
                    "gpa": 0.0,
                    "creditsAccepted": 0,
                    "transcriptsCount": 1,
                    "advisor": "Unassigned",
                    "tags": ["Transcript intake", "Low", "Decision-ready"],
                    "nextBestAction": "Open the student record and review the latest transcript outcome.",
                }
            ],
            "total": 1,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["students"][0]["name"] == "Hunter Haymore"
    assert payload["students"][0]["institutionGoal"] == "Grantsville High"
    assert "transcripts" not in payload["students"][0]


def test_list_students_passes_search_query(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_list_students(tenant_id, q=None, **kwargs):
        captured["tenant_id"] = tenant_id
        captured["q"] = q
        captured.update(kwargs)
        return {"students": [], "total": 0}

    monkeypatch.setattr(student_routes.student_service, "list_students", fake_list_students)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students?q=hunter")

    assert response.status_code == 200
    assert captured["q"] == "hunter"
    assert captured["limit"] == 50


def test_get_student_returns_detail_record(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_get_student(tenant_id, student_id, authorization=None):
        captured["tenant_id"] = tenant_id
        captured["student_id"] = student_id
        return {
            "id": student_id,
            "name": "Hunter Haymore",
            "preferredName": "Hunter",
            "email": None,
            "phone": None,
            "program": "Transcript intake",
            "institutionGoal": "Grantsville High",
            "stage": "Decision-ready",
            "risk": "Low",
            "fitScore": 86,
            "depositLikelihood": 61,
            "summary": "Latest transcript parsed from Grantsville High. Outcome draft prepared for review.",
            "gpa": 0.0,
            "creditsAccepted": 0,
            "transcriptsCount": 1,
            "advisor": "Unassigned",
            "tags": ["Transcript intake", "Low", "Decision-ready"],
            "nextBestAction": "Open the student record and review the latest transcript outcome.",
            "city": "Location pending",
            "lastActivity": "2026-04-19T15:21:59Z",
            "checklist": [{"label": "Identity matched", "done": True}],
            "transcripts": [],
            "termGpa": [],
            "recommendation": {
                "summary": "Latest transcript is ready for counselor review.",
                "fitNarrative": "Current transcript evidence from Grantsville High was parsed successfully and is available for review.",
                "nextBestAction": "Open the student record and review the latest transcript outcome.",
            },
        }

    monkeypatch.setattr(student_routes.student_service, "get_student", fake_get_student)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/student-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["student"]["id"] == "student-1"
    assert payload["student"]["recommendation"]["nextBestAction"] == payload["student"]["nextBestAction"]
    assert captured["student_id"] == "student-1"


def test_get_student_returns_404_when_missing(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(student_routes.student_service, "get_student", lambda tenant_id, student_id, authorization=None: None)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/missing-student")

    assert response.status_code == 404


def test_get_student_timeline_returns_events(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_get_timeline(tenant_id, student_id, authorization=None):
        captured["student_id"] = student_id
        return {
            "events": [
                {
                    "id": "evt-1",
                    "type": "checklist",
                    "title": "Official transcript marked complete",
                    "description": "Updated checklist item.",
                    "occurredAt": "2026-06-04T15:30:00Z",
                    "actor": {"id": "usr-1", "name": "Elian Brooks", "type": "user"},
                    "source": "checklist",
                    "status": "complete",
                    "entity": {"type": "student_checklist_item", "id": "chk-1"},
                    "sensitivityTier": "standard",
                }
            ]
        }

    monkeypatch.setattr(student_routes.student_service, "get_student_timeline", fake_get_timeline)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students/student-1/timeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"][0]["type"] == "checklist"
    assert captured["student_id"] == "student-1"


def test_student_identifier_variants_strip_leading_zeros():
    assert Student360Service()._student_identifier_variants("0002124578") == ["0002124578", "2124578"]
    assert AdmissionsOpsService()._student_identifier_variants("0002124578") == ["0002124578", "2124578"]
    assert OperationsService()._student_identifier_variants("0002124578") == ["0002124578", "2124578"]
