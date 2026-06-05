from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.prospect_routes import router
from app.db import get_db


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(
            tenant=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4()),
            authorization=SimpleNamespace(can=lambda permission: True),
        )

    def override_db():
        yield SimpleNamespace()

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.dependency_overrides[get_db] = override_db
    app.include_router(router, prefix="/api/v1")
    return app


def _prospect_payload():
    return {
        "firstName": "Mira",
        "lastName": "Holloway",
        "email": "mira@example.edu",
        "phone": "555-0100",
        "population": "transfer",
        "programInterest": "BS Nursing Transfer",
        "termInterest": "Fall 2026",
        "priorInstitution": "River County College",
        "source": "manual_entry",
        "sourceCategory": "direct",
        "campaign": "transfer-open-house",
        "consent": True,
        "question": "How many credits will transfer?",
        "transcriptUploadId": "upl_123",
    }


def test_create_prospect_inquiry_returns_live_summary(monkeypatch):
    from app.api import prospect_routes

    captured = {}

    def fake_create_inquiry(db, *, tenant_id, actor_user_id, payload):
        captured["payload"] = payload
        return {
            "prospect": {
                "prospectId": "pro_123",
                "studentId": None,
                "studentName": "Mira Holloway",
                "status": "fit_ready",
                "population": "transfer",
                "programInterest": "BS Nursing Transfer",
                "termInterest": "Fall 2026",
                "source": "manual_entry",
                "programFit": {
                    "program": "BS Nursing Transfer",
                    "fitScore": 88,
                    "confidence": 0.82,
                    "transferCredits": 42,
                    "estimatedCompletion": "2.1 years",
                    "scholarshipPotential": "$8.5k-$11k",
                },
                "nextStep": {"code": "start_application", "label": "Start application", "url": "/apply?prospectId=pro_123"},
                "counselor": {"id": "usr_42", "name": "Elian Brooks", "email": "elian@example.edu"},
                "transcriptStatus": "fit_ready",
                "missingItems": ["Official transcript", "Application form"],
                "signals": [{"label": "Population", "value": "transfer"}],
            }
        }

    monkeypatch.setattr(prospect_routes.prospect_service, "create_inquiry", fake_create_inquiry)

    response = TestClient(_build_test_app()).post("/api/v1/prospects/inquiries", json=_prospect_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["prospect"]["prospectId"] == "pro_123"
    assert payload["prospect"]["programFit"]["fitScore"] == 88
    assert captured["payload"].email == "mira@example.edu"


def test_create_prospect_transcript_upload_returns_upload(monkeypatch):
    from app.api import prospect_routes

    captured = {}

    def fake_upload(db, **kwargs):
        captured.update(kwargs)
        return {"uploadId": "upl_123", "status": "received", "filename": "mira.pdf"}

    monkeypatch.setattr(prospect_routes.prospect_service, "create_transcript_upload", fake_upload)

    response = TestClient(_build_test_app()).post(
        "/api/v1/prospects/transcripts/uploads",
        data={"email": "mira@example.edu", "population": "transfer", "programInterest": "BS Nursing"},
        files={"file": ("mira.pdf", b"pdf bytes", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["uploadId"] == "upl_123"
    assert captured["filename"] == "mira.pdf"
    assert captured["content"] == b"pdf bytes"


def test_get_upload_status_returns_processing_state(monkeypatch):
    from app.api import prospect_routes

    monkeypatch.setattr(
        prospect_routes.prospect_service,
        "get_upload_status",
        lambda tenant_id, upload_id: {
            "uploadId": upload_id,
            "status": "fit_ready",
            "processingRunId": "run_123",
            "message": "Fit preview is ready.",
        },
    )

    response = TestClient(_build_test_app()).get("/api/v1/prospects/transcripts/uploads/upl_123/status")

    assert response.status_code == 200
    assert response.json()["status"] == "fit_ready"


def test_get_prospect_fit_returns_preview(monkeypatch):
    from app.api import prospect_routes

    monkeypatch.setattr(
        prospect_routes.prospect_service,
        "get_fit",
        lambda tenant_id, prospect_id: {
            "programFit": {"program": "BS Nursing", "fitScore": 91, "confidence": 0.84, "transferCredits": 42},
            "missingItems": ["Application form"],
            "signals": [{"label": "Source", "value": "manual_entry"}],
            "nextStep": {"code": "start_application", "label": "Start application"},
        },
    )

    response = TestClient(_build_test_app()).get("/api/v1/prospects/pro_123/fit")

    assert response.status_code == 200
    assert response.json()["programFit"]["fitScore"] == 91


def test_convert_prospect_returns_student_id(monkeypatch):
    from app.api import prospect_routes

    monkeypatch.setattr(
        prospect_routes.prospect_service,
        "convert_application",
        lambda db, **kwargs: {"studentId": "student-1", "prospectId": kwargs["prospect_id"], "status": "converted"},
    )

    response = TestClient(_build_test_app()).post("/api/v1/prospects/pro_123/convert-application")

    assert response.status_code == 200
    assert response.json()["studentId"] == "student-1"


def test_create_prospect_inquiry_maps_validation_error_to_422(monkeypatch):
    from app.api import prospect_routes
    from app.services.prospect_service import ProspectValidationError

    def fake_create_inquiry(db, **kwargs):
        raise ProspectValidationError("Consent is required.")

    monkeypatch.setattr(prospect_routes.prospect_service, "create_inquiry", fake_create_inquiry)

    response = TestClient(_build_test_app()).post("/api/v1/prospects/inquiries", json=_prospect_payload())

    assert response.status_code == 422
    assert response.json()["detail"] == "Consent is required."
