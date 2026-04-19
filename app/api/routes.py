import logging
from zipfile import BadZipFile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.api_models import BatchParseTranscriptItem, BatchParseTranscriptResponse, ParseTranscriptResponse
from app.services.pipeline import TranscriptPipeline
from app.services.persistence import TranscriptPersistenceService
from app.utils.file_utils import extract_supported_files_from_zip, get_extension

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcripts", tags=["transcripts"])
pipeline = TranscriptPipeline()
persistence = TranscriptPersistenceService()


@router.post("/parse", response_model=ParseTranscriptResponse | BatchParseTranscriptResponse)
async def parse_transcript(
    file: UploadFile = File(...),
    document_type: str = Form("auto"),
    use_bedrock: str | None = Form(None),
) -> ParseTranscriptResponse | BatchParseTranscriptResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    normalized_use_bedrock = _normalize_use_bedrock(use_bedrock)
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
            )
        result = _parse_single_upload(
            filename=filename,
            content=content,
            content_type=file.content_type,
            requested_document_type=document_type,
            use_bedrock=normalized_use_bedrock,
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


def _parse_single_upload(
    filename: str,
    content: bytes,
    content_type: str | None,
    requested_document_type: str,
    use_bedrock: bool,
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
    )
    if persistence_ids:
        result.setdefault("metadata", {})
        result["metadata"]["persistence"] = persistence_ids
    return result


def _parse_zip_upload(
    filename: str,
    content: bytes,
    content_type: str | None,
    requested_document_type: str,
    use_bedrock: bool,
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
