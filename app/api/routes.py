import logging
from zipfile import BadZipFile

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Path, UploadFile, status

from app.api.dependencies import AuthenticatedTenantContext, get_current_tenant_context
from app.models.api_models import (
    BatchParseTranscriptItem,
    BatchParseTranscriptResponse,
    ParseTranscriptResponse,
    StartTranscriptUploadResponse,
    TranscriptUploadStatusResponse,
)
from app.services.pipeline import TranscriptPipeline
from app.services.persistence import TranscriptPersistenceService
from app.utils.file_utils import extract_supported_files_from_zip, get_extension

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcripts", tags=["transcripts"])
pipeline = TranscriptPipeline()
persistence = TranscriptPersistenceService()


@router.post("/uploads", response_model=StartTranscriptUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_transcript_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str = Form("auto"),
    use_bedrock: str | None = Form(None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> StartTranscriptUploadResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    filename = file.filename or "upload.bin"
    if get_extension(filename) == ".zip":
        raise HTTPException(status_code=400, detail="ZIP uploads are not supported by the async transcript upload API.")

    normalized_use_bedrock = _normalize_use_bedrock(use_bedrock)
    tenant_id = str(auth_context.tenant.id)

    try:
        upload_record = persistence.create_processing_upload(
            filename=filename,
            content=content,
            content_type=file.content_type,
            requested_document_type=document_type,
            use_bedrock=normalized_use_bedrock,
            tenant_id=tenant_id,
            uploaded_by_user_id=auth_context.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(
        _process_transcript_upload,
        transcript_id=upload_record["transcriptId"],
        tenant_id=tenant_id,
        filename=filename,
        content=content,
        content_type=file.content_type,
        requested_document_type=document_type,
        use_bedrock=normalized_use_bedrock,
    )

    return StartTranscriptUploadResponse(**upload_record)


@router.get(
    "/uploads/{transcript_id}/status",
    response_model=TranscriptUploadStatusResponse,
)
def get_transcript_upload_status(
    transcript_id: str = Path(...),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> TranscriptUploadStatusResponse:
    try:
        status_payload = persistence.get_transcript_status(transcript_id=transcript_id, tenant_id=str(auth_context.tenant.id))
    except ValueError as exc:
        detail = str(exc)
        if detail == "Transcript not found.":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return TranscriptUploadStatusResponse(**status_payload)


@router.get("/{transcript_id}/results", response_model=ParseTranscriptResponse)
def get_transcript_results(
    transcript_id: str = Path(...),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ParseTranscriptResponse:
    try:
        result = persistence.get_transcript_result(transcript_id=transcript_id, tenant_id=str(auth_context.tenant.id))
    except ValueError as exc:
        detail = str(exc)
        if detail == "Transcript not found.":
            raise HTTPException(status_code=404, detail=detail) from exc
        if detail == "Transcript result is not ready.":
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return ParseTranscriptResponse(**result)


@router.post("/parse", response_model=ParseTranscriptResponse | BatchParseTranscriptResponse)
async def parse_transcript(
    file: UploadFile = File(...),
    document_type: str = Form("auto"),
    use_bedrock: str | None = Form(None),
    auth_context: AuthenticatedTenantContext = Depends(get_current_tenant_context),
) -> ParseTranscriptResponse | BatchParseTranscriptResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    normalized_use_bedrock = _normalize_use_bedrock(use_bedrock)
    tenant_id = str(auth_context.tenant.id)
    logger.info("Route normalized use_bedrock raw_value=%s normalized_value=%s", use_bedrock, normalized_use_bedrock)

    try:
        filename = file.filename or "upload.bin"
        if get_extension(filename) == ".zip":
            return _parse_zip_upload(
                filename=filename,
                content=content,
                content_type=file.content_type,
                requested_document_type=document_type,
                use_bedrock=normalized_use_bedrock,
                tenant_id=tenant_id,
            )
        result = _parse_single_upload(
            filename=filename,
            content=content,
            content_type=file.content_type,
            requested_document_type=document_type,
            use_bedrock=normalized_use_bedrock,
            tenant_id=tenant_id,
        )
        return ParseTranscriptResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc


def _normalize_use_bedrock(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip().lower()
    if normalized == "":
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return True


def _process_transcript_upload(
    transcript_id: str,
    tenant_id: str,
    filename: str,
    content: bytes,
    content_type: str | None,
    requested_document_type: str,
    use_bedrock: bool,
) -> None:
    try:
        result = pipeline.process(
            filename=filename,
            content=content,
            content_type=content_type,
            requested_document_type=requested_document_type,
            use_bedrock=use_bedrock,
        )
        result.setdefault("metadata", {})
        result["metadata"]["tenantId"] = tenant_id
        persistence.complete_processing_upload(
            transcript_id=transcript_id,
            response_payload=result,
            tenant_id=tenant_id,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Async transcript processing failed transcript_id=%s", transcript_id)
        persistence.fail_processing_upload(transcript_id=transcript_id, tenant_id=tenant_id, error_message=str(exc))


def _parse_single_upload(
    filename: str,
    content: bytes,
    content_type: str | None,
    requested_document_type: str,
    use_bedrock: bool,
    tenant_id: str,
) -> dict:
    result = pipeline.process(
        filename=filename,
        content=content,
        content_type=content_type,
        requested_document_type=requested_document_type,
        use_bedrock=use_bedrock,
    )
    persistence_ids = persistence.persist_upload(
        filename=filename,
        content=content,
        content_type=content_type,
        requested_document_type=requested_document_type,
        use_bedrock=use_bedrock,
        response_payload=result,
        tenant_id=tenant_id,
    )
    if persistence_ids:
        result.setdefault("metadata", {})
        result["metadata"]["persistence"] = persistence_ids
    result.setdefault("metadata", {})
    result["metadata"]["tenantId"] = tenant_id
    return result


def _parse_zip_upload(
    filename: str,
    content: bytes,
    content_type: str | None,
    requested_document_type: str,
    use_bedrock: bool,
    tenant_id: str,
) -> BatchParseTranscriptResponse:
    try:
        files = extract_supported_files_from_zip(content)
    except BadZipFile as exc:
        raise ValueError(f"Uploaded file '{filename}' is not a valid ZIP archive.") from exc

    if not files:
        raise ValueError("ZIP archive did not contain any supported transcript files.")

    items: list[BatchParseTranscriptItem] = []
    processed_files = 0
    failed_files = 0

    for extracted_filename, extracted_content in files:
        try:
            result = _parse_single_upload(
                filename=extracted_filename,
                content=extracted_content,
                content_type=content_type,
                requested_document_type=requested_document_type,
                use_bedrock=use_bedrock,
                tenant_id=tenant_id,
            )
            items.append(
                BatchParseTranscriptItem(
                    filename=extracted_filename,
                    success=True,
                    result=ParseTranscriptResponse(**result),
                )
            )
            processed_files += 1
        except Exception as exc:
            items.append(
                BatchParseTranscriptItem(
                    filename=extracted_filename,
                    success=False,
                    error=str(exc),
                )
            )
            failed_files += 1

    return BatchParseTranscriptResponse(
        totalFiles=len(files),
        processedFiles=processed_files,
        failedFiles=failed_files,
        items=items,
    )
