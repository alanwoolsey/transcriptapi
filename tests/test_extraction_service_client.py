import httpx

from app.core.config import settings
from app.services.extraction_service_client import ExternalExtractionServiceClient


def test_external_extraction_client_uploads_polls_and_reads_results(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("x-tenant-id")))
        if request.method == "POST" and request.url.path == "/api/v1/transcripts/uploads":
            body = request.read()
            assert b'name="document_type"' in body
            assert b"college" in body
            assert b'name="use_bedrock"' in body
            assert b"false" in body
            return httpx.Response(
                202,
                json={
                    "transcriptId": "remote-tx-1",
                    "documentUploadId": "remote-doc-upload-1",
                    "parseRunId": "remote-run-1",
                    "status": "processing",
                },
            )
        if request.method == "GET" and request.url.path == "/api/v1/transcripts/uploads/remote-tx-1/status":
            return httpx.Response(
                200,
                json={
                    "transcriptId": "remote-tx-1",
                    "documentUploadId": "remote-doc-upload-1",
                    "parseRunId": "remote-run-1",
                    "status": "completed",
                    "error": None,
                    "completed": True,
                },
            )
        if request.method == "GET" and request.url.path == "/api/v1/transcripts/remote-tx-1/results":
            return httpx.Response(
                200,
                json={
                    "documentId": "remote-result-doc",
                    "demographic": {"firstName": "Jane", "lastName": "Smith", "studentId": "123"},
                    "courses": [],
                    "gradePointMap": [],
                    "grandGPA": {},
                    "termGPAs": [],
                    "audit": [],
                    "metadata": {},
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    original_client = httpx.Client

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(settings, "extraction_service_url", "https://extract.example.test/")
    monkeypatch.setattr(settings, "extraction_service_poll_interval_seconds", 0.1)
    monkeypatch.setattr(httpx, "Client", mock_client)

    result = ExternalExtractionServiceClient().process(
        filename="one.pdf",
        content=b"%PDF-1.4 fake",
        content_type="application/pdf",
        requested_document_type="college",
        use_bedrock=False,
        tenant_id="tenant-123",
    )

    assert result["documentId"] == "remote-result-doc"
    assert result["metadata"]["externalExtraction"] == {
        "serviceUrl": "https://extract.example.test",
        "transcriptId": "remote-tx-1",
        "documentUploadId": "remote-doc-upload-1",
        "parseRunId": "remote-run-1",
        "status": "completed",
    }
    assert calls == [
        ("POST", "/api/v1/transcripts/uploads", "tenant-123"),
        ("GET", "/api/v1/transcripts/uploads/remote-tx-1/status", "tenant-123"),
        ("GET", "/api/v1/transcripts/remote-tx-1/results", "tenant-123"),
    ]
