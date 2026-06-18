import time
from typing import Any

import httpx

from app.core.config import settings


class ExternalExtractionServiceClient:
    @property
    def is_enabled(self) -> bool:
        return bool((settings.extraction_service_url or "").strip())

    def process(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None,
        requested_document_type: str,
        use_bedrock: bool,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        base_url = self._base_url()
        headers = self._headers(tenant_id)
        timeout = settings.extraction_service_request_timeout_seconds

        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            upload_payload = self._upload(
                client=client,
                headers=headers,
                filename=filename,
                content=content,
                content_type=content_type,
                requested_document_type=requested_document_type,
                use_bedrock=use_bedrock,
            )
            remote_transcript_id = str(upload_payload.get("transcriptId") or "")
            if not remote_transcript_id:
                raise ValueError("Extraction service did not return a transcriptId.")

            final_status = self._wait_for_completion(
                client=client,
                headers=headers,
                transcript_id=remote_transcript_id,
            )
            result = self._get_results(
                client=client,
                headers=headers,
                transcript_id=remote_transcript_id,
            )

        result.setdefault("metadata", {})
        result["metadata"]["externalExtraction"] = {
            "serviceUrl": base_url,
            "transcriptId": remote_transcript_id,
            "documentUploadId": upload_payload.get("documentUploadId"),
            "parseRunId": upload_payload.get("parseRunId"),
            "status": final_status.get("status"),
        }
        return result

    def _upload(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str] | None,
        filename: str,
        content: bytes,
        content_type: str | None,
        requested_document_type: str,
        use_bedrock: bool,
    ) -> dict[str, Any]:
        response = client.post(
            "/api/v1/transcripts/uploads",
            headers=headers,
            data={
                "document_type": requested_document_type or "auto",
                "use_bedrock": "true" if use_bedrock else "false",
            },
            files={
                "file": (
                    filename,
                    content,
                    content_type or "application/octet-stream",
                )
            },
        )
        self._raise_for_response(response, "upload document to extraction service")
        payload = response.json()
        if "batchId" in payload:
            raise ValueError("Extraction service returned a batch response for a single document upload.")
        return payload

    def _wait_for_completion(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str] | None,
        transcript_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + settings.extraction_service_poll_timeout_seconds
        last_status: dict[str, Any] | None = None

        while time.monotonic() <= deadline:
            response = client.get(f"/api/v1/transcripts/uploads/{transcript_id}/status", headers=headers)
            self._raise_for_response(response, "read extraction status")
            last_status = response.json()
            status = str(last_status.get("status") or "").lower()
            if last_status.get("completed") is True or status == "completed":
                return last_status
            if status in {"failed", "error", "canceled", "cancelled"}:
                error = last_status.get("error") or f"Extraction service status was {status}."
                raise ValueError(str(error))
            time.sleep(max(0.1, settings.extraction_service_poll_interval_seconds))

        status_text = last_status.get("status") if last_status else "unknown"
        raise TimeoutError(f"Extraction service timed out waiting for transcript {transcript_id}; last status: {status_text}.")

    def _get_results(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str] | None,
        transcript_id: str,
    ) -> dict[str, Any]:
        response = client.get(f"/api/v1/transcripts/{transcript_id}/results", headers=headers)
        self._raise_for_response(response, "read extraction results")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Extraction service returned an invalid result payload.")
        return payload

    def _base_url(self) -> str:
        base_url = (settings.extraction_service_url or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("EXTRACTION_SERVICE_URL is not configured.")
        return base_url

    def _headers(self, tenant_id: str | None) -> dict[str, str] | None:
        if settings.extraction_service_forward_tenant_header and tenant_id:
            return {"X-Tenant-Id": tenant_id}
        return None

    def _raise_for_response(self, response: httpx.Response, action: str) -> None:
        if response.is_success:
            return
        detail: Any
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise ValueError(f"Could not {action}: HTTP {response.status_code}: {detail}")
