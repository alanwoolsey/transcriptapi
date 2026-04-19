import io
import zipfile
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant_context
from app.api.routes import router


def _build_test_app() -> FastAPI:
    def override_auth_context():
        yield SimpleNamespace(tenant=SimpleNamespace(id="tenant-123"), user=SimpleNamespace(id=uuid4()))

    app = FastAPI()
    app.dependency_overrides[get_current_tenant_context] = override_auth_context
    app.include_router(router, prefix="/api/v1")
    return app


def test_parse_endpoint_processes_zip_upload(monkeypatch):
    from app.api import routes

    calls = []

    def fake_process(filename, content, content_type, requested_document_type, use_bedrock):
        calls.append(filename)
        if filename == "bad.txt":
            raise ValueError("bad file")
        return {
            "documentId": f"doc-{filename}",
            "demographic": {
                "firstName": "Jane",
                "lastName": "Smith",
                "middleName": "",
                "studentId": "123",
                "institutionName": "Example U",
            },
            "courses": [],
            "gradePointMap": [],
            "grandGPA": {"unitsEarned": 0.0, "simpleGPA": 0.0, "cumulativeGPA": 0.0, "weightedGPA": 0.0},
            "termGPAs": [],
            "audit": [],
            "isOfficial": True,
            "isFinalized": False,
            "finalizedAt": None,
            "finalizedBy": None,
            "isFraudulent": False,
            "fraudFlaggedAt": None,
            "metadata": {},
        }

    monkeypatch.setattr(routes.pipeline, "process", fake_process)
    monkeypatch.setattr(routes.persistence, "persist_upload", lambda **kwargs: {})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("one.pdf", b"%PDF-1.4 fake")
        archive.writestr("nested/two.txt", b"Example transcript")
        archive.writestr("bad.txt", b"bad")
        archive.writestr("ignore.csv", b"nope")

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/transcripts/parse",
        files={"file": ("batch.zip", buf.getvalue(), "application/zip")},
        data={"document_type": "auto", "use_bedrock": "false"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["totalFiles"] == 3
    assert payload["processedFiles"] == 2
    assert payload["failedFiles"] == 1
    assert calls == ["one.pdf", "two.txt", "bad.txt"]


def test_parse_endpoint_rejects_invalid_zip():
    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/transcripts/parse",
        files={"file": ("batch.zip", b"not a zip", "application/zip")},
        data={"document_type": "auto", "use_bedrock": "false"},
    )

    assert response.status_code == 400
    assert "valid ZIP archive" in response.json()["detail"]


def test_parse_endpoint_persists_single_upload(monkeypatch):
    from app.api import routes

    def fake_process(filename, content, content_type, requested_document_type, use_bedrock):
        return {
            "documentId": "doc-123",
            "demographic": {
                "firstName": "Jane",
                "lastName": "Smith",
                "middleName": "",
                "studentId": "123",
                "institutionName": "Example U",
            },
            "courses": [],
            "gradePointMap": [],
            "grandGPA": {"unitsEarned": 0.0, "simpleGPA": 0.0, "cumulativeGPA": 0.0, "weightedGPA": 0.0},
            "termGPAs": [],
            "audit": [],
            "isOfficial": True,
            "isFinalized": False,
            "finalizedAt": None,
            "finalizedBy": None,
            "isFraudulent": False,
            "fraudFlaggedAt": None,
            "metadata": {"document_type": "college_transcript"},
        }

    persist_calls = []

    def fake_persist_upload(filename, content, content_type, requested_document_type, use_bedrock, response_payload, tenant_id=None):
        persist_calls.append(
            {
                "filename": filename,
                "content_type": content_type,
                "requested_document_type": requested_document_type,
                "use_bedrock": use_bedrock,
                "document_id": response_payload["documentId"],
                "tenant_id": tenant_id,
            }
        )
        return {"transcriptId": "tx-1"}

    monkeypatch.setattr(routes.pipeline, "process", fake_process)
    monkeypatch.setattr(routes.persistence, "persist_upload", fake_persist_upload)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/transcripts/parse",
        files={"file": ("one.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"document_type": "college", "use_bedrock": "false"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["persistence"]["transcriptId"] == "tx-1"
    assert payload["metadata"]["tenantId"] == "tenant-123"
    assert persist_calls == [
        {
            "filename": "one.pdf",
            "content_type": "application/pdf",
            "requested_document_type": "college",
            "use_bedrock": False,
            "document_id": "doc-123",
            "tenant_id": "tenant-123",
        }
    ]


def test_start_transcript_upload_returns_processing_ids(monkeypatch):
    from app.api import routes

    monkeypatch.setattr(
        routes.persistence,
        "create_processing_upload",
        lambda **kwargs: {
            "transcriptId": "tx-1",
            "documentUploadId": "du-1",
            "parseRunId": "pr-1",
            "status": "processing",
        },
    )

    background_calls = []

    def fake_background(**kwargs):
        background_calls.append(kwargs)

    monkeypatch.setattr(routes, "_process_transcript_upload", fake_background)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/transcripts/uploads",
        files={"file": ("one.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"document_type": "college", "use_bedrock": "false"},
    )

    assert response.status_code == 202
    assert response.json() == {
        "transcriptId": "tx-1",
        "documentUploadId": "du-1",
        "parseRunId": "pr-1",
        "status": "processing",
    }
    assert background_calls


def test_get_transcript_upload_status(monkeypatch):
    from app.api import routes

    monkeypatch.setattr(
        routes.persistence,
        "get_transcript_status",
        lambda transcript_id, tenant_id: {
            "transcriptId": transcript_id,
            "documentUploadId": "du-1",
            "parseRunId": "pr-1",
            "status": "completed",
            "error": None,
            "completed": True,
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/transcripts/uploads/tx-1/status")

    assert response.status_code == 200
    assert response.json()["completed"] is True


def test_get_transcript_results(monkeypatch):
    from app.api import routes

    monkeypatch.setattr(
        routes.persistence,
        "get_transcript_result",
        lambda transcript_id, tenant_id: {
            "documentId": transcript_id,
            "demographic": {
                "firstName": "Jane",
                "lastName": "Smith",
                "middleName": "",
                "studentId": "123",
                "institutionName": "Example U",
            },
            "courses": [],
            "gradePointMap": [],
            "grandGPA": {"unitsEarned": 0.0, "simpleGPA": 0.0, "cumulativeGPA": 0.0, "weightedGPA": 0.0},
            "termGPAs": [],
            "audit": [],
            "isOfficial": True,
            "isFinalized": False,
            "finalizedAt": None,
            "finalizedBy": None,
            "isFraudulent": False,
            "fraudFlaggedAt": None,
            "metadata": {"tenantId": tenant_id},
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/transcripts/tx-1/results")

    assert response.status_code == 200
    assert response.json()["documentId"] == "tx-1"
