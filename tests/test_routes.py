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
    storage_calls = []
    monkeypatch.setattr(
        routes.document_storage,
        "store_bytes",
        lambda **kwargs: storage_calls.append(kwargs),
    )

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
    assert storage_calls[0]["storage_key"] == "tx-1/one.pdf"


def test_start_transcript_upload_accepts_zip_and_returns_batch(monkeypatch):
    from app.api import routes

    monkeypatch.setattr(
        routes.persistence,
        "create_processing_upload_batch",
        lambda **kwargs: {
            "batchId": "batch-1",
            "status": "processing",
            "totalFiles": 2,
            "completedFiles": 0,
            "failedFiles": 0,
            "items": [
                {
                    "filename": "one.pdf",
                    "transcriptId": "tx-1",
                    "documentUploadId": "du-1",
                    "parseRunId": "pr-1",
                    "status": "processing",
                },
                {
                    "filename": "two.txt",
                    "transcriptId": "tx-2",
                    "documentUploadId": "du-2",
                    "parseRunId": "pr-2",
                    "status": "processing",
                },
            ],
        },
    )

    background_calls = []

    def fake_background(**kwargs):
        background_calls.append(kwargs)

    monkeypatch.setattr(routes, "_process_transcript_upload_batch", fake_background)
    storage_calls = []
    monkeypatch.setattr(
        routes.document_storage,
        "store_bytes",
        lambda **kwargs: storage_calls.append(kwargs),
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("one.pdf", b"%PDF-1.4 fake")
        archive.writestr("nested/two.txt", b"Example transcript")

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/v1/transcripts/uploads",
        files={"file": ("batch.zip", buf.getvalue(), "application/zip")},
        data={"document_type": "college", "use_bedrock": "false"},
    )

    assert response.status_code == 202
    assert response.json()["batchId"] == "batch-1"
    assert response.json()["totalFiles"] == 2
    assert len(background_calls) == 1
    assert len(background_calls[0]["batch_items"]) == 2
    assert background_calls[0]["batch_items"][0]["transcript_id"] == "tx-1"
    assert background_calls[0]["batch_items"][1]["transcript_id"] == "tx-2"
    assert storage_calls[0]["storage_key"] == "tx-1/one.pdf"
    assert storage_calls[1]["storage_key"] == "tx-2/two.txt"


def test_process_transcript_upload_batch_processes_all_items(monkeypatch):
    from app.api import routes

    calls = []

    def fake_process_transcript_upload(**kwargs):
        calls.append(kwargs["transcript_id"])

    monkeypatch.setattr(routes, "_process_transcript_upload", fake_process_transcript_upload)

    routes._process_transcript_upload_batch(
        batch_items=[
            {
                "transcript_id": "tx-1",
                "filename": "one.pdf",
                "content": b"one",
                "content_type": "application/pdf",
            },
            {
                "transcript_id": "tx-2",
                "filename": "two.pdf",
                "content": b"two",
                "content_type": "application/pdf",
            },
        ],
        tenant_id="tenant-123",
        requested_document_type="college",
        use_bedrock=False,
    )

    assert sorted(calls) == ["tx-1", "tx-2"]


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


def test_get_transcript_upload_batch_status(monkeypatch):
    from app.api import routes

    monkeypatch.setattr(
        routes.persistence,
        "get_upload_batch_status",
        lambda batch_id, tenant_id: {
            "batchId": batch_id,
            "status": "processing",
            "totalFiles": 2,
            "completedFiles": 1,
            "failedFiles": 0,
            "activeFiles": 1,
            "items": [
                {
                    "filename": "one.pdf",
                    "transcriptId": "tx-1",
                    "documentUploadId": "du-1",
                    "parseRunId": "pr-1",
                    "status": "completed",
                    "error": None,
                    "completed": True,
                    "startedAt": "2026-04-19T17:35:00Z",
                    "completedAt": "2026-04-19T17:35:08Z",
                },
                {
                    "filename": "two.txt",
                    "transcriptId": "tx-2",
                    "documentUploadId": "du-2",
                    "parseRunId": "pr-2",
                    "status": "processing",
                    "error": None,
                    "completed": False,
                    "startedAt": "2026-04-19T17:35:01Z",
                    "completedAt": None,
                },
            ],
        },
    )

    client = TestClient(_build_test_app())
    response = client.get("/api/v1/transcripts/uploads/batches/batch-1/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["completedFiles"] == 1
    assert payload["activeFiles"] == 1
    assert payload["items"][0]["completed"] is True
    assert payload["items"][0]["startedAt"] == "2026-04-19T17:35:00Z"


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
