from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.student_routes import router


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(tenant=SimpleNamespace(id=uuid4()))

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_list_students_returns_records(monkeypatch):
    from app.api import student_routes

    monkeypatch.setattr(
        student_routes.student_service,
        "list_students",
        lambda tenant_id, q=None: [
            {
                "id": "student-1",
                "name": "Hunter Haymore",
                "preferredName": "Hunter",
                "email": None,
                "phone": None,
                "program": "Transcript intake",
                "institutionGoal": "Grantsville High",
                "stage": "Decision-ready",
                "risk": "Low",
                "advisor": "Unassigned",
                "city": "Location pending",
                "gpa": 0.0,
                "creditsAccepted": 0,
                "transcriptsCount": 1,
                "fitScore": 86,
                "depositLikelihood": 61,
                "lastActivity": "2026-04-19T15:21:59Z",
                "tags": ["Transcript intake", "Low", "Decision-ready"],
                "summary": "Latest transcript parsed from Grantsville High. Outcome draft prepared for review.",
                "checklist": [{"label": "Identity matched", "done": True}],
                "transcripts": [],
                "termGpa": [],
                "recommendation": {
                    "summary": "Latest transcript is ready for counselor review.",
                    "fitNarrative": "Current transcript evidence from Grantsville High was parsed successfully and is available for review.",
                    "nextBestAction": "Open the student record and review the latest transcript outcome.",
                },
            }
        ],
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "Hunter Haymore"
    assert payload[0]["institutionGoal"] == "Grantsville High"


def test_list_students_passes_search_query(monkeypatch):
    from app.api import student_routes

    captured = {}

    def fake_list_students(tenant_id, q=None):
        captured["tenant_id"] = tenant_id
        captured["q"] = q
        return []

    monkeypatch.setattr(student_routes.student_service, "list_students", fake_list_students)

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/students?q=hunter")

    assert response.status_code == 200
    assert captured["q"] == "hunter"
